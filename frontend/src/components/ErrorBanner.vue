<script setup lang="ts">
import { computed } from 'vue'

import { ApiError } from '../api/client'

const props = defineProps<{ error: unknown }>()

const message = computed(() => {
  if (props.error instanceof ApiError) {
    if (props.error.code === 'agent_failed') {
      return 'Agent 실행 중 외부 의존성(MCP·LLM) 오류가 발생했습니다. Ollama나 API 키 상태를 확인하세요.'
    }
    return props.error.message
  }
  return props.error instanceof Error ? props.error.message : String(props.error)
})
const requestId = computed(() => (props.error instanceof ApiError ? props.error.requestId : null))
</script>

<template>
  <div class="banner danger" role="alert">
    {{ message }}
    <span v-if="requestId" class="mono"> (요청 ID {{ requestId }})</span>
  </div>
</template>
