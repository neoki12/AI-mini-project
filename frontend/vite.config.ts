import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 개발 서버(5173)는 /api 요청을 FastAPI 백엔드(8100)로 프록시한다 — 같은 출처라 CORS 불필요.
// 빌드 결과(dist/)는 FastAPI가 / 경로에서 그대로 서빙한다 (app/main.py).
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8100', changeOrigin: true } },
  },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts'] },   // e2e/는 Playwright가 실행
})
