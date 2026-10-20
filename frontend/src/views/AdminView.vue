<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api, ApiError, getAdminToken, setAdminToken } from '../api/client'
import type { Feedback, LangSmithStatus, RunDetail, RunSummary } from '../api/types'
import ErrorBanner from '../components/ErrorBanner.vue'
import EvaluationPanel from '../components/EvaluationPanel.vue'
import { formatDateTime } from '../lib/format'

const status = ref<LangSmithStatus | null>(null)
const runs = ref<RunSummary[]>([])
const feedback = ref<Feedback[]>([])
const detail = ref<RunDetail | null>(null)
const errorOnly = ref(false)
const error = ref<unknown>(null)
const needToken = ref(false)
const tokenInput = ref(getAdminToken() ?? '')
const loading = ref(false)

const maxStep = computed(() => Math.max(0.001, ...(detail.value?.steps ?? []).map((s) => s.latency_s ?? 0)))

function handle(e: unknown) {
  if (e instanceof ApiError && e.status === 401) needToken.value = true
  else error.value = e
}

async function loadRuns() {
  if (!status.value?.enabled) return
  try {
    runs.value = await api.admin.runs(20, errorOnly.value)
  } catch (e) {
    handle(e)
  }
}

async function load() {
  loading.value = true
  error.value = null
  needToken.value = false
  try {
    status.value = await api.admin.langsmith()
    feedback.value = await api.admin.feedback()
    await loadRuns()
  } catch (e) {
    handle(e)
  } finally {
    loading.value = false
  }
}

async function openRun(id: string) {
  try {
    detail.value = await api.admin.run(id)
  } catch (e) {
    handle(e)
  }
}

function saveToken() {
  setAdminToken(tokenInput.value.trim() || null)
  load()
}

onMounted(load)
</script>

<template>
  <section v-if="needToken" class="card">
    <h1>관리자 인증</h1>
    <p class="muted">이 서버는 관리자 토큰(ADMIN_TOKEN)이 설정돼 있습니다.</p>
    <form class="token" @submit.prevent="saveToken">
      <input v-model="tokenInput" type="password" autocomplete="off" placeholder="관리자 토큰" aria-label="관리자 토큰" />
      <button type="submit" class="primary">확인</button>
    </form>
  </section>

  <template v-else>
    <section class="card">
      <div class="head">
        <h1>관리자</h1>
        <button type="button" :disabled="loading" @click="load">새로고침</button>
      </div>
      <ErrorBanner v-if="error" :error="error" />
      <dl v-if="status" class="facts">
        <div><dt>LangSmith 추적</dt><dd :class="status.enabled && status.reachable ? 'ok' : 'bad'">
          {{ !status.enabled ? '꺼짐' : status.reachable ? '연결됨' : '연결 실패' }}</dd></div>
        <div><dt>프로젝트</dt><dd>
          <a v-if="status.project_url" :href="status.project_url" target="_blank" rel="noopener">{{ status.project }} ↗</a>
          <template v-else>{{ status.project }}</template></dd></div>
        <div><dt>관리자 인증</dt><dd :class="status.admin_auth ? 'ok' : 'warn'">
          {{ status.admin_auth ? '토큰 사용' : '꺼짐 (개발 모드)' }}</dd></div>
      </dl>
      <p v-if="status?.error" class="banner warn">{{ status.error }}</p>
    </section>

    <EvaluationPanel :enabled="!!status?.enabled && !!status?.reachable" />

    <section class="card">
      <div class="head">
        <h2>최근 실행</h2>
        <label class="small"><input v-model="errorOnly" type="checkbox" @change="loadRuns" /> 오류만</label>
      </div>
      <p v-if="!status?.enabled" class="muted">LangSmith 추적이 꺼져 있습니다.</p>
      <div v-else class="table-scroll">
        <table>
          <thead><tr><th>시각</th><th>이름</th><th>상태</th><th>소요</th><th>토큰</th><th>사용자 평가</th><th></th></tr></thead>
          <tbody>
            <tr v-for="r in runs" :key="r.id" :class="{ active: detail?.id === r.id }">
              <td class="nowrap">{{ r.start_time ? formatDateTime(r.start_time) : '-' }}</td>
              <td>{{ r.name }} <span v-if="r.tags.some((t) => t.startsWith('profile:baseline'))" class="pill">baseline</span></td>
              <td><span class="pill" :class="r.status === 'success' ? 'ok' : 'warn'">{{ r.status }}</span></td>
              <td class="num">{{ r.latency_s ?? '-' }}초</td>
              <td class="num">{{ r.total_tokens.toLocaleString() }}</td>
              <td>
                <template v-if="r.feedback.user_rating">
                  👍 {{ Math.round((r.feedback.user_rating.avg ?? 0) * 100) }}% ({{ r.feedback.user_rating.n }})
                </template>
              </td>
              <td class="nowrap">
                <button type="button" @click="openRun(r.id)">단계별</button>
                <a v-if="r.url" :href="r.url" target="_blank" rel="noopener" class="ls">LangSmith ↗</a>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="detail" class="card">
      <div class="head">
        <h2>실행 상세 <span class="mono small">{{ detail.id }}</span></h2>
        <button type="button" @click="detail = null">닫기</button>
      </div>
      <p class="muted">{{ detail.inputs_preview }}</p>
      <div class="table-scroll">
        <table>
          <thead><tr><th>Agent(노드)</th><th>소요</th><th></th><th>LLM</th><th>MCP</th><th>토큰</th></tr></thead>
          <tbody>
            <tr v-for="(s, i) in detail.steps" :key="i">
              <td class="mono">{{ s.name }}</td>
              <td class="num">{{ s.latency_s ?? '-' }}초</td>
              <td class="bar-cell"><div class="bar" :style="{ width: `${((s.latency_s ?? 0) / maxStep) * 100}%` }" /></td>
              <td class="num">{{ s.llm_calls }}</td>
              <td class="num">{{ s.tool_calls }}</td>
              <td class="num">{{ s.tokens.toLocaleString() }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="card">
      <h2>사용자 피드백</h2>
      <p v-if="!feedback.length" class="muted">아직 피드백이 없습니다.</p>
      <ul class="plain">
        <li v-for="f in feedback" :key="f.id">
          <span>{{ f.score ? '👍' : '👎' }}</span>
          <RouterLink :to="{ name: 'review-detail', params: { id: f.review_id } }">{{ f.request ?? f.review_id }}</RouterLink>
          <span v-if="f.comment" class="comment">“{{ f.comment }}”</span>
          <span class="muted small">{{ formatDateTime(f.created_at) }}</span>
        </li>
      </ul>
    </section>
  </template>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.head h1, .head h2 { margin: 0; }
.small { font-size: 13px; }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 16px 0 0; }
.facts dt { font-size: 13px; color: var(--text-muted); }
.facts dd { margin: 0; font-weight: 600; }
.ok { color: var(--ok-text); }
.warn { color: var(--warn-text); }
.bad { color: var(--danger-text); }
.token { display: flex; gap: 8px; }
.token input { flex: 1; font: inherit; padding: 8px 12px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); color: var(--text); }
.nowrap { white-space: nowrap; }
.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
tr.active td { background: var(--surface-2); }
.ls { margin-left: 8px; font-size: 13px; }
.bar-cell { width: 35%; }
.bar { height: 10px; border-radius: 4px; background: var(--accent); opacity: 0.75; min-width: 2px; }
.plain { list-style: none; padding: 0; margin: 0; }
.plain li { display: flex; gap: 10px; flex-wrap: wrap; align-items: baseline; padding: 8px 0; border-top: 1px solid var(--border); }
.comment { color: var(--text-muted); }
</style>
