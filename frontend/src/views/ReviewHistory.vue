<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { api } from '../api/client'
import type { ReviewList } from '../api/types'
import ErrorBanner from '../components/ErrorBanner.vue'
import GradeBadge from '../components/GradeBadge.vue'
import StatusPill from '../components/StatusPill.vue'
import { CHANGE_TYPE_LABELS, formatDateTime } from '../lib/format'

const PAGE_SIZE = 20
const page = ref(0)
const data = ref<ReviewList | null>(null)
const error = ref<unknown>(null)
const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil((data.value?.total ?? 0) / PAGE_SIZE)))

async function load() {
  loading.value = true
  error.value = null
  try {
    data.value = await api.listReviews(PAGE_SIZE, page.value * PAGE_SIZE)
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}

watch(page, load, { immediate: true })
</script>

<template>
  <section class="card">
    <div class="head">
      <h1>검토 이력</h1>
      <span v-if="data" class="muted">총 {{ data.total }}건</span>
    </div>
    <ErrorBanner v-if="error" :error="error" />
    <p v-else-if="loading && !data" class="muted">불러오는 중…</p>
    <p v-else-if="data && !data.items.length" class="muted">
      아직 검토 이력이 없습니다. <RouterLink to="/">새 검토를 요청</RouterLink>해 보세요.
    </p>
    <div v-else-if="data" class="table-scroll">
      <table>
        <thead>
          <tr><th>요청</th><th>공장</th><th>유형</th><th>등급</th><th>상태</th><th>일시</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in data.items" :key="item.id">
            <td class="request">
              <RouterLink :to="{ name: 'review-detail', params: { id: item.id } }">{{ item.request }}</RouterLink>
            </td>
            <td>{{ item.shop ?? '-' }}</td>
            <td>{{ item.change_types.map((t) => CHANGE_TYPE_LABELS[t] ?? t).join(', ') }}</td>
            <td><GradeBadge :grade="item.grading?.grade" /></td>
            <td><StatusPill :status="item.review_status" /></td>
            <td class="muted nowrap">{{ formatDateTime(item.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="data && pageCount > 1" class="pager">
      <button type="button" :disabled="page === 0" @click="page -= 1">이전</button>
      <span class="muted">{{ page + 1 }} / {{ pageCount }}</span>
      <button type="button" :disabled="page + 1 >= pageCount" @click="page += 1">다음</button>
    </div>
  </section>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 12px; }
.request { max-width: 420px; }
.nowrap { white-space: nowrap; }
.pager { display: flex; gap: 12px; justify-content: center; align-items: center; margin-top: 16px; }
</style>
