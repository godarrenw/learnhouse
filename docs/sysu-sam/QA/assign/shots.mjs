/**
 * 作业工具五个 Tab 的端到端走查：既截图，也断言。任何一条断言不成立就非零退出，
 * 所以它是能当验收用的，不只是拍照。
 *
 * 跑法（在仓库根目录）：
 *
 *   node docs/sysu-sam/QA/assign/login.mjs        # 存登录态
 *   node docs/sysu-sam/QA/assign/shots.mjs        # 走查 + 截图
 *
 * 前置：本地后端 9005、前端 3005（见 docs/sysu-sam/QA/assign-tools.md 第七节）。
 * 只做只读操作 —— 学期复用只走到 confirm=false 的摘要，不会真的复制课程。
 */
import { createRequire } from 'node:module'

// 脚本放在 docs/ 下，node 会按脚本所在目录找 node_modules，找不到 playwright。
// 从仓库里唯一装了 playwright 的地方（apps/e2e）解析它。
const require = createRequire(new URL('../../../../apps/e2e/package.json', import.meta.url))
const { chromium } = require('@playwright/test')
import fs from 'node:fs'

const BASE = process.env.BASE || 'http://localhost:3005'
const STATE = process.env.STATE || './.assign-auth-state.json'
const OUT = process.env.OUT || new URL('.', import.meta.url).pathname

let failures = 0
function check(ok, what) {
  if (ok) {
    console.log('  ok  ', what)
  } else {
    failures += 1
    console.error('  FAIL', what)
  }
}

const COURSE_CONTENT = '制造系统自动化技术（含数字化）'
const COURSE_ASSIGN = 'AI-Driven Advanced Manufacturing'
const PAGE_LABEL = /1\.1 什么是自动化/

fs.mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch()
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  storageState: STATE,
})
const page = await context.newPage()
// console 里的「Failed to load resource」看不出是哪个请求，所以按响应记，
// 这样能把上游 analytics/events 的 400 排除掉（本地没配 PostHog，和作业工具无关）。
const badResponses = []
page.on('response', (r) => {
  if (r.status() >= 400) badResponses.push(`${r.status()} ${r.url()}`)
})

async function dismissOnboarding() {
  for (let i = 0; i < 6; i += 1) {
    const start = page.getByRole('button', { name: /^开始|Get started/ })
    if (await start.count()) {
      await start.first().click({ force: true }).catch(() => {})
      await page.waitForTimeout(1200)
    }
    await page.keyboard.press('Escape').catch(() => {})
    await page.waitForTimeout(500)
    if (!(await page.locator('.fixed.inset-0').count())) break
  }
}

async function pickCourse(name) {
  const select = page.locator('select').first()
  await select.selectOption({ label: name })
  await page.waitForTimeout(2500)
}

async function tab(key) {
  await page.click(`[data-testid="assign-subtab-${key}"]`)
  await page.waitForSelector(`[data-testid="assign-tab-${key}"]`, { timeout: 30_000 })
  await page.waitForTimeout(1500)
}

async function shot(name) {
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true })
  console.log('shot', name)
}

await page.goto(`${BASE}/dash/tools/assign`, { waitUntil: 'domcontentloaded' })
await page.waitForSelector('[data-testid="assign-subtabs"]', { timeout: 60_000 })
await page.waitForTimeout(2000)
await dismissOnboarding()
await page.waitForTimeout(1500)

// ---- 1. AI 出题：真调一次大模型 ----
await pickCourse(COURSE_CONTENT)
await tab('ai')
const pageSelect = page.locator('[data-testid="assign-ai-page"]')
const pageOption = await pageSelect
  .locator('option')
  .filter({ hasText: PAGE_LABEL })
  .first()
  .getAttribute('value')
await pageSelect.selectOption(pageOption)
await page.locator('[data-testid="assign-ai-count"]').fill('3')
check((await page.locator('[data-testid^="assign-subtab-"]').count()) === 5, '五个分段 Tab 都在')
check(
  (await page.locator('[data-testid="assign-ai-page"] option').count()) > 1,
  'AI 出题的内容页下拉拉到了课程结构'
)
check(
  (await page.locator('[data-testid="assign-ai-model"] option').count()) > 1,
  '模型下拉拉到了 /ext/assign/llm/models 的结果'
)
await shot('1-ai-setup')

await page.click('[data-testid="assign-ai-draft"]')
await page.waitForSelector('[data-testid="assign-spec-preview"]', { timeout: 180_000 })
await page.waitForTimeout(1200)
check(
  (await page.locator('[data-testid^="assign-spec-task-"]').count()) > 0,
  'AI 出题返回了至少一道可编辑的题'
)
check(
  (await page.locator('[data-testid="assign-ai-create"]').count()) === 1,
  '出完题后出现了「一键布置」'
)
await shot('2-ai-preview')

// ---- 2. 随堂测 ----
await tab('quiz')
check(
  (await page.locator('[data-testid="assign-quiz-formative"]').isChecked()),
  '随堂测默认勾着「形成性」'
)
check((await page.locator('[data-testid="assign-quiz-q-0"]').count()) === 1, '随堂测表单默认给了一道题')
await shot('3-quiz-form')

// ---- 3. 查重 / 随堂测结果：换到有作业的那门课 ----
await pickCourse(COURSE_ASSIGN)
await page.waitForTimeout(2000)
await tab('quiz')
const quizPick = page.locator('[data-testid="assign-quiz-pick"]')
const quizOptions = await quizPick.locator('option').count()
if (quizOptions > 1) {
  await quizPick.selectOption({ index: 1 })
  await page.waitForTimeout(3000)
}
await shot('4-quiz-results')

await tab('similarity')
const simPick = page.locator('[data-testid="assign-sim-assignment"]')
if ((await simPick.locator('option').count()) > 1) {
  await simPick.selectOption({ index: 1 })
  await page.waitForTimeout(3000)
}
check(
  (await page.locator('[data-testid="assign-sim-threshold"]').count()) === 1,
  '查重有阈值滑块'
)
check(
  (await page.locator('[data-testid="assign-sim-disclaimer"]').count()) === 1,
  '查重结果原样显示了后端的免责说明'
)
await shot('5-similarity')

// ---- 4. 学期复用：只走到 confirm=false 的摘要 ----
await pickCourse(COURSE_CONTENT)
await tab('clone')
await page.locator('[data-testid="assign-clone-name"]').fill('2027 春 · 制造系统自动化技术')
await page.click('[data-testid="assign-clone-next1"]')
await page.waitForTimeout(600)
await page.locator('[data-testid="assign-clone-days"]').fill('182')
await page.click('[data-testid="assign-clone-preview"]')
await page.waitForSelector('[data-testid="assign-clone-summary"]', { timeout: 60_000 })
await page.waitForTimeout(1000)
const summaryText = await page.locator('[data-testid="assign-clone-summary"]').innerText()
check(summaryText.includes('2027 春'), '学期复用摘要回显了新课程名')
check(
  (await page.locator('[data-testid="assign-clone-done"]').count()) === 0,
  '只试算，没有真的复制课程'
)
await shot('6-clone-summary')

// ---- 5. 版本回滚 ----
await tab('versions')
const verSelect = page.locator('[data-testid="assign-ver-page"]')
const verOption = await verSelect
  .locator('option')
  .filter({ hasText: PAGE_LABEL })
  .first()
  .getAttribute('value')
await verSelect.selectOption(verOption)
await page.waitForTimeout(2500)
const compare = page.locator('[data-testid^="assign-ver-compare-"]').first()
if (await compare.count()) {
  await compare.click()
  await page.waitForSelector('[data-testid="assign-ver-diff"]', { timeout: 60_000 })
  await page.waitForTimeout(2500)
}
check(
  (await page.locator('[data-testid^="assign-ver-compare-"]').count()) > 0,
  '版本列表拉到了历史版本'
)
check((await page.locator('[data-testid="assign-ver-diff"]').count()) === 1, 'diff 视图出来了')
await shot('7-versions-diff')
const unified = page.locator('[data-testid="assign-ver-view-unified"]')
if (await unified.count()) {
  await unified.click()
  await page.waitForTimeout(1200)
  await shot('8-versions-unified')
}

// ---- 6. 窄屏：不能横向溢出 ----
await page.setViewportSize({ width: 400, height: 900 })
await tab('ai')
await page.waitForTimeout(1500)
const overflow = await page.evaluate(
  () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
)
await shot('9-mobile-ai')
check(!overflow, '400px 窄屏没有横向溢出')

const relevant = badResponses.filter((e) => !/\/analytics\//.test(e))
check(relevant.length === 0, `除上游 analytics 外没有失败请求（实际 ${relevant.length} 条）`)
if (relevant.length) console.error(relevant.slice(0, 8))
console.log('（被忽略的上游失败请求：', badResponses.length - relevant.length, '条）')

await browser.close()
if (failures) {
  console.error(`\n${failures} 条断言没过`)
  process.exit(1)
}
console.log('\n全部断言通过')
