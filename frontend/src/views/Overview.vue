<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">汇总各业务模块的关键指标，先看总量再看异常。</p>
      </div>
    </header>
    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>
    <table class="data-table">
      <thead>
        <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in moduleRows" :key="row.name">
          <td>{{ row.name }}</td>
          <td>{{ row.created }}</td>
          <td>{{ row.pending }}</td>
          <td>{{ row.abnormal }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

const cards = ref<Overview['cards']>([])
const moduleRows = ref<Overview['modules']>([])

onMounted(async () => {
  try {
    const payload = await fetchJson<Overview>('/api/overview')
    cards.value = payload.cards
    moduleRows.value = payload.modules
  } catch {
    cards.value = [{"label": "业务模块", "value": 0}, {"label": "今日新增", "value": 0}]
    moduleRows.value = [{"name": "指标域管理", "created": 0, "pending": 0, "abnormal": 0}, {"name": "派生指标", "created": 0, "pending": 0, "abnormal": 0}, {"name": "API服务", "created": 0, "pending": 0, "abnormal": 0}, {"name": "查询优化", "created": 0, "pending": 0, "abnormal": 0}, {"name": "接口订阅", "created": 0, "pending": 0, "abnormal": 0}, {"name": "调用凭证", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据源连接", "created": 0, "pending": 0, "abnormal": 0}, {"name": "调用追踪", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据预览", "created": 0, "pending": 0, "abnormal": 0}, {"name": "接口版本", "created": 0, "pending": 0, "abnormal": 0}, {"name": "批量导出", "created": 0, "pending": 0, "abnormal": 0}, {"name": "指标重名解析", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据聚合", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据清洗", "created": 0, "pending": 0, "abnormal": 0}, {"name": "访问看板", "created": 0, "pending": 0, "abnormal": 0}, {"name": "SQL模板", "created": 0, "pending": 0, "abnormal": 0}, {"name": "结果缓存", "created": 0, "pending": 0, "abnormal": 0}, {"name": "查询审计", "created": 0, "pending": 0, "abnormal": 0}]
  }
})
</script>
