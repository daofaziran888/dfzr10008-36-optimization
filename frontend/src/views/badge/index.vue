<template>
  <section class="page" data-module="badge">
    <header class="page-head">
      <div>
        <h2>数据产品认证管理</h2>
        <p class="page-desc">维护数据产品认证的类型分类、标准对标与有效期管理，为数据产品认证提供可验证的数据工程流程。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记认证记录</button>
        <button class="btn" type="button" @click="exportRows">导出数据产品认证清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

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
          <td v-for="column in columns" :key="column">
            <template v-if="column === '有效期状态'">
              <span :class="['badge-state', stateClass(row[column])]">{{ row[column] ?? '—' }}</span>
            </template>
            <template v-else-if="column === '生效认证'">
              <span v-if="row[column]">{{ row[column].审批人 }} / {{ row[column].有效期限 }}</span>
              <span v-else class="muted">—</span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
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
            <button class="link" type="button" @click="openHistory(row)">延期记录</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无数据产品认证数据，可先登记认证记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据产品认证记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 延期审批弹窗：收集审批人、新有效期限与审批时间，错误原因直接回显 -->
    <div v-if="extendOpen" class="modal-mask" @click.self="closeExtend">
      <div class="modal-card" role="dialog" aria-modal="true" aria-label="认证延期审批">
        <h3>认证延期 · {{ extendRow?.['认证编号'] }}</h3>
        <p class="modal-desc">
          当前有效期：{{ extendRow?.['有效期限'] }} ｜ 有效期状态：
          <span :class="['badge-state', stateClass(extendRow?.['有效期状态'])]">{{ extendRow?.['有效期状态'] }}</span>
        </p>
        <form class="modal-form" @submit.prevent="submitExtend">
          <label class="filter-item">
            <span>审批人</span>
            <input v-model="extendForm.审批人" placeholder="如：周宁" required />
          </label>
          <label class="filter-item">
            <span>新有效期限</span>
            <input v-model="extendForm.新有效期限" type="date" required />
          </label>
          <label class="filter-item">
            <span>原有效期限（并发延期时填写）</span>
            <input v-model="extendForm.原有效期限" type="date" />
          </label>
          <label class="filter-item">
            <span>审批时间</span>
            <input v-model="extendForm.审批时间" type="datetime-local" />
          </label>
          <p v-if="extendError" class="error-text">{{ extendError }}</p>
          <div class="modal-actions">
            <button class="btn" type="button" @click="closeExtend">取消</button>
            <button class="btn primary" type="submit" :disabled="submitting">
              {{ submitting ? '提交中…' : '提交延期审批' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- 延期记录弹窗：展示每条延期结论与裁决原因 -->
    <div v-if="historyOpen" class="modal-mask" @click.self="historyOpen = false">
      <div class="modal-card" role="dialog" aria-modal="true" aria-label="延期记录">
        <h3>延期记录 · {{ historyRow?.['认证编号'] }}</h3>
        <table v-if="historyRows.length" class="data-table">
          <thead>
            <tr>
              <th>审批人</th><th>审批时间</th><th>原有效期限</th><th>新有效期限</th>
              <th>结论</th><th>未采纳原因</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="record in historyRows" :key="record.id">
              <td>{{ record.审批人 }}</td>
              <td>{{ record.审批时间 }}</td>
              <td>{{ record.原有效期限 }}</td>
              <td>{{ record.新有效期限 }}</td>
              <td>
                <span :class="['badge-state', record.结论 === '生效中' ? 'state-valid' : 'state-expired']">
                  {{ record.结论 }}
                </span>
              </td>
              <td>{{ record.未采纳原因 ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty-state">暂无延期记录，该认证仍以原有效期为准</p>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="historyOpen = false">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/badge'
const columns = ["认证编号", "产品名称", "认证类型", "认证标准", "认证机构", "有效期限", "有效期状态", "生效认证", "认证状态"]
const actions = ["通过认证", "驳回认证", "延期认证"]
const stats = ref([
  { label: '认证记录总数', value: 0 },
  { label: '有效认证', value: 0 },
  { label: '已过期认证', value: 0 },
])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = ["认证编号", "产品名称", "认证类型"]

const extendOpen = ref(false)
const submitting = ref(false)
const extendError = ref('')
const extendRow = ref<Row | null>(null)
const extendForm = reactive({
  审批人: '',
  新有效期限: '',
  原有效期限: '',
  审批时间: '',
})

const historyOpen = ref(false)
const historyRow = ref<Row | null>(null)
const historyRows = ref<Row[]>([])

function stateClass(state: unknown): string {
  if (state === '有效') return 'state-valid'
  if (state === '已过期') return 'state-expired'
  return 'state-none'
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '认证记录登记入口尚未接入审批流'
}

function openExtend(row: Row) {
  extendRow.value = row
  extendError.value = ''
  extendForm.审批人 = ''
  extendForm.新有效期限 = ''
  extendForm.原有效期限 = ''
  extendForm.审批时间 = ''
  extendOpen.value = true
}

function closeExtend() {
  extendOpen.value = false
  extendRow.value = null
}

async function openHistory(row: Row) {
  historyRow.value = row
  historyRows.value = row['延期记录'] ?? []
  historyOpen.value = true
}

async function submitExtend() {
  if (!extendRow.value) return
  submitting.value = true
  extendError.value = ''
  const values: Record<string, string> = {
    审批人: extendForm.审批人.trim(),
    新有效期限: extendForm.新有效期限,
  }
  if (extendForm.原有效期限) values.原有效期限 = extendForm.原有效期限
  if (extendForm.审批时间) values.审批时间 = extendForm.审批时间.replace('T', ' ') + ':00'
  try {
    const response = await request(`${ENDPOINT}/${extendRow.value.id}/extend`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      // 过期边界、非法期限等失败原因由后端给出，直接展示给审批人
      extendError.value = payload.message || '认证延期未生效，请稍后重试'
      return
    }
    closeExtend()
    await reload()
  } catch (error) {
    extendError.value = error instanceof Error ? error.message : '认证延期请求失败，可重试'
  } finally {
    submitting.value = false
  }
}

async function runAction(action: string, row: Row) {
  if (action === '延期认证') {
    openExtend(row)
    return
  }
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '数据产品认证动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据产品认证操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('认证记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value[0].value = total.value
    stats.value[1].value = rows.value.filter((row: Row) => row['有效期状态'] === '有效').length
    stats.value[2].value = rows.value.filter((row: Row) => row['有效期状态'] === '已过期').length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据产品认证列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}

.modal-card {
  width: min(720px, 92vw);
  background: #fff;
  border-radius: 10px;
  padding: 20px 24px;
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.22);
}

.modal-desc {
  margin: 8px 0 16px;
  color: #475569;
  font-size: 13px;
}

.modal-form {
  display: grid;
  gap: 12px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 8px;
}

.badge-state {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 18px;
}

.state-valid {
  background: #dcfce7;
  color: #166534;
}

.state-expired {
  background: #fee2e2;
  color: #991b1b;
}

.state-none {
  background: #e2e8f0;
  color: #475569;
}

.muted {
  color: #94a3b8;
}
</style>
