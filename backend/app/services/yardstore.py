"""堆存记录业务规则：状态流转、字段校验、筛选口径与箱区全景聚合都收在这里。

全景视图以箱区档案（yard 表）为底图，把堆存单按箱区编号归并到对应格子；
某个箱区暂时没有堆存单，只影响这一格的展示，不会让整张全景变空。
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.store import store

MODULE = "yardstore"
YARD_MODULE = "yard"
REQUIRED_FIELDS = ["堆存单号", "关联箱号", "箱区编号"]
STATUS_ORDER = ["待进场", "堆存中", "待提离", "已提离"]
# 已实际在场的状态：堆存中与待提离仍占着箱位，算作当前堆存量
ACTIVE_STATUS = ["堆存中", "待提离"]
ACTION_RULES = {"确认进场": "堆存中", "确认提离": "已提离", "撤销堆存": "待进场"}
NEGATIVE_ACTIONS = ["撤销堆存"]
# 免费堆存期（天），超过即视为超期箱
FREE_STORAGE_DAYS = 7
_TIER_RE = re.compile(r"\d+")


def _parse_tier(value: Any) -> int | None:
    """把「4层」「6」这类堆放层数归一成整数；识别不出时返回 None，由调用方标注缺失。"""
    match = _TIER_RE.search(str(value or ""))
    return int(match.group()) if match else None


def _entry_status(row: dict[str, Any]) -> str:
    """堆存单状态以结构化的 status 为准，中文展示字段只作回退。"""
    return str(row.get("status") or row.get("堆存状态") or "").strip()


def _storage_days(row: dict[str, Any], today: date) -> int | None:
    """优先取已登记的堆存天数；没有登记时按堆存开始日期推算，再没有就返回 None。"""
    raw = row.get("堆存天数")
    try:
        if raw not in (None, ""):
            return int(raw)
    except (TypeError, ValueError):
        pass
    start = str(row.get("堆存开始") or "").strip()
    if start:
        try:
            start_day = date.fromisoformat(start)
        except ValueError:
            return None
        return max((today - start_day).days, 0)
    return None


def _annotate(row: dict[str, Any], today: date) -> dict[str, Any]:
    """给堆存单补上全景需要的派生标记：是否在场、堆存天数、是否超期。"""
    entry = dict(row)
    status = _entry_status(row)
    days = _storage_days(row, today)
    overdue = status in ACTIVE_STATUS and days is not None and days > FREE_STORAGE_DAYS
    entry["_在场"] = status in ACTIVE_STATUS
    entry["_堆存天数"] = days
    entry["_超期"] = overdue
    return entry


class YardstoreService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        yard_no: str | None = None,
        in_yard: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("堆存单号", ""))]
        if status:
            rows = [row for row in rows if _entry_status(row) == status]
        if yard_no:
            rows = [row for row in rows if str(row.get("箱区编号") or "").strip() == yard_no.strip()]
        if in_yard:
            rows = [row for row in rows if _entry_status(row) in ACTIVE_STATUS]
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

    def panorama(self) -> dict[str, Any]:
        """按箱区档案铺出全景底图，并把堆存单归并到每个格子。

        以箱区表为底，保证暂时无堆存单的箱区仍占一格；堆存单里出现、但箱区
        档案缺失的编号补成虚拟格，避免记录在全景里消失。
        """
        today = date.today()
        yard_rows = store.rows(YARD_MODULE)
        registry_available = bool(yard_rows)
        yards_by_no = {str(row.get("箱区编号") or "").strip(): row for row in yard_rows}

        groups: dict[str, list[dict[str, Any]]] = {}
        for row in store.rows(MODULE):
            yard_no = str(row.get("箱区编号") or "").strip()
            if not yard_no:
                continue
            groups.setdefault(yard_no, []).append(_annotate(row, today))

        cells: list[dict[str, Any]] = []
        seen: set[str] = set()
        for yard_no, yard in yards_by_no.items():
            seen.add(yard_no)
            cells.append(self._build_cell(yard_no, yard, groups.get(yard_no, []), today))
        # 箱区档案里查不到、但堆存单确实挂在这个编号下：补虚拟格并标明缺档案
        for yard_no, entries in groups.items():
            if yard_no not in seen:
                cells.append(self._build_cell(yard_no, None, entries, today))

        # 按堆放层数排（层数未知的沉底），同层再按箱区编号，保证平面格子排布稳定
        cells.sort(key=lambda cell: (cell["tier"] is None, cell["tier"] if cell["tier"] is not None else 0, cell["yard_no"]))

        tiers = sorted({cell["tier"] for cell in cells if cell["tier"] is not None})
        return {
            "as_of": today.isoformat(),
            "free_storage_days": FREE_STORAGE_DAYS,
            "registry_available": registry_available,
            "tiers": tiers,
            "totals": {
                "cells": len(cells),
                "storing": sum(cell["storing_count"] for cell in cells),
                "overdue": sum(cell["overdue_count"] for cell in cells),
                "entries": sum(cell["entry_count"] for cell in cells),
            },
            "cells": cells,
        }

    def yard_detail(self, yard_no: str) -> dict[str, Any] | None:
        """单个箱区的明细：箱区档案 + 归并到这一区的堆存单（带超期标记）。

        箱区编号在档案中不存在也不报错：作为缺档案的虚拟格返回，缺什么由字段说明。
        """
        yard_no = (yard_no or "").strip()
        if not yard_no:
            return None
        today = date.today()
        yard = next(
            (row for row in store.rows(YARD_MODULE) if str(row.get("箱区编号") or "").strip() == yard_no),
            None,
        )
        entries = [
            _annotate(row, today)
            for row in store.rows(MODULE)
            if str(row.get("箱区编号") or "").strip() == yard_no
        ]
        entries.sort(key=lambda item: (not item["_在场"], not item["_超期"], item["id"]))
        return self._build_cell(yard_no, yard, entries, today)

    def _build_cell(
        self,
        yard_no: str,
        yard: dict[str, Any] | None,
        entries: list[dict[str, Any]] | None,
        today: date,
    ) -> dict[str, Any]:
        """组装一个全景格子的汇总口径；名单与格子的数字都从这里来，保证对得上。"""
        entries = entries or []
        tier = _parse_tier((yard or {}).get("堆放层数"))
        active = [entry for entry in entries if entry["_在场"]]
        missing: list[str] = []
        if yard is None:
            missing.append("箱区档案")
        elif tier is None:
            missing.append("堆放层数")
        if not entries:
            missing.append("堆存单")
        return {
            "yard_no": yard_no,
            "yard_name": (yard or {}).get("箱区名称") or "",
            "tier": tier,
            "tier_label": str((yard or {}).get("堆放层数") or "").strip(),
            "yard_status": (yard or {}).get("status") or (yard or {}).get("箱区状态") or "",
            "registered": yard is not None,
            "storing_count": len(active),
            "overdue_count": sum(1 for entry in active if entry["_超期"]),
            "entry_count": len(entries),
            "missing": missing,
            "entries": entries,
        }
