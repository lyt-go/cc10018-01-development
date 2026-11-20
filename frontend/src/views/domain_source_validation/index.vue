<template>
  <section class="page" data-module="domain_source_validation">
    <header class="page-head">
      <div>
        <h2>域源映射校验</h2>
        <p class="page-desc">维护指标域到数据源表、取数连接的校验证据：证据绑定连接编号，连接断开即失效，同库名连接不能替代。</p>
      </div>
      <div class="page-actions">
        <button class="btn" data-testid="reload" type="button" @click="reload">刷新证据列表</button>
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
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.校验状态)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              class="link"
              type="button"
              :data-testid="`action-${row.id}-revalidate`"
              @click="revalidate(row)"
            >
              重新校验
            </button>
            <button
              class="link"
              type="button"
              :data-testid="`action-${row.id}-check`"
              @click="checkAuthorization(row)"
            >
              取数检查
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无域源校验证据，可先在指标域管理登记或开启域</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条域源校验证据</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/domain_source_validation'
const columns = ["校验编号", "域编号", "数据源表", "连接编号", "校验状态", "失效原因", "校验时间", "校验来源"]
const metricNames = ["证据总数", "有效证据", "已失效证据"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(1, 2)
const stats = computed(() => [
  { label: metricNames[0], value: total.value },
  { label: metricNames[1], value: rows.value.filter((row) => row.校验状态 === '有效').length },
  { label: metricNames[2], value: rows.value.filter((row) => row.校验状态 === '已失效').length },
])

function resetFilters() {
  filters.value = {}
  void reload()
}

async function revalidate(row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.域编号}/revalidate`, { method: 'POST' })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '重新校验未通过')
    noticeMessage.value = payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重新校验失败'
  }
}

async function checkAuthorization(row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.域编号}/check`)
    const payload = await response.json()
    noticeMessage.value = payload.ok
      ? `域 ${row.域编号} 取数授权有效，实际取数连接 ${payload.连接编号}`
      : `域 ${row.域编号} 取数未授权：${payload.reason}`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '取数检查失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (filters.value['域编号']) params.set('domain_code', filters.value['域编号'])
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('域源校验证据列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '域源校验证据列表读取失败'
  }
}

onMounted(reload)
</script>
