<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { api } from '../api/client'
import type { EvaluationJob } from '../api/types'
import { delta, formatMetric, METRICS } from '../lib/admin'
import { formatDateTime } from '../lib/format'
import ErrorBanner from './ErrorBanner.vue'

const props = defineProps<{ enabled: boolean }>()
const jobs = ref<EvaluationJob[]>([])
const selectedId = ref<string | null>(null)
const error = ref<unknown>(null)
const starting = ref(false)
let poll: ReturnType<typeof setInterval> | undefined

const selected = computed(() => jobs.value.find((j) => j.id === selectedId.value) ?? jobs.value[0] ?? null)
const running = computed(() => jobs.value.some((j) => j.status === 'queued' || j.status === 'running'))

async function load() {
  try {
    jobs.value = await api.admin.evaluations()
  } catch (e) {
    error.value = e
  }
}

async function start(profiles: string[], limit?: number) {
  starting.value = true
  error.value = null
  try {
    const job = await api.admin.startEvaluation(profiles, limit)
    selectedId.value = job.id
    await load()
  } catch (e) {
    error.value = e
  } finally {
    starting.value = false
  }
}

onMounted(async () => {
  await load()
  poll = setInterval(() => { if (running.value) load() }, 3000)
})
onBeforeUnmount(() => clearInterval(poll))
</script>

<template>
  <section class="card">
    <div class="head">
      <h2>Before / After 평가</h2>
      <div class="actions">
        <button type="button" :disabled="!props.enabled || running || starting" @click="start(['baseline', 'improved'], 3)">빠른 점검 (3건)</button>
        <button type="button" class="primary" :disabled="!props.enabled || running || starting" @click="start(['baseline', 'improved'])">전체 평가 (10건)</button>
      </div>
    </div>
    <p class="muted small">
      평가 데이터셋(<span class="mono">4m-review-eval</span>)을 Baseline(개선 기능 전부 끔)과 Improved(전부 켬)로
      같은 입력에 실행해 LangSmith 실험으로 비교합니다. 실모델은 10건 기준 약 10~15분 걸립니다.
    </p>
    <ErrorBanner v-if="error" :error="error" />
    <p v-if="!props.enabled" class="banner warn">LangSmith 추적이 꺼져 있어 평가를 실행할 수 없습니다.</p>

    <div v-if="jobs.length" class="jobs">
      <button v-for="job in jobs.slice(0, 6)" :key="job.id" type="button"
        :class="['job', job.status, { active: selected?.id === job.id }]" @click="selectedId = job.id">
        <span class="mono">{{ job.id }}</span>
        <span>{{ job.status === 'running' || job.status === 'queued'
          ? `진행 ${job.progress.done}/${job.progress.total}` : job.status === 'completed' ? '완료' : job.status === 'interrupted' ? '중단됨' : '실패' }}</span>
        <span class="muted small">{{ formatDateTime(job.created_at) }} · {{ job.case_count }}건 · {{ job.llm_backend }}</span>
      </button>
    </div>

    <template v-if="selected">
      <div v-if="selected.status === 'running' || selected.status === 'queued'" class="progress" role="progressbar"
        :aria-valuenow="selected.progress.done" :aria-valuemax="selected.progress.total">
        <div :style="{ width: `${(selected.progress.done / Math.max(selected.progress.total, 1)) * 100}%` }" />
      </div>
      <p v-if="selected.error" class="banner danger">{{ selected.error }}</p>
      <div v-if="selected.experiments.length" class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>지표</th>
              <th v-for="ex in selected.experiments" :key="ex.profile">
                {{ ex.profile === 'baseline' ? 'Baseline (Before)' : 'Improved (After)' }}
                <a v-if="ex.url" :href="ex.url" target="_blank" rel="noopener" class="small">LangSmith ↗</a>
              </th>
              <th v-if="selected.experiments.length === 2">변화</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in METRICS" :key="m.key">
              <td>{{ m.label }}</td>
              <td v-for="ex in selected.experiments" :key="ex.profile" class="num">{{ formatMetric(ex.summary[m.key], m.kind) }}</td>
              <td v-if="selected.experiments.length === 2" class="num"
                :class="{ better: delta(selected, m.key).better === true, worse: delta(selected, m.key).better === false }">
                {{ delta(selected, m.key).text }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.head h2 { margin: 0; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
.small { font-size: 13px; margin: 8px 0; }
.jobs { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
.job { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; text-align: left; }
.job.active { border-color: var(--accent); }
.job.failed { border-color: var(--danger-text); }
.job.interrupted { border-color: var(--warn-text); }
.progress { height: 8px; background: var(--surface-2); border-radius: 999px; overflow: hidden; margin: 8px 0 12px; }
.progress div { height: 100%; background: var(--accent); transition: width 0.4s; }
.num { font-variant-numeric: tabular-nums; }
.better { color: var(--ok-text); font-weight: 600; }
.worse { color: var(--danger-text); font-weight: 600; }
th a { margin-left: 6px; font-weight: 400; }
</style>
