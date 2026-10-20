// E2E — 실제 백엔드(fake LLM)가 빌드된 화면을 서빙하는 상태에서 브라우저로 흐름을 확인한다.
// 실행 전 `npm run build`가 필요하다 (CI도 build 다음에 실행).
import { defineConfig, devices } from '@playwright/test'

const PORT = Number(process.env.E2E_PORT ?? 8199)
// 로컬은 설치된 Chrome을 쓴다 (Chromium 내려받기 생략). CI는 playwright install chromium.
const channel = process.env.CI ? undefined : (process.env.E2E_CHANNEL ?? 'chrome')

export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: 'retain-on-failure', channel },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Desktop Chrome'], viewport: { width: 375, height: 740 } },
      testMatch: /layout\.spec\.ts/ },
  ],
  webServer: {
    command: 'sh e2e/serve.sh',
    url: `http://127.0.0.1:${PORT}/api/v1/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
})
