import { expect, test } from '@playwright/test'

const REQUEST = '차체 대시 패널 라인 용접 로봇(BD-RB-301, BD-RB-302)의 용접 전류 조건을 변경합니다.'

test('검토 요청 → 처리 과정이 보이고 → 결과 상세로 이동한다', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('변경 요청').fill(REQUEST)
  await page.getByRole('button', { name: '검토 요청' }).click()

  await expect(page.getByRole('heading', { name: '처리 과정' })).toBeVisible()
  await page.waitForURL(/#\/reviews\/rv-/)
  await expect(page.getByRole('heading', { name: REQUEST })).toBeVisible()
  await expect(page.getByRole('heading', { name: '검증 항목 체크리스트' })).toBeVisible()
  await expect(page.getByText('[COM-01]').first()).toBeVisible()

  await page.getByRole('link', { name: '검토 이력', exact: true }).click()
  await expect(page.getByText(REQUEST)).toBeVisible()
})

test('4M 변경 요청이 아니면 검토하지 않고 안내한다', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('변경 요청').fill('오늘 점심 뭐 먹지?')
  await page.getByRole('button', { name: '검토 요청' }).click()

  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page).toHaveURL(/#\/$/)
  await expect(page.getByRole('heading', { name: '처리 과정' })).toHaveCount(0)
})

test('공장 미상 → 보완 정보로 다시 검토해 해결한다', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('변경 요청').fill('신입 작업자 2명을 야간조에 투입하려고 합니다')
  await page.getByRole('button', { name: '검토 요청' }).click()
  await page.waitForURL(/#\/reviews\/rv-/)
  const parentUrl = page.url()
  await expect(page.getByText('추가 확인 필요').first()).toBeVisible()

  await page.getByRole('link', { name: /보완해서 다시 검토/ }).click()
  await expect(page.getByRole('heading', { name: '보완 정보로 다시 검토' })).toBeVisible()
  await page.getByLabel('보완 정보').fill('의장 공장 도어 트림 공정이에요')
  await page.getByRole('button', { name: '검토 요청' }).click()

  await page.waitForURL((url) => /#\/reviews\/rv-/.test(url.href) && url.href !== parentUrl)
  await expect(page.getByText(/보완 재검토 · 원 검토/)).toBeVisible()
  await expect(page.getByText('검토 완료').first()).toBeVisible()
})
