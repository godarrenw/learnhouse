/**
 * 学情工具的端到端走查：四个 Tab 走一遍，顺带验导出 CSV 与排序表头。
 *
 * 集成时从 `apps/web/tests/ext/learning.e2e.ts` 迁过来的。原来那份在 apps/web 下
 * 自带一套 playwright 配置，但 `@playwright/test` 不是 apps/web 的依赖，只能靠
 * `bunx playwright` 临时拉包跑 —— 临时包解析不到配置里的 import，干净环境下
 * 直接 MODULE_NOT_FOUND。迁到这里之后复用本目录已有的基建：
 * 会话由 global-setup 登录一次存成 storageState，onboarding 遮罩由 fixtures 预置，
 * 版本也跟着 apps/e2e 钉在 @playwright/test 1.49.1，不再需要 @ts-nocheck。
 *
 * 跑法见 features/ext/README.md。
 */
import { expect, test } from '../../../core/fixtures'
import { BASE_URL } from '../../../core/instance'
import { ADMIN_STATE, STUDENT_STATE } from '../../../core/sharedAuth'

const TOOL_URL = `${BASE_URL}/dash/tools/learning`
// 截图落到仓库根的 docs/ 下（playwright 的工作目录是 apps/e2e）
const SHOTS = process.env.LH_E2E_SHOTS ?? '../../docs/sysu-sam/QA/learning'
// 有演示数据的那门课，见 docs/sysu-sam/QA/learning/seed-demo-data.sql
const DEMO_COURSE = process.env.LH_E2E_DEMO_COURSE ?? 'AI-Driven Advanced Manufacturing'

test.describe('教学工具 / 学情', () => {
  test.use({ storageState: ADMIN_STATE })

  test('四个 Tab 都能打开并出数据', async ({ page }) => {
    await page.goto(TOOL_URL)
    await expect(page.getByTestId('learning-tool')).toBeVisible({ timeout: 30_000 })

    // 选课下拉由路由页统一渲染，选中有演示数据的那门课
    await page.locator('select').first().selectOption({ label: DEMO_COURSE })

    // 1) 成绩册
    const gradebook = page.getByTestId('learning-gradebook-table')
    await expect(gradebook).toBeVisible({ timeout: 30_000 })
    await expect(gradebook).toContainText('已批')
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
      expect([...readFileSync(csvPath).subarray(0, 3)]).toEqual([0xef, 0xbb, 0xbf])
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

  test('概览页显示最近学习动态卡片', async ({ page }) => {
    // recent 是组织级接口，不用选课。集成时把它接到概览页，
    // 老师进教学工具第一眼就能看到最近谁在学什么。
    await page.goto(`${BASE_URL}/dash/tools`)
    const card = page.getByTestId('sysu-recent-activity')
    await expect(card).toBeVisible({ timeout: 30_000 })
    // 卡片里至少有一条事件，且工具网格没被它挤掉
    await expect(card.locator('li')).not.toHaveCount(0)
    await expect(page.getByTestId('sysu-tools-grid')).toBeVisible()
    await page.screenshot({ path: `${SHOTS}/09-overview-recent.png`, fullPage: true })
  })
})

/* --- SYSU-SAM: 越权面的反面用例 --- */
test.describe('教学工具 / 学情 — 普通成员视角', () => {
  test.use({ storageState: STUDENT_STATE })

  /**
   * 学情的每个接口都吐学生姓名、成绩和学习记录，所以课程级判定用的是「能改这门课」
   * 而不是 read —— 公开课程的 read 权限对任何登录用户都成立，按 read 判等于把
   * 全班数据开放给选了课的人。接口层的 403 由 pytest 覆盖
   * （`test_student_cannot_read_class_data_of_public_course`，四个只读接口逐个验），
   * 这里只确认界面这一端也进不去。
   */
  test('User 角色进不去学情工具', async ({ page }) => {
    await page.goto(TOOL_URL)
    await expect(page.getByTestId('learning-tool')).toHaveCount(0)
    await expect(page.locator('body')).toContainText(
      /don't have access|permission|没有权限|404|not found|页面不存在/i
    )
  })
})
/* --- /SYSU-SAM --- */
