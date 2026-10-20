<script setup lang="ts">
import { computed, ref } from 'vue'

import type { Review } from '../api/types'
import {
  CHANGE_TYPE_LABELS, evidenceText, formatDateTime, groupChecklist, renderReport, statusLabel,
} from '../lib/format'
import ActivityLog from './ActivityLog.vue'
import GradeBadge from './GradeBadge.vue'
import StatusPill from './StatusPill.vue'

const props = defineProps<{ review: Review }>()

const groups = computed(() => groupChecklist(props.review.checklist))
const missing = computed(() => new Set(props.review.missing_items))
const showReport = ref(true)
const showLog = ref(false)
</script>

<template>
  <section class="card">
    <div class="head">
      <div>
        <p class="muted small">{{ formatDateTime(review.created_at) }} · <span class="mono">{{ review.id }}</span></p>
        <h1 class="request">{{ review.request }}</h1>
        <p v-if="review.parent_id" class="muted small">
          보완 재검토 · 원 검토 <RouterLink :to="{ name: 'review-detail', params: { id: review.parent_id } }">{{ review.parent_id }}</RouterLink>
        </p>
      </div>
      <div class="badges">
        <GradeBadge :grade="review.grading?.grade" :approver="review.grading?.approver" />
        <StatusPill :status="review.review_status" />
      </div>
    </div>

    <div v-if="review.review_status === '추가 확인 필요'" class="banner warn" role="alert">
      <strong>추가 확인 필요</strong>
      <ul>
        <li v-for="w in review.warnings" :key="w">{{ w }}</li>
        <li v-if="review.missing_items.length">보고서에 빠진 항목: {{ review.missing_items.join(', ') }}</li>
        <li v-for="issue in review.citation_issues ?? []" :key="issue">근거 인용 문제: {{ issue }}</li>
      </ul>
      <RouterLink class="followup" :to="{ name: 'review-new', query: { parent: review.id } }">
        보완해서 다시 검토 →
      </RouterLink>
    </div>

    <dl class="facts">
      <div><dt>공장</dt><dd>{{ review.shop ?? '미상' }}</dd></div>
      <div>
        <dt>변경 유형</dt>
        <dd>{{ review.change_types.map((t) => `${CHANGE_TYPE_LABELS[t] ?? t}(${t})`).join(', ') }}</dd>
      </div>
      <div><dt>초기유동관리</dt><dd>{{ review.grading?.initial_flow_period ?? '-' }}</dd></div>
      <div><dt>검증 항목</dt><dd>{{ review.checklist.length }}건</dd></div>
    </dl>
    <p v-if="review.grading" class="muted small">등급 근거: {{ review.grading.reason }}</p>
  </section>

  <section class="card">
    <h2>검증 항목 체크리스트</h2>
    <p v-if="!groups.length" class="muted">검증 항목이 없습니다.</p>
    <div v-for="group in groups" :key="group.key" class="group">
      <h3>{{ group.label }} <span class="muted small">{{ group.hint }} · {{ group.items.length }}건</span></h3>
      <div class="table-scroll">
        <table>
          <thead><tr><th class="col-id">ID</th><th>항목</th><th>근거</th></tr></thead>
          <tbody>
            <tr v-for="item in group.items" :key="item.id" :class="{ missing: missing.has(item.id) }">
              <td class="mono col-id">{{ item.id }}</td>
              <td>{{ item.name }}<span v-if="missing.has(item.id)" class="pill warn">보고서 누락</span></td>
              <td class="muted">{{ evidenceText(item) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>

  <div class="two-col">
    <section class="card">
      <h2>참조 문서</h2>
      <ul class="plain">
        <li v-for="d in review.documents" :key="d.doc_id">
          <span class="mono">{{ d.doc_id }} Rev.{{ d.rev }}</span> {{ d.title }}
          <span class="muted small">({{ d.doc_type === 'standard' ? '공정 표준' : '검사 기준' }})</span>
        </li>
      </ul>
    </section>
    <section class="card">
      <h2>현장 데이터</h2>
      <p v-if="!review.field_findings.length" class="muted">조회한 설비·라인이 없습니다.</p>
      <ul class="plain">
        <li v-for="f in review.field_findings" :key="`${f.kind}-${f.target}`">
          <span class="mono">{{ f.target }}</span>
          <span class="pill" :class="{ warn: f.abnormal || f.failed }">{{ statusLabel(f.status) }}</span>
          <span class="muted small">{{ f.note }}</span>
        </li>
      </ul>
    </section>
  </div>

  <section class="card">
    <div class="report-head">
      <h2>검토 보고서</h2>
      <button type="button" @click="showReport = !showReport">{{ showReport ? '접기' : '펼치기' }}</button>
    </div>
    <!-- renderReport는 HTML을 먼저 이스케이프하고 **굵게**만 변환한다 -->
    <pre v-if="showReport" class="report" v-html="renderReport(review.reply)" />
  </section>

  <section v-if="review.events.length" class="card">
    <div class="report-head">
      <h2>처리 과정 <span class="muted small">Agent별 수행 내역</span></h2>
      <button type="button" :aria-expanded="showLog" @click="showLog = !showLog">{{ showLog ? '접기' : '펼치기' }}</button>
    </div>
    <ActivityLog v-if="showLog" :events="review.events" />
  </section>

  <section class="card meta muted small">
    <span>백엔드 {{ review.metadata.llm_backend }}</span>
    <span>토큰 {{ review.metadata.tokens.toLocaleString() }}</span>
    <span>비용 ${{ review.metadata.cost_usd.toFixed(4) }}</span>
    <span>재작성 {{ Math.max(review.metadata.validation_attempts - 1, 0) }}회</span>
    <span>게이트 추가 {{ review.metadata.gate_added }}건</span>
    <span v-if="review.metadata.langsmith_run_id" class="mono">LangSmith {{ review.metadata.langsmith_run_id }}</span>
  </section>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; flex-wrap: wrap; }
.request { font-size: 18px; line-height: 1.45; white-space: pre-line; }
.badges { display: flex; gap: 8px; flex-wrap: wrap; }
.small { font-size: 13px; margin: 0; }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 16px 0 8px; }
.facts dt { font-size: 13px; color: var(--text-muted); }
.facts dd { margin: 0; font-weight: 600; }
.banner ul { margin: 6px 0 0; padding-left: 20px; }
.followup { display: inline-block; margin-top: 8px; font-weight: 600; }
.group + .group { margin-top: 20px; }
h3 { font-size: 15px; margin: 0 0 6px; }
.col-id { width: 120px; white-space: nowrap; }
tr.missing td { background: var(--warn-bg); }
td .pill { margin-left: 8px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }
.two-col .card + .card { margin-top: 0; }
.two-col + .card { margin-top: 16px; }
.plain { list-style: none; padding: 0; margin: 0; }
.plain li { padding: 6px 0; border-bottom: 1px solid var(--border); display: flex; gap: 8px; flex-wrap: wrap; align-items: baseline; }
.plain li:last-child { border-bottom: none; }
.report-head { display: flex; justify-content: space-between; align-items: center; }
.report { white-space: pre-wrap; word-break: break-word; font-family: inherit; margin: 0; background: var(--surface-2); padding: 14px; border-radius: var(--radius); }
.meta { display: flex; gap: 16px; flex-wrap: wrap; }
@media (max-width: 720px) { .two-col { grid-template-columns: 1fr; } }
</style>
