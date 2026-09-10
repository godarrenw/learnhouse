/**
 * 目标：证明「教学工具 → 作业工具」这个页面上，五个 Tab 都真的连着后端在干活，
 * 而不只是画了个壳。
 *
 * 每条断言都挑那种「坏了就等于功能没有」的性质：
 *  - AI 出题：能读到课程结构，能把大模型出的题渲染成可编辑的预览；
 *    没配大模型端点时是明确禁用 + 一句人话，而不是点了没反应
 *  - 随堂测：默认是形成性的；结果面板按题算答对率；能导出 CSV
 *  - 查重：后端给的免责说明必须原样出现在页面上 —— 这是产品口径，不是装饰
 *  - 学期复用：向导第三步的摘要是 confirm=false 真跑出来的，**且这一步不写库**
 *    （用例会去核对课程数没变）
 *  - 版本回滚：能列出历史版本、能 diff、两栏和合并两种视图都在
 *
 * 夹具每次新建一门带随机后缀的课，跑完删掉，所以对着共享的本地预发栈跑也不留垃圾。
 */
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { test, expect } from '../../../../core/fixtures'
import { ADMIN_STATE } from '../../../../core/sharedAuth'
import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  ORG_SLUG,
  SHARED_STUDENT_EMAIL,
  SHARED_STUDENT_PASSWORD,
} from '../../../../core/instance'
import { getOrg, login, req } from '../../../../core/client'
import {
  AssignFixture,
  cleanupAssignFixture,
  deleteCoursesNamed,
  seedAssignFixture,
} from '../api'

test.use({ storageState: ADMIN_STATE })

const TOOL_URL = '/dash/tools/assign'

/**
 * 设了 `EXT_SHOTS=1` 就顺手把每个 Tab 截一张图到 docs/sysu-sam/QA/assign/，
 * QA 文档里的图就是这么来的。默认不截，免得每次跑用例都写文件。
 */
const SHOTS_DIR = fileURLToPath(new URL('../../../../../../docs/sysu-sam/QA/assign/', import.meta.url))
const WANT_SHOTS = process.env.EXT_SHOTS === '1'

async function maybeShot(page: any, name: string, focus?: any) {
  if (!WANT_SHOTS) return
  mkdirSync(SHOTS_DIR, { recursive: true })
  // 工具页是固定高度的 grid，内容在一个内部滚动容器里，fullPage 只能拍到首屏。
  // 所以先把要看的那张卡片滚进视口再拍。
  if (focus) {
    await focus.scrollIntoViewIfNeeded()
    await page.waitForTimeout(400)
  }
  await page.screenshot({ path: `${SHOTS_DIR}${name}.png` })
}
/** 学期复用那一步会用到的新课程名，跑完按这个前缀清理。 */
const CLONE_NAME_PREFIX = 'E2E 复用 '

let fixture: AssignFixture
let adminToken: string
let cloneName: string

test.beforeAll(async () => {
  adminToken = await login(ADMIN_EMAIL, ADMIN_PASSWORD)
  const org = await getOrg()

  // 学生是可选的：本地预发库是邀请制，新建学生会 403。有共享学生就用它交一份卷，
  // 好让结果面板有真实的答对率；没有就只验空态。
  let studentToken: string | undefined
  let studentId: number | undefined
  if (SHARED_STUDENT_EMAIL && SHARED_STUDENT_PASSWORD) {
    try {
      studentToken = await login(SHARED_STUDENT_EMAIL, SHARED_STUDENT_PASSWORD)
      const me = await req<any>('GET', '/users/session', studentToken)
      studentId = me?.user?.id ?? me?.id
    } catch {
      studentToken = undefined
    }
  }

  fixture = await seedAssignFixture(adminToken, org, studentToken, studentId)
  cloneName = `${CLONE_NAME_PREFIX}${fixture.courseUuid.slice(-8)}`
  // 说清楚这一轮到底有没有学生交卷 —— 否则「答对率」那条断言被静默跳过了都看不出来
  // eslint-disable-next-line no-console
  console.log(
    fixture.submittedStudentId === null
      ? '[ext/assign] 没有学生交卷，答对率那一段会跳过'
      : `[ext/assign] 学生 ${fixture.submittedStudentId} 已交卷，会校验答对率`,
  )
})

test.afterAll(async () => {
  await cleanupAssignFixture(adminToken, fixture)
  await deleteCoursesNamed(adminToken, ORG_SLUG, (name) => name.startsWith(CLONE_NAME_PREFIX))
})

/** 打开工具页并把课程下拉切到夹具那门课。 */
async function openTool(page: any, tab: string) {
  await page.goto(TOOL_URL)
  await expect(page.getByTestId('assign-subtabs')).toBeVisible()
  const courseSelect = page.locator('select').first()
  await expect(courseSelect.locator('option')).not.toHaveCount(0)
  await courseSelect.selectOption({ value: fixture.courseUuid })
  await page.getByTestId(`assign-subtab-${tab}`).click()
  await expect(page.getByTestId(`assign-tab-${tab}`)).toBeVisible()
}

test('工具页把五个 Tab 都挂出来了', async ({ page }) => {
  await page.goto(TOOL_URL)
  await expect(page.getByTestId('assign-subtabs')).toBeVisible()
  for (const key of ['ai', 'quiz', 'similarity', 'clone', 'versions']) {
    await expect(page.getByTestId(`assign-subtab-${key}`)).toBeVisible()
  }
  await maybeShot(page, '1-ai-setup')
})

test('AI 出题读得到课程结构，出的题落在可编辑的预览里', async ({ page }) => {
  await openTool(page, 'ai')

  // 内容页下拉来自 /courses/{uuid}/meta，能看到夹具那一页就说明结构树拉到了
  const pageSelect = page.getByTestId('assign-ai-page')
  await expect(pageSelect.locator('option', { hasText: fixture.pageName })).toHaveCount(1)

  const draftButton = page.getByTestId('assign-ai-draft')
  const modelSelect = page.getByTestId('assign-ai-model')

  if (await modelSelect.isDisabled()) {
    // 没配大模型端点：必须是明确禁用 + 一句人话，而不是点了没反应
    await expect(draftButton).toBeDisabled()
    await expect(page.getByText(/没有配置大模型端点|No model endpoint/)).toBeVisible()
    test.info().annotations.push({
      type: 'skipped-assertion',
      description: '这套实例没配 LEARNHOUSE_EXT_LLM_*，跳过真出题那一段',
    })
    return
  }

  const pageOptionValue = await pageSelect
    .locator('option', { hasText: fixture.pageName })
    .first()
    .getAttribute('value')
  await pageSelect.selectOption(pageOptionValue as string)
  await page.getByTestId('assign-ai-count').fill('2')
  await draftButton.click()

  // 大模型可能要十几秒
  await expect(page.getByTestId('assign-spec-preview')).toBeVisible({ timeout: 180_000 })
  await expect(page.getByTestId('assign-spec-task-0')).toBeVisible()
  // 题干可编辑，而不是只读的展示
  await expect(page.getByTestId('assign-spec-q-0-0')).toBeEditable()
  await expect(page.getByTestId('assign-ai-create')).toBeVisible()
  await maybeShot(page, '2-ai-preview', page.getByTestId('assign-spec-preview'))
})

test('随堂测默认是形成性的，结果面板按题给答对率并能导出 CSV', async ({ page }) => {
  await openTool(page, 'quiz')

  // 建卷表单：形成性默认勾上（不计成绩、交卷即给答案，这是随堂测的用法）
  await expect(page.getByTestId('assign-quiz-formative')).toBeChecked()
  await expect(page.getByTestId('assign-quiz-q-0')).toBeVisible()

  // 结果面板：选夹具里那份随堂测
  await page.getByTestId('assign-quiz-pick').selectOption({ value: fixture.quizAssignmentUuid })
  const results = page.getByTestId('assign-quiz-results')
  await expect(results.getByText('CNC 里的 C 指的是什么？')).toBeVisible({ timeout: 30_000 })

  if (fixture.submittedStudentId !== null) {
    // 学生全选对了，这道题的答对率应该是 100%
    await expect(results.getByText('100%').first()).toBeVisible()
    // 有数据才谈得上导出
    await expect(page.getByTestId('assign-quiz-export').getByRole('button')).toBeEnabled()
  } else {
    test.info().annotations.push({
      type: 'skipped-assertion',
      description: '这套实例造不出学生（邀请制），只验题目清单渲染，不验答对率',
    })
  }
  await maybeShot(page, '3-quiz-results', results)
})

test('查重把后端的免责说明原样显示出来', async ({ page }) => {
  await openTool(page, 'similarity')

  await expect(page.getByTestId('assign-sim-threshold')).toBeVisible()
  await page.getByTestId('assign-sim-assignment').selectOption({
    value: fixture.quizAssignmentUuid,
  })

  const disclaimer = page.getByTestId('assign-sim-disclaimer')
  await expect(disclaimer).toBeVisible({ timeout: 30_000 })
  // 「相似度只是线索，不是抄袭的结论」是产品口径，不能被前端改写或省略
  await expect(disclaimer).toContainText('不是抄袭的结论')
  await maybeShot(page, '4-similarity', disclaimer)
})

test('学期复用的确认摘要是真跑出来的，而且这一步不写库', async ({ page }) => {
  const before = await req<any[]>(
    'GET',
    `/courses/org_slug/${ORG_SLUG}/page/1/limit/100?include_unpublished=true`,
    adminToken,
  )

  await openTool(page, 'clone')
  await page.getByTestId('assign-clone-name').fill(cloneName)
  await page.getByTestId('assign-clone-next1').click()
  await page.getByTestId('assign-clone-days').fill('182')
  await page.getByTestId('assign-clone-preview').click()

  const summary = page.getByTestId('assign-clone-summary')
  await expect(summary).toBeVisible({ timeout: 30_000 })
  await expect(summary).toContainText(cloneName)
  // 摘要里应该列出夹具那份带截止日期的作业，并把 2099-03-01 顺延 182 天
  await expect(summary).toContainText(fixture.dueAssignmentTitle)
  await expect(summary).toContainText('2099-08-30')
  // 还没确认，不该出现「已复制完成」
  await expect(page.getByTestId('assign-clone-done')).toHaveCount(0)

  const after = await req<any[]>(
    'GET',
    `/courses/org_slug/${ORG_SLUG}/page/1/limit/100?include_unpublished=true`,
    adminToken,
  )
  expect(after.length).toBe(before.length)
  await maybeShot(page, '5-clone-summary', summary)
})

test('版本回滚能列出历史版本，并给出两栏与合并两种 diff', async ({ page }) => {
  await openTool(page, 'versions')

  await page.getByTestId('assign-ver-page').selectOption({ value: fixture.pageActivityUuid })

  // 夹具改了两次内容，所以至少有两个历史版本
  const compareLinks = page.locator('[data-testid^="assign-ver-compare-"]')
  await expect(compareLinks.first()).toBeVisible({ timeout: 30_000 })
  expect(await compareLinks.count()).toBeGreaterThanOrEqual(2)

  // 挑**最老**的那一版（列表是倒序，所以是最后一行）。别挑第一行：同一套实例上
  // 别的用例也可能给这一页再存几版，v1 的内容却是稳定的。
  await compareLinks.last().click()
  const diff = page.getByTestId('assign-ver-diff')
  await expect(diff).toBeVisible({ timeout: 30_000 })
  // 左栏是 v1，正文里应该还留着第一稿那句话
  await expect(diff).toContainText('第一稿')

  await maybeShot(page, '6-versions-diff', diff)

  await page.getByTestId('assign-ver-view-unified').click()
  await expect(page.getByTestId('assign-ver-unified')).toBeVisible()
  await maybeShot(page, '7-versions-unified', page.getByTestId('assign-ver-unified'))
})

test('窄屏下页面不横向溢出', async ({ page }) => {
  await page.setViewportSize({ width: 400, height: 900 })
  await page.goto(TOOL_URL)
  await expect(page.getByTestId('assign-subtabs')).toBeVisible()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  )
  expect(overflow).toBe(false)
  await maybeShot(page, '8-mobile')
})
