import { expect, test } from '@playwright/test'

// 화면마다 가로 스크롤이 생기지 않는지 (모바일 375px에서 특히)
for (const path of ['/#/', '/#/reviews', '/#/admin']) {
  test(`가로 넘침 없음: ${path}`, async ({ page }) => {
    await page.goto(path)
    await page.waitForLoadState('networkidle')
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow).toBeLessThanOrEqual(0)
  })
}
