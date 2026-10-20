<script setup lang="ts">
import { computed } from 'vue'

import type { StreamEvent } from '../api/types'
import { buildSteps, formatElapsed } from '../lib/activity'

const props = defineProps<{ events: StreamEvent[] }>()
const steps = computed(() => buildSteps(props.events))
</script>

<template>
  <ol class="log" aria-live="polite">
    <li v-for="step in steps" :key="step.key" :class="['step', step.status]">
      <span class="icon" aria-hidden="true">
        <span v-if="step.status === 'running'" class="spinner" />
        <template v-else-if="step.status === 'done'">✓</template>
        <template v-else>!</template>
      </span>
      <div class="body">
        <div class="line">
          <span class="agent">{{ step.agent }}</span>
          <span class="title">{{ step.title }}</span>
          <span v-if="step.elapsedMs !== null" class="elapsed">{{ formatElapsed(step.elapsedMs) }}</span>
        </div>
        <ul v-if="step.details.length" class="details">
          <li v-for="(d, i) in step.details" :key="i" :class="{ warn: d.warn }">{{ d.text }}</li>
        </ul>
      </div>
    </li>
  </ol>
</template>

<style scoped>
.log { list-style: none; margin: 0; padding: 0; }
.step { display: flex; gap: 10px; padding: 7px 0; }
.step + .step { border-top: 1px dashed var(--border); }
.icon {
  flex: 0 0 20px; height: 20px; border-radius: 50%; display: inline-flex; align-items: center;
  justify-content: center; font-size: 12px; font-weight: 700; margin-top: 1px;
}
.done .icon { background: var(--ok-bg); color: var(--ok-text); }
.error .icon { background: var(--danger-bg); color: var(--danger-text); }
.spinner {
  width: 14px; height: 14px; border-radius: 50%; border: 2px solid var(--border);
  border-top-color: var(--accent); animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinner { animation-duration: 2.4s; } }
.body { flex: 1; min-width: 0; }
.line { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
.agent {
  font-size: 12px; font-weight: 600; padding: 1px 8px; border-radius: 999px;
  background: var(--surface-2); color: var(--text-muted); white-space: nowrap;
}
.running .title { color: var(--text); font-weight: 600; }
.done .title { color: var(--text-muted); }
.elapsed { margin-left: auto; font-size: 12px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.details { list-style: none; margin: 4px 0 0; padding: 0; font-size: 13.5px; }
.details li { padding: 2px 0 2px 12px; border-left: 2px solid var(--border); color: var(--text); }
.details li.warn { border-left-color: var(--warn-text); color: var(--warn-text); }
</style>
