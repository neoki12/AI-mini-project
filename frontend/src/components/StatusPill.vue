<script setup lang="ts">
import type { ReviewStatus } from '../api/types'

defineProps<{ status: ReviewStatus | null | undefined }>()
</script>

<template>
  <span v-if="status" class="pill" :class="status === '검토 완료' ? 'ok' : 'warn'">{{ status }}</span>
</template>
