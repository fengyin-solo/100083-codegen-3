<template>
  <section class="page" data-module="yardstore">
    <header class="page-head">
      <div>
        <h2>堆存记录管理</h2>
        <p class="page-desc">维护堆存单，围绕堆存单号、关联箱号、箱区编号、贝位号做登记、筛选与状态流转；全景按堆放层数展示各箱区当前堆存量与超期箱。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记堆存单</button>
        <button class="btn" type="button" @click="exportRows">导出堆存记录清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="view-tabs" role="tablist">
      <button
        type="button"
        role="tab"
        :class="['tab-btn', { active: view === 'list' }]"
        :aria-selected="view === 'list'"
        @click="switchView('list')"
      >
        箱区名单
      </button>
      <button
        type="button"
        role="tab"
        :class="['tab-btn', { active: view === 'panorama' }]"
        :aria-selected="view === 'panorama'"
        @click="switchView('panorama')"
      >
        堆存全景
      </button>
    </div>

    <!-- 名单视图：与全景用同一份接口口径，切换时保留筛选、分页与滚动位置 -->
    <div v-show="view === 'list'" class="view-pane">
      <form class="filter-bar" @submit.prevent="reload">
        <label class="filter-item">
          <span>堆存单号</span>
          <input v-model="filters.keyword" placeholder="按堆存单号检索" />
        </label>
        <label class="filter-item">
          <span>堆存状态</span>
          <select v-model="filters.status">
            <option value="">全部状态</option>
            <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>箱区编号</span>
          <input v-model="filters.yard_no" placeholder="按箱区编号精确过滤" />
        </label>
        <label class="filter-check">
          <input v-model="filters.in_yard" type="checkbox" />
          <span>仅看在场箱（堆存中、待提离）</span>
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      </form>

      <div v-if="filters.yard_no" class="sync-banner">
        <span>
          已按箱区 <strong>{{ filters.yard_no }}</strong> 过滤<template v-if="filters.in_yard">（仅在场箱，合计与全景该格数字一致）</template>
        </span>
        <button class="link" type="button" @click="goPanoramaCell(filters.yard_no)">在全景中定位此格</button>
      </div>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.id)">
            <td v-for="column in columns" :key="column">{{ row[column] === '' || row[column] == null ? '—' : row[column] }}</td>
            <td class="row-actions">
              <button
                v-for="action in actions"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="columns.length + 1" class="empty-state">当前条件下暂无堆存记录</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ total }} 条堆存记录（当前第 {{ page }} 页，每页 {{ pageSize }} 条）</span>
        <span class="pager">
          <button class="btn" type="button" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
          <button class="btn" type="button" :disabled="rows.length < pageSize" @click="changePage(page + 1)">下一页</button>
        </span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </div>

    <!-- 全景视图：格子始终渲染，缺数据的格子只标缺什么，不拖垮整张全景 -->
    <div v-show="view === 'panorama'" class="view-pane">
      <div v-if="panoError" class="pano-error">
        <span>{{ panoError }}</span>
        <button class="btn" type="button" @click="loadPanorama">重新加载全景</button>
      </div>
      <template v-else>
        <div class="pano-meta">
          <span>数据截至 {{ panorama?.as_of || '—' }} · 免费堆存期 {{ panorama?.free_storage_days ?? 7 }} 天，超期以红数标出</span>
          <span class="pano-totals">
            合计在库 <strong>{{ panorama?.totals.storing ?? 0 }}</strong> 箱 ·
            超期 <strong class="overdue-text">{{ panorama?.totals.overdue ?? 0 }}</strong> 箱 ·
            {{ panorama?.totals.cells ?? 0 }} 个箱区格
          </span>
        </div>
        <p v-if="panorama && !panorama.registry_available" class="pano-warn">箱区档案暂无数据，以下格子按堆存单里出现的箱区编号临时拼出。</p>

        <div class="pano-body">
          <div class="pano-grid-wrap">
            <div v-for="tier in panorama?.tiers ?? []" :key="tier" class="tier-row">
              <div class="tier-axis">{{ tier }}层区</div>
              <div class="tier-cells">
                <button
                  v-for="cell in cellsByTier[tier] ?? []"
                  :key="cell.yard_no"
                  type="button"
                  :class="['yard-cell', {
                    selected: selectedYard === cell.yard_no,
                    missing: cell.missing.length > 0,
                    'has-overdue': cell.overdue_count > 0,
                  }]"
                  @click="selectCell(cell.yard_no)"
                >
                  <span class="cell-name">{{ cell.yard_name || cell.yard_no }}</span>
                  <span class="cell-no">{{ cell.yard_no }}</span>
                  <span class="cell-count">{{ cell.storing_count }}</span>
                  <span class="cell-count-label">在库箱</span>
                  <span :class="['cell-overdue', { zero: cell.overdue_count === 0 }]">超期 {{ cell.overdue_count }}</span>
                  <span v-if="cell.missing.length" class="cell-missing">缺：{{ cell.missing.join('、') }}</span>
                  <span v-else class="cell-tier">{{ cell.tier_label }}</span>
                </button>
              </div>
            </div>
            <div v-if="unknownCells.length" class="tier-row">
              <div class="tier-axis unknown">层数未知</div>
              <div class="tier-cells">
                <button
                  v-for="cell in unknownCells"
                  :key="cell.yard_no"
                  type="button"
                  :class="['yard-cell', 'missing', { selected: selectedYard === cell.yard_no, 'has-overdue': cell.overdue_count > 0 }]"
                  @click="selectCell(cell.yard_no)"
                >
                  <span class="cell-name">{{ cell.yard_name || cell.yard_no }}</span>
                  <span class="cell-no">{{ cell.yard_no }}</span>
                  <span class="cell-count">{{ cell.storing_count }}</span>
                  <span class="cell-count-label">在库箱</span>
                  <span :class="['cell-overdue', { zero: cell.overdue_count === 0 }]">超期 {{ cell.overdue_count }}</span>
                  <span class="cell-missing">缺：{{ cell.missing.join('、') }}</span>
                </button>
              </div>
            </div>
          </div>

          <aside class="cell-detail">
            <div v-if="!selectedCell" class="detail-empty">
              点击左侧任意格子，查看这一区的箱号、贝位与对应堆存单；缺数据的格子会标出缺什么。
            </div>
            <template v-else>
              <header class="detail-head">
                <div>
                  <h3>{{ selectedCell.yard_name || selectedCell.yard_no }}</h3>
                  <p>{{ selectedCell.yard_no }}<span v-if="selectedCell.tier_label"> · {{ selectedCell.tier_label }}</span><span v-if="selectedCell.yard_status"> · {{ selectedCell.yard_status }}</span></p>
                </div>
                <button class="btn" type="button" @click="goListCell(selectedCell.yard_no)">在名单中查看</button>
              </header>

              <div class="detail-summary">
                <span>在库 <strong>{{ selectedCell.storing_count }}</strong></span>
                <span>超期 <strong :class="{ 'overdue-text': selectedCell.overdue_count > 0 }">{{ selectedCell.overdue_count }}</strong></span>
                <span>堆存单 {{ selectedCell.entry_count }}</span>
              </div>

              <ul v-if="selectedCell.missing.length" class="detail-missing">
                <li v-for="item in selectedCell.missing" :key="item">本格缺{{ item }}，其余信息仍可正常查看。</li>
              </ul>

              <table v-if="selectedCell.entries.length" class="data-table detail-table">
                <thead>
                  <tr>
                    <th>箱号</th>
                    <th>堆存单号</th>
                    <th>贝位号</th>
                    <th>状态</th>
                    <th>天数</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="entry in selectedCell.entries" :key="String(entry.id)" :class="{ overdue: entry._超期, inactive: !entry._在场 }">
                    <td>{{ entry.关联箱号 || '—' }}</td>
                    <td>{{ entry.堆存单号 || '—' }}</td>
                    <td>{{ entry.贝位号 || '—' }}</td>
                    <td>
                      {{ entry.status || entry.堆存状态 || '—' }}
                      <span v-if="entry._超期" class="tag overdue-tag">超期</span>
                    </td>
                    <td>{{ entry._堆存天数 == null ? '—' : entry._堆存天数 }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-else class="detail-empty-inner">这一区还没有堆存单，先在名单里登记或等待进场。</p>
            </template>
          </aside>
        </div>
      </template>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
interface StoreEntry {
  id: number
  status?: string
  堆存单号?: string
  关联箱号?: string
  箱区编号?: string
  贝位号?: string
  堆存状态?: string
  _堆存天数?: number | null
  _在场?: boolean
  _超期?: boolean
  [key: string]: unknown
}
interface PanoCell {
  yard_no: string
  yard_name: string
  tier: number | null
  tier_label: string
  yard_status: string
  registered: boolean
  storing_count: number
  overdue_count: number
  entry_count: number
  missing: string[]
  entries: StoreEntry[]
}
interface Panorama {
  as_of: string
  free_storage_days: number
  registry_available: boolean
  tiers: number[]
  totals: { cells: number; storing: number; overdue: number; entries: number }
  cells: PanoCell[]
}
interface ListFilters {
  keyword: string
  status: string
  yard_no: string
  in_yard: boolean
}

const ENDPOINT = '/api/yardstore'
const columns = ['堆存单号', '关联箱号', '箱区编号', '贝位号', '堆存开始', '堆存结束', '堆存天数', '堆存状态']
const actions = ['确认进场', '确认提离', '撤销堆存']
const statuses = ['待进场', '堆存中', '待提离', '已提离']
const pageSize = 20

// ---- 名单与全景共享的视图状态：切走再切回来仍保留原视野与选中格 ----
const view = ref<'list' | 'panorama'>('list')
const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const errorMessage = ref('')
const filters = reactive<ListFilters>({ keyword: '', status: '', yard_no: '', in_yard: false })
let listScrollY = 0

const panorama = ref<Panorama | null>(null)
const selectedYard = ref('')
const panoError = ref('')

const stats = computed(() => [
  { label: '在场堆存箱量', value: panorama.value?.totals.storing ?? 0 },
  { label: '超期箱量', value: panorama.value?.totals.overdue ?? 0 },
  { label: '堆存单据总数', value: panorama.value?.totals.entries ?? 0 },
])

// 全景格子按堆放层数归行；层数为 null（箱区档案缺失等）的格子进「层数未知」行
const cellsByTier = computed<Record<number, PanoCell[]>>(() => {
  const grouped: Record<number, PanoCell[]> = {}
  for (const cell of panorama.value?.cells ?? []) {
    if (cell.tier === null) continue
    grouped[cell.tier] ??= []
    grouped[cell.tier].push(cell)
  }
  return grouped
})

const unknownCells = computed<PanoCell[]>(
  () => (panorama.value?.cells ?? []).filter((cell) => cell.tier === null),
)

const selectedCell = computed<PanoCell | null>(
  () => panorama.value?.cells.find((cell) => cell.yard_no === selectedYard.value) ?? null,
)

async function switchView(next: 'list' | 'panorama') {
  if (view.value === next) return
  if (next === 'panorama') {
    listScrollY = window.scrollY
    await loadPanorama()
  }
  view.value = next
  if (next === 'list') {
    requestAnimationFrame(() => window.scrollTo({ top: listScrollY }))
  }
}

async function loadPanorama() {
  panoError.value = ''
  try {
    const response = await request(`${ENDPOINT}/panorama`)
    if (!response.ok) throw new Error('全景数据读取失败')
    panorama.value = (await response.json()) as Panorama
    // 已选中的格子若已不存在（例如编号被改），回退为不选中而不是清空整张全景
    if (selectedYard.value && !panorama.value.cells.some((cell) => cell.yard_no === selectedYard.value)) {
      selectedYard.value = panorama.value.cells[0]?.yard_no ?? ''
    } else if (!selectedYard.value) {
      selectedYard.value = panorama.value.cells[0]?.yard_no ?? ''
    }
  } catch (error) {
    panorama.value = null
    panoError.value = error instanceof Error ? error.message : '全景加载失败'
  }
}

async function selectCell(yardNo: string) {
  selectedYard.value = yardNo
  // 明细以全景格子内的 entries 直接呈现；缺档案格也照常可点
  const cell = panorama.value?.cells.find((item) => item.yard_no === yardNo)
  if (cell) return
  // 兜底：全景里找不到时再单独拉一次，避免面板空白
  try {
    const response = await request(`${ENDPOINT}/yard-detail?yard_no=${encodeURIComponent(yardNo)}`)
    if (!response.ok) throw new Error('箱区明细读取失败')
    const detail = (await response.json()) as PanoCell
    if (panorama.value) panorama.value.cells.push(detail)
  } catch {
    /* 单个格子失败不影响其它格子 */
  }
}

function goListCell(yardNo: string) {
  // 默认只看在场箱，保证名单合计与格子上的「在库箱」数完全对得上
  filters.yard_no = yardNo
  filters.in_yard = true
  page.value = 1
  void switchView('list').then(reload)
}

function goPanoramaCell(yardNo: string) {
  void switchView('panorama').then(() => {
    if (panorama.value?.cells.some((cell) => cell.yard_no === yardNo)) {
      selectedYard.value = yardNo
    }
  })
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  filters.yard_no = ''
  filters.in_yard = false
  page.value = 1
  void reload()
}

function changePage(next: number) {
  if (next < 1) return
  page.value = next
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '堆存单登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('堆存记录动作未生效，请稍后重试')
    }
    await reload()
    if (panorama.value) await loadPanorama()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆存记录操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.status) query.set('status', filters.status)
  if (filters.yard_no) query.set('yard_no', filters.yard_no)
  if (filters.in_yard) query.set('in_yard', 'true')
  query.set('page', String(page.value))
  query.set('size', String(pageSize))
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('堆存单列表读取失败')
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆存记录列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadPanorama()
})
</script>

<style scoped>
.view-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--border);
}
.tab-btn {
  border: 1px solid transparent;
  border-bottom: none;
  background: transparent;
  padding: 8px 18px;
  font-size: 14px;
  color: var(--muted);
  cursor: pointer;
  border-radius: 6px 6px 0 0;
}
.tab-btn.active {
  background: #fff;
  border-color: var(--border);
  color: var(--brand);
  font-weight: 600;
  position: relative;
  top: 1px;
}
.view-pane {
  background: transparent;
}
.filter-check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--muted);
  align-self: center;
}
.filter-check input {
  margin: 0;
}
.filter-item select {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 5px 8px;
  font-size: 13px;
}
.sync-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1e40af;
  border-radius: 6px;
  padding: 6px 12px;
  font-size: 12px;
  margin-bottom: 10px;
}
.pager {
  display: flex;
  gap: 6px;
}
.pager .btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.pano-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 10px;
}
.pano-totals strong {
  font-size: 14px;
  color: #1f2937;
}
.overdue-text {
  color: #b42318;
}
.pano-warn {
  margin: 0 0 10px;
  padding: 6px 10px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
  border-radius: 6px;
  font-size: 12px;
}
.pano-error {
  display: flex;
  gap: 12px;
  align-items: center;
  background: #fef3f2;
  border: 1px solid #fecdca;
  color: #b42318;
  border-radius: 8px;
  padding: 12px 16px;
  font-size: 13px;
}
.pano-body {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
.pano-grid-wrap {
  flex: 1;
  min-width: 0;
}
.tier-row {
  display: flex;
  gap: 10px;
  align-items: stretch;
  margin-bottom: 12px;
}
.tier-axis {
  width: 56px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #eef2f7;
  border: 1px dashed var(--border);
  border-radius: 8px;
  color: var(--muted);
  font-size: 12px;
  writing-mode: vertical-rl;
  letter-spacing: 2px;
}
.tier-axis.unknown {
  background: #fef3f2;
  color: #b42318;
}
.tier-cells {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
}
.yard-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.yard-cell:hover {
  border-color: var(--brand);
  box-shadow: 0 1px 6px rgba(31, 111, 235, 0.18);
}
.yard-cell.selected {
  border-color: var(--brand);
  border-width: 2px;
  padding: 9px 11px;
  box-shadow: 0 0 0 2px rgba(31, 111, 235, 0.15);
}
.yard-cell.has-overdue {
  border-left: 3px solid #d92d20;
}
.yard-cell.missing {
  background: #fafbfc;
  border-style: dashed;
}
.cell-name {
  font-size: 13px;
  font-weight: 600;
}
.cell-no {
  font-size: 11px;
  color: var(--muted);
}
.cell-count {
  font-size: 26px;
  line-height: 1.15;
  font-weight: 700;
  margin-top: 4px;
}
.cell-count-label {
  font-size: 11px;
  color: var(--muted);
}
.cell-overdue {
  font-size: 12px;
  color: #b42318;
  font-weight: 600;
  margin-top: 2px;
}
.cell-overdue.zero {
  color: var(--muted);
  font-weight: 400;
}
.cell-tier {
  font-size: 11px;
  color: var(--muted);
}
.cell-missing {
  font-size: 11px;
  color: #b54708;
  margin-top: 2px;
}
.cell-detail {
  width: 400px;
  flex-shrink: 0;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  position: sticky;
  top: 12px;
  max-height: calc(100vh - 140px);
  overflow-y: auto;
}
.detail-empty {
  color: var(--muted);
  font-size: 13px;
  padding: 24px 8px;
  line-height: 1.7;
}
.detail-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
}
.detail-head h3 {
  margin: 0;
  font-size: 16px;
}
.detail-head p {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--muted);
}
.detail-summary {
  display: flex;
  gap: 16px;
  margin: 12px 0;
  padding: 8px 10px;
  background: #f8fafc;
  border-radius: 6px;
  font-size: 13px;
}
.detail-summary strong {
  font-size: 16px;
  margin-left: 4px;
}
.detail-missing {
  margin: 0 0 10px;
  padding-left: 18px;
  color: #b54708;
  font-size: 12px;
  line-height: 1.7;
}
.detail-table th,
.detail-table td {
  font-size: 12px;
  padding: 6px 8px;
}
.detail-table tr.overdue td {
  background: #fef3f2;
}
.detail-table tr.inactive td {
  color: var(--muted);
}
.tag {
  display: inline-block;
  border-radius: 4px;
  padding: 0 6px;
  font-size: 11px;
  margin-left: 4px;
}
.overdue-tag {
  background: #fee4e2;
  color: #b42318;
}
.detail-empty-inner {
  color: var(--muted);
  font-size: 13px;
  text-align: center;
  padding: 20px 0;
}
@media (max-width: 1200px) {
  .pano-body {
    flex-direction: column;
  }
  .cell-detail {
    width: 100%;
    position: static;
    max-height: none;
  }
}
</style>
