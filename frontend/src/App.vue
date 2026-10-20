<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api } from './api/client'
import type { Health } from './api/types'

const health = ref<Health | null>(null)
const offline = ref(false)
const degradedServers = computed(() => Object.entries(health.value?.mcp_servers ?? {})
  .filter(([, s]) => !s.ok).map(([name]) => `MCP 서버 ${name} 응답 없음`).join(', '))

onMounted(async () => {
  try {
    health.value = await api.health()
  } catch {
    offline.value = true
  }
})
</script>

<template>
  <header class="topbar">
    <div class="container bar">
      <RouterLink to="/" class="brand">4M 변경 영향 검토</RouterLink>
      <nav>
        <RouterLink to="/" exact-active-class="active">새 검토</RouterLink>
        <RouterLink to="/reviews" active-class="active">검토 이력</RouterLink>
        <RouterLink to="/admin" active-class="active">관리자</RouterLink>
      </nav>
      <span class="backend muted" :class="{ offline }">
        <template v-if="health">
          <span v-if="health.status === 'degraded'" class="degraded" :title="degradedServers">⚠️ 일부 기능 장애 · </span>
          {{ health.llm_backend }} · {{ health.fast_llm }} / {{ health.quality_llm }}
        </template>
        <template v-else-if="offline">백엔드 연결 안 됨</template>
      </span>
    </div>
  </header>
  <main class="container">
    <RouterView />
  </main>
  <footer class="container muted footnote">
    교육용 가상 데이터(가상의 완성차 공장)를 사용합니다. 검토 결과는 참고용이며 최종 판단은 품질 담당자가 합니다.
  </footer>
</template>

<style scoped>
.topbar { background: var(--surface); border-bottom: 1px solid var(--border); }
.bar { display: flex; align-items: center; gap: 24px; padding-top: 12px; padding-bottom: 12px; flex-wrap: wrap; }
.brand { font-weight: 700; color: var(--text); }
nav { display: flex; gap: 16px; }
nav a { color: var(--text-muted); }
nav a.active { color: var(--accent); font-weight: 600; }
.backend { margin-left: auto; font-size: 13px; }
.backend.offline, .degraded { color: var(--danger-text); }
.footnote { font-size: 13px; padding-top: 0; }
</style>
