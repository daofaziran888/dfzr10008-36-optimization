<template>
  <section class="page" data-module="product">
    <header class="page-head">
      <div>
        <h2>数据产品定义管理</h2>
        <p class="page-desc">维护数据产品的类型定义、数据来源与计算逻辑，为数据产品定义提供可验证的数据工程流程。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记数据产品</button>
        <button class="btn" type="button" @click="exportRows">导出数据产品定义清单</button>
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
            <template v-if="column === '认证有效期状态'">
              <span :class="['cert-state', row[column] === '有效' ? 'cert-valid' : 'cert-empty']">
                {{ row[column] ?? '—' }}
              </span>
            </template>
            <template v-else-if="column === '有效认证'">
              <span v-if="row[column]">{{ row[column].认证编号 }} / {{ row[column].有效期限 }}</span>
              <span v-else class="muted">暂无有效认证</span>
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
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无数据产品定义数据，可先登记数据产品</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据产品定义记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/product'
const columns = ["产品编号", "产品名称", "产品类型", "数据来源", "计算逻辑", "输出格式", "负责人", "产品状态", "认证有效期状态", "有效认证"]
const actions = ["发布产品", "下线产品", "删除产品"]
const statuses = ["草稿", "开发中", "已发布", "已下线"]
const stats = [{"label": "数据产品总数", "value": 0}, {"label": "已发布产品", "value": 0}, {"label": "已下线产品", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '数据产品登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      // 发布准入等后端校验失败原因直接展示，例如「暂无有效认证，发布准入不通过」
      throw new Error(payload.message || '数据产品定义动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据产品定义操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('数据产品列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据产品定义列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.cert-state {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 18px;
}

.cert-valid {
  background: #dcfce7;
  color: #166534;
}

.cert-empty {
  background: #e2e8f0;
  color: #475569;
}

.muted {
  color: #94a3b8;
}
</style>
