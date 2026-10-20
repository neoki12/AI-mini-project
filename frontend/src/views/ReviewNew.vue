<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api, ApiError } from '../api/client'
import { streamReview } from '../api/stream'
import type { Review, StreamEvent } from '../api/types'
import ActivityLog from '../components/ActivityLog.vue'
import ErrorBanner from '../components/ErrorBanner.vue'
import { EXAMPLE_REQUESTS } from '../lib/format'

const MAX_LENGTH = 2000
const router = useRouter()
const route = useRoute()
// 보완 재검토 모드: ?parent=rv-... — 원 검토에 보완 정보만 덧붙여 다시 검토한다
const parentId = computed(() => (typeof route.query.parent === 'string' ? route.query.parent : null))
const parent = ref<Review | null>(null)
watch(parentId, async (id) => {
  parent.value = null
  if (id) {
    try { parent.value = await api.getReview(id) } catch (e) { error.value = e }
  }
}, { immediate: true })
const message = ref('')
const pending = ref(false)
const elapsed = ref(0)
const error = ref<unknown>(null)
const events = ref<StreamEvent[]>([])
const draft = ref('')            // Writer Agent가 작성 중인 보고서 (토큰 스트리밍)
const draftAttempt = ref(0)
const outOfScope = ref<string | null>(null)   // 4M 변경 요청이 아니라 검토하지 않은 경우
let timer: ReturnType<typeof setInterval> | undefined
let controller: AbortController | undefined

function onEvent(e: StreamEvent) {
  if (e.type === 'AnswerToken') {
    if (e.attempt !== draftAttempt.value) {   // 검수 반려로 재작성하면 새로 시작
      draftAttempt.value = e.attempt ?? 0
      draft.value = ''
    }
    draft.value += e.delta ?? ''
    return
  }
  if (e.type === 'OutOfScope') {
    outOfScope.value = e.message ?? '4M 변경 요청이 아닌 것 같아 검토를 시작하지 않았어요.'
    return
  }
  if (e.type === 'ReviewSaved' && e.id) {
    router.push({ name: 'review-detail', params: { id: e.id } })
    return
  }
  if (e.type === 'Error') {
    error.value = new ApiError(502, e.code ?? 'agent_failed', e.message ?? '오류', e.request_id ?? null)
  }
  events.value.push(e)
}

async function submit() {
  const text = message.value.trim()
  if (!text || pending.value) return
  pending.value = true
  error.value = null
  outOfScope.value = null
  events.value = []
  draft.value = ''
  draftAttempt.value = 0
  elapsed.value = 0
  timer = setInterval(() => (elapsed.value += 1), 1000)
  controller = new AbortController()
  try {
    await streamReview(text, onEvent, controller.signal, parentId.value ?? undefined)
  } catch (e) {
    if ((e as Error).name !== 'AbortError') error.value = e
  } finally {
    pending.value = false
    clearInterval(timer)
  }
}

function cancel() {
  controller?.abort()
}

onBeforeUnmount(() => {
  clearInterval(timer)
  controller?.abort()
})
</script>

<template>
  <section class="card">
    <h1>{{ parentId ? '보완 정보로 다시 검토' : '4M 변경 검토 요청' }}</h1>
    <div v-if="parent" class="parent">
      <p class="muted small">원 검토 <RouterLink :to="{ name: 'review-detail', params: { id: parent.id } }">{{ parent.id }}</RouterLink></p>
      <p class="parent-request">{{ parent.request }}</p>
      <ul v-if="parent.warnings.length" class="parent-warnings">
        <li v-for="w in parent.warnings" :key="w">{{ w }}</li>
      </ul>
    </div>
    <p class="muted">
      작업자·설비·재료·공법 변경 내용을 적으면 관련 표준서와 현장 데이터를 조회해 필요한 검증 항목,
      변경 등급, 다음 공정 영향을 정리합니다. 최종 판단과 승인은 품질 담당자가 합니다.
    </p>

    <form @submit.prevent="submit">
      <label for="request" class="label">{{ parentId ? '보완 정보' : '변경 요청' }}</label>
      <textarea id="request" v-model="message" rows="5" :maxlength="MAX_LENGTH" :disabled="pending"
        :placeholder="parentId ? '예: 의장 공장 도어 트림 공정이에요'
          : '예: 차체 대시 패널 라인 용접 로봇(BD-RB-301)의 용접 전류 조건을 변경합니다.'" />
      <div class="row">
        <span class="muted small">{{ message.length }} / {{ MAX_LENGTH }}</span>
        <div class="actions">
          <button v-if="pending" type="button" @click="cancel">중단</button>
          <button type="submit" class="primary" :disabled="pending || !message.trim()">
            {{ pending ? `검토 중… ${elapsed}초` : '검토 요청' }}
          </button>
        </div>
      </div>
    </form>
    <ErrorBanner v-if="error" :error="error" />
    <div v-if="outOfScope" class="banner warn" role="alert">{{ outOfScope }}</div>
  </section>

  <section v-if="(events.length || pending) && !outOfScope" class="card">
    <div class="live-head">
      <h2>처리 과정</h2>
      <span class="muted small">{{ pending ? `${elapsed}초 경과` : '종료' }}</span>
    </div>
    <ActivityLog :events="events" />
    <div v-if="draft" class="draft">
      <p class="muted small">보고서 작성 중{{ draftAttempt > 1 ? ` (재작성 ${draftAttempt - 1}회차)` : '' }}</p>
      <pre>{{ draft }}</pre>
    </div>
  </section>

  <section v-if="!pending && !parentId && (!events.length || outOfScope)" class="card">
    <h2>예시 요청</h2>
    <ul class="examples">
      <li v-for="ex in EXAMPLE_REQUESTS" :key="ex">
        <button type="button" @click="message = ex">{{ ex }}</button>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.label { display: block; font-weight: 600; margin: 16px 0 6px; }
.parent { background: var(--surface-2); border-radius: var(--radius); padding: 12px 14px; margin-top: 12px; }
.parent-request { margin: 4px 0; font-weight: 600; }
.parent-warnings { margin: 6px 0 0; padding-left: 18px; color: var(--warn-text); font-size: 14px; }
.row { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; gap: 12px; }
.actions { display: flex; gap: 8px; }
.small { font-size: 13px; margin: 0; }
.live-head { display: flex; justify-content: space-between; align-items: baseline; }
.draft { margin-top: 12px; }
.draft pre {
  white-space: pre-wrap; word-break: break-word; font-family: inherit; margin: 6px 0 0;
  background: var(--surface-2); padding: 12px; border-radius: var(--radius); max-height: 260px; overflow: auto;
}
.examples { list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }
.examples button { width: 100%; text-align: left; background: var(--surface-2); }
</style>
