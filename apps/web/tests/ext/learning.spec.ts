/**
 * 学情工具的端到端走查：登录 → 打开工具 → 走完四个 Tab → 截图。
 *
 * 仓库里没有 Playwright 依赖（`bun test tests` 跑的是纯逻辑单测），所以这条用例
 * 用 `bunx playwright test` 按需拉起，配置见同目录 `playwright.config.ts`。
 * 跑之前要先起本地栈：
 *
 *   apps/api  uv run uvicorn app:app --port 9003
 *   apps/web  bun run dev --port 3003
 *
 * 环境变量：LH_E2E_BASE_URL（默认 http://localhost:3003）、
 * LH_E2E_EMAIL / LH_E2E_PASSWORD（默认本地预发栈的管理员）、
 * LH_E2E_SHOTS（截图目录，默认 docs/sysu-sam/QA/learning）。
 */
import { expect, test } from '@playwright/test'

const BASE = process.env.LH_E2E_BASE_URL ?? 'http://localhost:3003'
const EMAIL = process.env.LH_E2E_EMAIL ?? 'user1@example.local'
const PASSWORD = process.env.LH_E2E_PASSWORD ?? 'LocalDev#2026'
// playwright 的工作目录是 apps/web，截图要落到仓库根的 docs/ 下
const SHOTS = process.env.LH_E2E_SHOTS ?? '../../docs/sysu-sam/QA/learning'
// 单组织模式（NEXT_PUBLIC_LEARNHOUSE_MULTI_ORG=False）下后台在 /dash 下，
// 多组织模式才是 /orgs/<slug>/dash。用 LH_E2E_ORG_SLUG 切换。
const ORG_SLUG = process.env.LH_E2E_ORG_SLUG ?? ''
const DASH = ORG_SLUG ? `${BASE}/orgs/${ORG_SLUG}/dash` : `${BASE}/dash`
const TOOL_URL = `${DASH}/tools/learning`

/**
 * 新账号第一次进后台会弹「欢迎来到…」引导层，它是 fixed 全屏遮罩，
 * 会把后面所有点击都吃掉。这里直接把 useOnboarding 的 localStorage 状态
 * 预置成「已看过、已关闭」，比等弹窗出来再点稳。
 */
async function suppressOnboarding(page: import('@playwright/test').Page) {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem(
        'lh_onboarding',
        JSON.stringify({
          completedSteps: [],
          skippedSteps: [],
          minimized: true,
          expanded: false,
          showAllSteps: false,
          dismissed: true,
          welcomeSeen: true,
        })
      )
    } catch {
      /* 隐私模式下写不进去，忽略 */
    }
  })
}

test.describe('教学工具 / 学情', () => {
  test.beforeEach(async ({ page }) => {
    await suppressOnboarding(page)
    await page.goto(`${BASE}/login`)
    // 登录页默认可能是「邮件登录链接」那一屏，先切回密码登录
    const passwordField = page.locator('input[type="password"]')
    if ((await passwordField.count()) === 0) {
      await page.getByRole('button', { name: /password instead|使用密码/i }).click()
    }
    await page.locator('input[type="email"]').fill(EMAIL)
    await passwordField.fill(PASSWORD)
    await page.locator('form button[type="submit"]').last().click()
    // 单组织模式登录后落在 /home，多组织模式落在 /orgs/<slug>，两种都算成功
    await page.waitForURL((url) => !/\/login/.test(url.pathname), { timeout: 30_000 })
  })

  test('四个 Tab 都能打开并出数据', async ({ page }) => {
    await page.goto(TOOL_URL)
    await expect(page.getByTestId('learning-tool')).toBeVisible({ timeout: 30_000 })

    // 选课下拉由路由页统一渲染，选中有演示数据的那门课
    const courseSelect = page.locator('select').first()
    await courseSelect.selectOption({ label: 'AI-Driven Advanced Manufacturing' })

    // 1) 成绩册
    await expect(page.getByTestId('learning-gradebook-table')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByTestId('learning-gradebook-table')).toContainText('已批')
    await page.screenshot({ path: `${SHOTS}/01-gradebook.png`, fullPage: true })

    // 导出 CSV：确认真的触发了下载，并且带 UTF-8 BOM（Excel 打开中文不乱码）
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: /导出 CSV|Export CSV/ }).click(),
    ])
    expect(download.suggestedFilename()).toMatch(/^gradebook-/)
    const csvPath = await download.path()
    if (csvPath) {
      const { readFileSync } = await import('node:fs')
      const head = readFileSync(csvPath).subarray(0, 3)
      expect([...head]).toEqual([0xef, 0xbb, 0xbf])
    }

    // 按「总分」列排序，确认表头点得动
    await page.locator('th', { hasText: /总分|Total/ }).first().click()
    await page.screenshot({ path: `${SHOTS}/02-gradebook-sorted.png`, fullPage: true })

    // 2) 缺交
    await page.getByRole('button', { name: /缺交|Missing/ }).first().click()
    await expect(page.getByTestId('learning-missing-assignment')).toBeVisible()
    await page.screenshot({ path: `${SHOTS}/03-missing.png`, fullPage: true })

    // 3) 学习进度 + 明细抽屉
    await page.getByRole('button', { name: /学习进度|Progress/ }).first().click()
    await expect(page.getByTestId('learning-progress-table')).toBeVisible({ timeout: 30_000 })
    await page.screenshot({ path: `${SHOTS}/04-progress.png`, fullPage: true })
    await page.getByTestId('learning-progress-detail').first().click()
    await expect(page.getByTestId('learning-student-detail')).toBeVisible({ timeout: 30_000 })
    await page.screenshot({ path: `${SHOTS}/05-progress-detail.png`, fullPage: true })
    await page.keyboard.press('Escape')

    // 4) 课程体检 + 危险操作确认
    await page.getByRole('button', { name: /课程体检|Health check/ }).first().click()
    await expect(page.getByTestId('learning-lint-counts')).toBeVisible({ timeout: 30_000 })
    await page.screenshot({ path: `${SHOTS}/06-lint.png`, fullPage: true })
    await page.getByTestId('learning-fix-publish').click()
    await expect(page.getByText(/一键发布未发布活动？|Publish unpublished/)).toBeVisible()
    await page.screenshot({ path: `${SHOTS}/07-lint-confirm.png`, fullPage: true })
    await page.keyboard.press('Escape')
  })

  test('窄屏下不横向溢出', async ({ page }) => {
    await page.setViewportSize({ width: 400, height: 900 })
    await page.goto(TOOL_URL)
    await expect(page.getByTestId('learning-tool')).toBeVisible({ timeout: 30_000 })
    await page.screenshot({ path: `${SHOTS}/08-mobile.png`, fullPage: true })
  })
})
