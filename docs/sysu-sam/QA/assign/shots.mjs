/**
 * 作业工具五个 Tab 的截图脚本（QA 证据用，不进 e2e 套件）。
 * 跑法：cd apps/e2e && node _shots.mjs
 * 前置：先跑 _login.mjs 存下登录态；本地后端 9005、前端 3005。
 *
 * 只做只读操作 —— 学期复用只走到 confirm=false 的摘要，不会真的复制课程。
 */
import { chromium } from '@playwright/test'
import fs from 'node:fs'

const BASE = process.env.BASE || 'http://localhost:3005'
const STATE = '/private/tmp/claude-501/-Volumes-D-code/748617f2-89b2-480a-a7d9-3f9a18f4b748/scratchpad/state.json'
const OUT = process.env.OUT || '/Volumes/D/code/lh-wt-assign/docs/sysu-sam/QA/assign'

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
const errors = []
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(m.text())
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
await shot('1-ai-setup')

await page.click('[data-testid="assign-ai-draft"]')
await page.waitForSelector('[data-testid="assign-spec-preview"]', { timeout: 180_000 })
await page.waitForTimeout(1200)
await shot('2-ai-preview')

// ---- 2. 随堂测 ----
await tab('quiz')
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
console.log('mobile horizontal overflow:', overflow)

console.log('console errors:', JSON.stringify(errors.slice(0, 10), null, 2))
await browser.close()
