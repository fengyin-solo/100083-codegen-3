<template>
  <section class="page" data-module="yardstore">
    <header class="page-head">
      <div>
        <h2>堆存记录管理</h2>
        <p class="page-desc">维护堆存单，围绕堆存单号、关联箱号、箱区编号、贝位号做登记、筛选与状态流转；切到堆存全景可按箱区格子核对在堆与超期。</p>
      </div>
      <div class="page-actions">
        <div class="view-switch">
          <button class="btn" :class="{ primary: view === 'list' }" type="button" @click="switchView('list')">箱区名单</button>
          <button class="btn" :class="{ primary: view === 'panorama' }" type="button" @click="switchView('panorama')">堆存全景</button>
        </div>
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

    <template v-if="view === 'list'">
      <form class="filter-bar" @submit.prevent="reload">
        <label v-for="field in filterFields" :key="field" class="filter-item">
          <span>{{ field }}</span>
          <input v-model="filters[field]" :placeholder="`按${field}检索`" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.id)">
            <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
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
            <td :colspan="columns.length + 1" class="empty-state">暂无堆存记录数据，可先登记堆存单</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ total }} 条堆存记录记录</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </template>

    <template v-else>
      <div v-if="blocks.length" class="panorama-grid">
        <button
          v-for="block in blocks"
          :key="block.箱区编号"
          type="button"
          class="panorama-cell"
          :class="{ selected: block.箱区编号 === selectedBlockCode, missing: isMissing(block) }"
          @click="selectBlock(block.箱区编号)"
        >
          <span class="cell-head">
            <strong>{{ block.箱区编号 }}</strong>
            <span class="cell-tier">{{ block.堆放层数 == null ? '层数未知' : `堆放 ${block.堆放层数} 层` }}</span>
          </span>
          <span class="cell-name">{{ block.箱区名称 || '—' }}</span>
          <span v-if="isMissing(block)" class="cell-missing">{{ block.缺失.join('；') }}</span>
          <span v-else class="cell-figures">
            <span class="figure"><em>{{ block.当前堆存量 }}</em>在堆</span>
            <span class="figure overdue" :class="{ quiet: block.超期箱数 === 0 }"><em>{{ block.超期箱数 }}</em>超期</span>
          </span>
        </button>
      </div>
      <p v-if="!blocks.length && !panoramaError" class="empty-state">暂无箱区数据，请先在堆场管理中登记箱区</p>

      <section v-if="selectedBlockCode" class="panorama-detail">
        <header class="detail-head">
          <h3>{{ selectedBlockCode }} · 箱号与堆存单</h3>
          <button class="link" type="button" @click="clearSelection">收起明细</button>
        </header>
        <p v-if="detailError" class="error-text">{{ detailError }}</p>
        <template v-else-if="detail">
          <p class="detail-summary">
            在堆 {{ detail.summary.当前堆存量 }} 箱 · 超期 {{ detail.summary.超期箱数 }} 箱 · 堆存单 {{ detail.summary.堆存单数 }} 张
          </p>
          <table v-if="detail.entries.length" class="data-table">
            <thead>
              <tr>
                <th>关联箱号</th>
                <th>堆存单号</th>
                <th>贝位号</th>
                <th>堆存开始</th>
                <th>堆存结束</th>
                <th>堆存天数</th>
                <th>堆存状态</th>
                <th>是否超期</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="entry in detail.entries" :key="String(entry.id)">
                <td>{{ entry.关联箱号 ?? '—' }}</td>
                <td>{{ entry.堆存单号 ?? '—' }}</td>
                <td>{{ entry.贝位号 ?? '—' }}</td>
                <td>{{ entry.堆存开始 ?? '—' }}</td>
                <td>{{ entry.堆存结束 ?? '—' }}</td>
                <td>{{ entry.堆存天数 ?? '—' }}</td>
                <td>{{ entry.堆存状态 ?? '—' }}</td>
                <td><span v-if="entry.超期" class="overdue-tag">超期</span><span v-else>—</span></td>
              </tr>
            </tbody>
          </table>
          <p v-else class="empty-state">这一箱区还没有堆存数据，可先在名单中登记堆存单</p>
        </template>
        <p v-else class="empty-state">明细加载中…</p>
      </section>

      <footer class="page-foot">
        <span v-if="totals">全景合计：{{ totals.箱区数 }} 个箱区 · 在堆 {{ totals.当前堆存量 }} 箱 · 超期 {{ totals.超期箱数 }} 箱 · 堆存单 {{ totals.堆存单数 }} 张（与名单合计一致）</span>
        <span v-if="panoramaError" class="error-text">{{ panoramaError }}</span>
      </footer>
    </template>
  </section>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null>

type PanoramaBlock = {
  箱区编号: string
  箱区名称: string
  堆放层数: number | null
  当前堆存量: number
  超期箱数: number
  堆存单数: number
  缺失: string[]
}

type PanoramaTotals = {
  箱区数: number
  当前堆存量: number
  超期箱数: number
  堆存单数: number
}

type BlockEntry = {
  id: number | null
  堆存单号: string | null
  关联箱号: string | null
  贝位号: string | null
  堆存开始: string | null
  堆存结束: string | null
  堆存天数: string | number | null
  堆存状态: string | null
  超期: boolean
}

type BlockDetail = {
  block: { 箱区编号: string; 箱区名称: string; 堆放层数: number | null }
  entries: BlockEntry[]
  summary: { 当前堆存量: number; 超期箱数: number; 堆存单数: number }
}

const ENDPOINT = '/api/yardstore'
const columns = ["堆存单号", "关联箱号", "箱区编号", "贝位号", "堆存开始", "堆存结束", "堆存天数", "堆存状态"]
const actions = ["确认进场", "确认提离", "撤销堆存"]
const statuses = ["待进场", "堆存中", "待提离", "已提离"]
const stats = [{"label": "堆存中箱量", "value": 0}, {"label": "今日进场箱量", "value": 0}, {"label": "今日提离箱量", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

// 名单与全景各自记住滚动位置，来回切换不丢视野
type View = 'list' | 'panorama'
const view = ref<View>('list')
const scrollMemory: Record<View, number> = { list: 0, panorama: 0 }

// 全景状态：选中格用箱区编号记住，切走再切回来仍然亮着
const blocks = ref<PanoramaBlock[]>([])
const totals = ref<PanoramaTotals | null>(null)
const panoramaError = ref('')
const selectedBlockCode = ref('')
const detail = ref<BlockDetail | null>(null)
const detailError = ref('')

function isMissing(block: PanoramaBlock): boolean {
  return block.缺失.includes('暂无堆存数据')
}

async function switchView(next: View) {
  if (next === view.value) {
    return
  }
  scrollMemory[view.value] = window.scrollY
  view.value = next
  if (next === 'panorama') {
    // 名单里可能刚做过进场/提离，切到全景时重取一遍，格子数字才和名单对得上
    await reloadPanorama()
  }
  await nextTick()
  window.scrollTo(0, scrollMemory[next])
}

async function reloadPanorama() {
  panoramaError.value = ''
  try {
    const payload = await fetchJson<{ blocks: PanoramaBlock[]; totals: PanoramaTotals }>(`${ENDPOINT}/panorama`)
    blocks.value = payload.blocks ?? []
    totals.value = payload.totals ?? null
    if (selectedBlockCode.value) {
      const stillThere = blocks.value.some((block) => block.箱区编号 === selectedBlockCode.value)
      if (stillThere) {
        await reloadDetail()
      } else {
        selectedBlockCode.value = ''
        detail.value = null
      }
    }
  } catch (error) {
    panoramaError.value = error instanceof Error ? error.message : '堆存全景读取失败'
  }
}

async function selectBlock(code: string) {
  if (selectedBlockCode.value === code) {
    clearSelection()
    return
  }
  selectedBlockCode.value = code
  detail.value = null
  await reloadDetail()
}

function clearSelection() {
  selectedBlockCode.value = ''
  detail.value = null
  detailError.value = ''
}

async function reloadDetail() {
  const code = selectedBlockCode.value
  if (!code) {
    return
  }
  detailError.value = ''
  try {
    detail.value = await fetchJson<BlockDetail>(`${ENDPOINT}/panorama/${encodeURIComponent(code)}`)
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '箱区明细读取失败'
  }
}

function resetFilters() {
  filters.value = {}
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
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆存记录操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('堆存单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆存记录列表读取失败'
  }
}

onMounted(reload)
</script>
