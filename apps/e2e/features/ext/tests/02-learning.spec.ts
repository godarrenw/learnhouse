/**
 * 学情工具的端到端走查：四个 Tab 各一条，外加概览页的最近动态卡片与越权反面用例。
 *
 * 集成时从 `apps/web/tests/ext/learning.e2e.ts` 迁过来的。原来那份在 apps/web 下
 * 自带一套 playwright 配置，但 `@playwright/test` 不是 apps/web 的依赖，只能靠
 * `bunx playwright` 临时拉包跑 —— 临时包解析不到配置里的 import，干净环境下
 * 直接 MODULE_NOT_FOUND。迁到这里之后复用本目录已有的基建：
 * 会话由 global-setup 登录一次存成 storageState，onboarding 遮罩由 fixtures 预置，
 * 版本也跟着 apps/e2e 钉在 @playwright/test 1.49.1，不再需要 @ts-nocheck。
 *
 * **为什么按 Tab 拆开而不是一条走完**：合成一条的话，成绩册那步一挂，后面三个 Tab
 * 就再也跑不到，报告里只看得见第一个错。拆开之后每个 Tab 独立成败，定位快得多。
 *
 * 跑法见 features/ext/README.md。依赖 `docs/sysu-sam/QA/learning/seed-demo-data.sql`
 * 造的演示数据 —— 干净的库里四个 Tab 全是空态，用例会因为找不到「已批」而失败。
 */
import { readFileSync } from 'node:fs'

import { expect, test } from '../../../core/fixtures'
import { BASE_URL } from '../../../core/instance'
import { ADMIN_STATE, STUDENT_STATE } from '../../../core/sharedAuth'

const TOOL_URL = `${BASE_URL}/dash/tools/learning`
// 截图落到仓库根的 docs/ 下（playwright 的工作目录是 apps/e2e）
const SHOTS = process.env.LH_E2E_SHOTS ?? '../../docs/sysu-sam/QA/learning'
// 有演示数据的那门课，见 docs/sysu-sam/QA/learning/seed-demo-data.sql
const DEMO_COURSE = process.env.LH_E2E_DEMO_COURSE ?? 'AI-Driven Advanced Manufacturing'

/** 打开工具并选中有演示数据的课程。选课下拉由 `/dash/tools/[tool]` 路由页统一渲染。 */
async function openTool(page: import('@playwright/test').Page) {
  await page.goto(TOOL_URL)
  await expect(page.getByTestId('learning-tool')).toBeVisible({ timeout: 30_000 })
  await page.locator('select').first().selectOption({ label: DEMO_COURSE })
}

/** 切到某个子 Tab（它们是组件内 state，不改 URL）。 */
async function openTab(page: import('@playwright/test').Page, name: RegExp) {
  await page.getByRole('button', { name }).first().click()
}

test.describe('教学工具 / 学情', () => {
  test.use({ storageState: ADMIN_STATE })

  test('成绩册渲染已批 / 待批·迟交 / 未交三种状态', async ({ page }) => {
    await openTool(page)

    const gradebook = page.getByTestId('learning-gradebook-table')
    await expect(gradebook).toBeVisible({ timeout: 30_000 })
    // 三种状态都要在。「待批·迟交」是最容易写错的一档：服务端从不主动写 LATE，
    // 迟交是靠「提交时间 vs 截止时刻」自己算出来的，只断言「已批」盖不住它。
    await expect(gradebook).toContainText('已批')
    await expect(gradebook).toContainText('待批·迟交')
    await expect(gradebook).toContainText('未交')
    await page.screenshot({ path: `${SHOTS}/01-gradebook.png`, fullPage: true })
  })

  test('导出 CSV 真的下载，且带 UTF-8 BOM', async ({ page }) => {
    await openTool(page)
    await expect(page.getByTestId('learning-gradebook-table')).toBeVisible({ timeout: 30_000 })

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: /导出 CSV|Export CSV/ }).click(),
    ])
    expect(download.suggestedFilename()).toMatch(/^gradebook-/)
    const csvPath = await download.path()
    // 不做 if 保护：拿不到落盘路径就是这条用例失败，不能悄悄跳过 BOM 检查
    expect(csvPath).not.toBeNull()
    expect([...readFileSync(csvPath as string).subarray(0, 3)]).toEqual([0xef, 0xbb, 0xbf])
  })

  test('点表头能排序，方向写进 aria-sort', async ({ page }) => {
    await openTool(page)
    const gradebook = page.getByTestId('learning-gradebook-table')
    await expect(gradebook).toBeVisible({ timeout: 30_000 })

    const totalHeader = gradebook.locator('th', { hasText: /总分|Total/ }).first()
    await totalHeader.click()
    // 只「点得动」不算数：要确认 DataTable 真的进入了排序态
    await expect(totalHeader).toHaveAttribute('aria-sort', /ascending|descending/)
    await page.screenshot({ path: `${SHOTS}/02-gradebook-sorted.png`, fullPage: true })
  })

  test('缺交名单列出没交的人，并能按作业筛选', async ({ page }) => {
    await openTool(page)
    await openTab(page, /缺交|Missing/)

    await expect(page.getByTestId('learning-missing-assignment')).toBeVisible()
    // 筛选框在不代表名单对，得看见真的有人被列成「未交」
    await expect(page.getByTestId('learning-missing')).toContainText('未交')
    await page.screenshot({ path: `${SHOTS}/03-missing.png`, fullPage: true })
  })

  test('学习进度点得开单人明细，明细里写了分母口径', async ({ page }) => {
    await openTool(page)
    await openTab(page, /学习进度|Progress/)

    await expect(page.getByTestId('learning-progress-table')).toBeVisible({ timeout: 30_000 })
    await page.screenshot({ path: `${SHOTS}/04-progress.png`, fullPage: true })

    await page.getByTestId('learning-progress-detail').first().click()
    const detail = page.getByTestId('learning-student-detail')
    await expect(detail).toBeVisible({ timeout: 30_000 })
    // 分母含未发布活动，这句说明必须在，否则老师会和学生端看到的百分比对不上
    await expect(detail).toContainText(/分母|denominator/i)
    await page.screenshot({ path: `${SHOTS}/05-progress-detail.png`, fullPage: true })
    await page.keyboard.press('Escape')
  })

  test('课程体检分级显示，一键发布有二次确认', async ({ page }) => {
    await openTool(page)
    await openTab(page, /课程体检|Health check/)

    await expect(page.getByTestId('learning-lint-counts')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByTestId('learning-lint-list')).toBeVisible()
    await page.screenshot({ path: `${SHOTS}/06-lint.png`, fullPage: true })

    // 危险操作走 ConfirmDanger，绝不能点一下就直接发布给学生
    await page.getByTestId('learning-fix-publish').click()
    await expect(page.getByText(/一键发布未发布活动？|Publish unpublished/)).toBeVisible()
    await page.screenshot({ path: `${SHOTS}/07-lint-confirm.png`, fullPage: true })
    await page.keyboard.press('Escape')
  })

  test('窄屏下不横向溢出', async ({ page }) => {
    await page.setViewportSize({ width: 400, height: 900 })
    await page.goto(TOOL_URL)
    await expect(page.getByTestId('learning-tool')).toBeVisible({ timeout: 30_000 })

    // 只截图的话这条用例永远不会失败，得真量一下
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth
    )
    expect(overflow).toBeLessThanOrEqual(1)
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
