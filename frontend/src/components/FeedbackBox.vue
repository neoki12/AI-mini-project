<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api } from '../api/client'
import type { Feedback } from '../api/types'
import ErrorBanner from './ErrorBanner.vue'

const props = defineProps<{ reviewId: string }>()
const existing = ref<Feedback[]>([])
const score = ref<0 | 1 | null>(null)
const comment = ref('')
const sending = ref(false)
const error = ref<unknown>(null)

onMounted(async () => {
  try {
    existing.value = await api.listReviewFeedback(props.reviewId)
  } catch {
    existing.value = []
  }
})

async function submit() {
  if (score.value === null || sending.value) return
  sending.value = true
  error.value = null
  try {
    const fb = await api.addFeedback(props.reviewId, score.value, comment.value.trim())
    existing.value = [fb, ...existing.value]
    score.value = null
    comment.value = ''
  } catch (e) {
    error.value = e
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <section class="card">
    <h2>이 검토가 도움이 됐나요?</h2>
    <p class="muted small">평가는 LangSmith 실행 기록에 함께 남아 관리자 화면에서 품질을 추적하는 데 쓰입니다.</p>
    <div class="choices" role="radiogroup" aria-label="검토 평가">
      <button type="button" :class="{ selected: score === 1 }" :aria-pressed="score === 1" @click="score = 1">👍 도움이 됨</button>
      <button type="button" :class="{ selected: score === 0 }" :aria-pressed="score === 0" @click="score = 0">👎 아쉬움</button>
    </div>
    <template v-if="score !== null">
      <textarea v-model="comment" rows="2" maxlength="1000"
        :placeholder="score === 0 ? '빠졌거나 잘못된 항목이 있었다면 알려 주세요 (선택)' : '의견 (선택)'" />
      <div class="row">
        <button type="button" class="primary" :disabled="sending" @click="submit">
          {{ sending ? '보내는 중…' : '평가 보내기' }}
        </button>
      </div>
    </template>
    <ErrorBanner v-if="error" :error="error" />
    <ul v-if="existing.length" class="history">
      <li v-for="fb in existing" :key="fb.id">
        <span>{{ fb.score ? '👍' : '👎' }}</span>
        <span>{{ fb.comment || '(의견 없음)' }}</span>
        <span class="muted small">{{ fb.langsmith_feedback_id ? 'LangSmith 기록됨' : '로컬 저장' }}</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.small { font-size: 13px; margin: 0 0 10px; }
.choices { display: flex; gap: 8px; margin-bottom: 10px; }
.choices button.selected { border-color: var(--accent); color: var(--accent); font-weight: 600; }
.row { display: flex; justify-content: flex-end; margin-top: 8px; }
.history { list-style: none; padding: 0; margin: 12px 0 0; }
.history li { display: flex; gap: 10px; align-items: baseline; padding: 6px 0; border-top: 1px solid var(--border); }
</style>
