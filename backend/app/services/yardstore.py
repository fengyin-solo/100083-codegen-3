"""堆存记录业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "yardstore"
YARD_MODULE = "yard"
REQUIRED_FIELDS = ["堆存单号", "关联箱号", "箱区编号"]
STATUS_ORDER = ["待进场", "堆存中", "待提离", "已提离"]
ACTION_RULES = {"确认进场": "堆存中", "确认提离": "已提离", "撤销堆存": "待进场"}
NEGATIVE_ACTIONS = ["撤销堆存"]

# 仍在箱区里的状态：待进场还没卸进箱区，已提离已经出场，都不算当前堆存量
IN_YARD_STATUSES = {"堆存中", "待提离"}
# 免堆期（天）：在堆超过这个天数就记为超期箱
OVERDUE_DAYS = 7
# 堆存单写了箱区档案里不存在的箱区编号时，全景里归到这一格，保证合计仍与名单一致
UNASSIGNED_BLOCK = "未分配箱区"


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _is_overdue(row: dict[str, Any], today: date) -> bool:
    """在堆的箱子满足任一条件即算超期：堆存天数超过免堆期，或堆存结束日已过。"""
    if row.get("status") not in IN_YARD_STATUSES:
        return False
    days = _to_int(row.get("堆存天数"))
    if days is not None:
        return days > OVERDUE_DAYS
    end = _to_date(row.get("堆存结束"))
    return end is not None and end < today


class YardstoreService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("堆存单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"堆存单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于堆存记录可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"堆存单已{action}"

    def _rows_by_block(self) -> dict[str, list[dict[str, Any]]]:
        """把堆存单按箱区编号归堆；没写编号的归到空串，后面并入未分配箱区。"""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in store.rows(MODULE):
            code = str(row.get("箱区编号") or "").strip()
            grouped.setdefault(code, []).append(row)
        return grouped

    def _summarize(self, entries: list[dict[str, Any]], today: date) -> dict[str, int]:
        in_yard = [row for row in entries if row.get("status") in IN_YARD_STATUSES]
        return {
            "当前堆存量": len(in_yard),
            "超期箱数": sum(1 for row in in_yard if _is_overdue(row, today)),
            "堆存单数": len(entries),
        }

    def build_panorama(self) -> dict[str, Any]:
        """箱区全景：按堆放层数排格子，每格给当前堆存量与超期箱数。

        没有堆存数据的箱区照样出现在全景里，只在这一格标出缺什么；
        合计与堆存单名单用同一批数据算，保证两边对得上。
        """
        today = date.today()
        grouped = self._rows_by_block()
        blocks: list[dict[str, Any]] = []
        known_codes: set[str] = set()
        for yard in store.rows(YARD_MODULE):
            code = str(yard.get("箱区编号") or "").strip()
            known_codes.add(code)
            entries = grouped.get(code, [])
            tiers = _to_int(yard.get("堆放层数"))
            missing: list[str] = []
            if not entries:
                missing.append("暂无堆存数据")
            if tiers is None:
                missing.append("缺堆放层数")
            blocks.append({
                "箱区编号": code or f"箱区{yard.get('id')}",
                "箱区名称": yard.get("箱区名称") or "",
                "堆放层数": tiers,
                **self._summarize(entries, today),
                "缺失": missing,
            })
        leftovers = [row for code, rows in grouped.items() if code not in known_codes for row in rows]
        if leftovers:
            blocks.append({
                "箱区编号": UNASSIGNED_BLOCK,
                "箱区名称": "堆存单上的箱区编号在箱区档案里找不到",
                "堆放层数": None,
                **self._summarize(leftovers, today),
                "缺失": ["缺箱区主数据"],
            })
        blocks.sort(key=lambda block: (block["堆放层数"] is None, block["堆放层数"] or 0, block["箱区编号"]))
        totals = {
            "箱区数": len(blocks),
            "当前堆存量": sum(block["当前堆存量"] for block in blocks),
            "超期箱数": sum(block["超期箱数"] for block in blocks),
            "堆存单数": sum(block["堆存单数"] for block in blocks),
        }
        return {"blocks": blocks, "totals": totals}

    def block_detail(self, block_code: str) -> dict[str, Any] | None:
        """某一箱区的箱号与对应堆存单；箱区不存在时返回 None，由路由说明原因。"""
        code = block_code.strip()
        today = date.today()
        grouped = self._rows_by_block()
        if code == UNASSIGNED_BLOCK:
            known_codes = {str(yard.get("箱区编号") or "").strip() for yard in store.rows(YARD_MODULE)}
            entries = [row for c, rows in grouped.items() if c not in known_codes for row in rows]
            block_info = {"箱区编号": UNASSIGNED_BLOCK, "箱区名称": "堆存单上的箱区编号在箱区档案里找不到", "堆放层数": None}
        else:
            yard = next(
                (row for row in store.rows(YARD_MODULE) if str(row.get("箱区编号") or "").strip() == code),
                None,
            )
            if yard is None:
                return None
            entries = grouped.get(code, [])
            block_info = {
                "箱区编号": code,
                "箱区名称": yard.get("箱区名称") or "",
                "堆放层数": _to_int(yard.get("堆放层数")),
            }
        return {
            "block": block_info,
            "entries": [
                {
                    "id": row.get("id"),
                    "堆存单号": row.get("堆存单号"),
                    "关联箱号": row.get("关联箱号"),
                    "贝位号": row.get("贝位号"),
                    "堆存开始": row.get("堆存开始"),
                    "堆存结束": row.get("堆存结束"),
                    "堆存天数": row.get("堆存天数"),
                    "堆存状态": row.get("status"),
                    "超期": _is_overdue(row, today),
                }
                for row in entries
            ],
            "summary": self._summarize(entries, today),
        }
