<script setup lang="ts">
import type { Grade } from '../api/types'

defineProps<{ grade: Grade | null | undefined; approver?: string }>()
</script>

<template>
  <span v-if="grade" class="grade" :class="`grade-${grade.toLowerCase()}`" :title="approver">
    {{ grade }}등급<template v-if="approver"> · {{ approver }}</template>
  </span>
  <span v-else class="pill">등급 없음</span>
</template>

<style scoped>
.grade {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
  border: 1.5px solid currentColor;
}
.grade-a { color: var(--grade-a); }
.grade-b { color: var(--grade-b); }
.grade-c { color: var(--grade-c); }
</style>
