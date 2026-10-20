<script setup lang="ts">
import { ref, watch } from 'vue'

import { api } from '../api/client'
import type { Review } from '../api/types'
import ErrorBanner from '../components/ErrorBanner.vue'
import FeedbackBox from '../components/FeedbackBox.vue'
import ReviewResult from '../components/ReviewResult.vue'

const props = defineProps<{ id: string }>()
const review = ref<Review | null>(null)
const error = ref<unknown>(null)
const loading = ref(false)

async function load(id: string) {
  loading.value = true
  error.value = null
  try {
    review.value = await api.getReview(id)
  } catch (e) {
    review.value = null
    error.value = e
  } finally {
    loading.value = false
  }
}

watch(() => props.id, load, { immediate: true })
</script>

<template>
  <p class="nav"><RouterLink to="/reviews">← 검토 이력</RouterLink></p>
  <p v-if="loading" class="muted">불러오는 중…</p>
  <ErrorBanner v-else-if="error" :error="error" />
  <template v-else-if="review">
    <ReviewResult :review="review" />
    <FeedbackBox :key="review.id" :review-id="review.id" />
  </template>
</template>

<style scoped>
.nav { margin: 0 0 12px; }
</style>
