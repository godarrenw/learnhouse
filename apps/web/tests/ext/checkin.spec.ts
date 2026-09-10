/**
 * 上课签到的端到端验证（Playwright）。
 *
 * 跑之前需要：
 *   1. 本地栈的 Postgres / Redis 已转出到宿主机（见 docs/sysu-sam/QA/checkin.md）
 *   2. 后端从源码起在 CHECKIN_API_BASE（默认 http://127.0.0.1:9004）
 *   3. 前端 bun run dev 起在 CHECKIN_WEB_BASE（默认 http://localhost:3004）
 *   4. 库里有一个教师账号和一个普通学生账号（见下面的环境变量默认值）
 *
 * 仓库本身没装 Playwright（上游只有 bun test 的纯逻辑单测），所以这份 spec 用
 * `bunx playwright test tests/ext/checkin.spec.ts` 跑，复用本机已下载的 chromium。
 * 要进 CI 得先把 @playwright/test 加进 devDependencies。
 *
 * 覆盖：老师开会话 → 投屏页拿到二维码与口令 → 学生扫码路径签到 → 学生口令路径签到
 * → 重复签被拒 → 老师端名单出现 → 关闭 → 关闭后再签被拒 → 导出 CSV。
 */
import { test, expect, request as playwrightRequest } from '@playwright/test'
import type { APIRequestContext, Browser, Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const WEB = process.env.CHECKIN_WEB_BASE ?? 'http://localhost:3004'
const API = process.env.CHECKIN_API_BASE ?? 'http://127.0.0.1:9004'
const TEACHER_EMAIL = process.env.CHECKIN_TEACHER_EMAIL ?? 'user1@example.local'
const TEACHER_PASSWORD = process.env.CHECKIN_TEACHER_PASSWORD ?? 'LocalDev#2026'
const STUDENT_EMAIL =
  process.env.CHECKIN_STUDENT_EMAIL ?? 'checkin-student@example.local'
const STUDENT_PASSWORD = process.env.CHECKIN_STUDENT_PASSWORD ?? 'Student#2026'

const SHOTS = path.resolve(__dirname, '../../../../docs/sysu-sam/QA/checkin')

async function shot(page: Page, name: string) {
  fs.mkdirSync(SHOTS, { recursive: true })
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) })
}

/** 走真实登录页登录，和学生实际用的路径一致。 */
async function login(page: Page, email: string, password: string) {
  // 后台首次进入会弹欢迎引导（fixed inset-0 的遮罩），它会挡住所有点击。
  // 直接把 useOnboarding 的 localStorage 状态置成「已看过」，跳过它。
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
      /* 隐私模式下写不进去，测试环境里不会发生 */
    }
  })
  await page.goto(`${WEB}/login`)
  await page.locator('input[type="email"], input[name="email"]').first().fill(email)
  await page.locator('input[type="password"]').first().fill(password)
  await page
    .locator('button[type="submit"]')
    .first()
    .click()
  await page.waitForURL((url: URL) => !url.pathname.startsWith('/login'), {
    timeout: 45_000,
  })
}

/** 教师身份的 API 上下文，用来读投屏页那份 live 数据（等价于「看屏幕」）。 */
async function teacherApi(): Promise<APIRequestContext> {
  const anon = await playwrightRequest.newContext({ baseURL: API })
  const res = await anon.post('/api/v1/auth/login', {
    form: { username: TEACHER_EMAIL, password: TEACHER_PASSWORD },
  })
  expect(res.ok()).toBeTruthy()
  const body = await res.json()
  return playwrightRequest.newContext({
    baseURL: API,
    extraHTTPHeaders: { Authorization: `Bearer ${body.tokens.access_token}` },
  })
}

async function readLive(api: APIRequestContext, sessionUuid: string) {
  const res = await api.get(`/api/v1/ext/checkin/sessions/${sessionUuid}/live`)
  expect(res.ok()).toBeTruthy()
  return res.json()
}

async function studentPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext()
  const page = await context.newPage()
  await login(page, STUDENT_EMAIL, STUDENT_PASSWORD)
  return page
}


/** 找一门公开且已发布的课程 —— 学生端页面只有这种能打开。 */
async function publicCourseUuid(): Promise<string> {
  const anon = await playwrightRequest.newContext({ baseURL: API })
  const res = await anon.get('/api/v1/courses/org_slug/default/page/1/limit/100')
  expect(res.ok()).toBeTruthy()
  const list = await res.json()
  const found = (Array.isArray(list) ? list : []).find(
    (c: any) => c.public && c.published
  )
  expect(found, '本地栈里需要至少一门公开已发布的课程').toBeTruthy()
  return found.course_uuid
}

test.describe.configure({ mode: 'serial' })

test.describe('上课签到', () => {
  let sessionUuid = ''
  let courseUuid = ''
  let api: APIRequestContext

  test.beforeAll(async () => {
    api = await teacherApi()
  })

  test('老师开一场签到，投屏页出二维码与六位口令', async ({ page }) => {
    await login(page, TEACHER_EMAIL, TEACHER_PASSWORD)
    await page.goto(`${WEB}/dash/tools/checkin`)

    await expect(page.getByTestId('checkin-course-select')).toBeVisible({
      timeout: 30_000,
    })
    // 等课程列表真的到了再截图，否则拍到的是「暂无课程」的中间态。
    // 判据是选中项有真实的 course_uuid，不是那个占位 option。
    await expect
      .poll(
        async () => await page.getByTestId('checkin-course-select').inputValue(),
        { timeout: 30_000 }
      )
      .toMatch(/^course_/)
    await expect(
      page
        .getByTestId('checkin-sessions-table')
        .or(page.getByTestId('checkin-empty'))
    ).toBeVisible({ timeout: 30_000 })
    courseUuid = await page.getByTestId('checkin-course-select').inputValue()
    await page.getByTestId('checkin-title-input').fill('端到端验证课')
    await shot(page, '01-tool-form')

    await page.getByTestId('checkin-start').click()
    await page.waitForURL(/\/dash\/tools\/checkin\/present\//, { timeout: 45_000 })
    sessionUuid = page.url().split('/present/')[1].split('?')[0]

    await expect(page.getByTestId('checkin-present')).toBeVisible()
    await expect(page.locator('[data-testid="checkin-qr"] svg')).toBeVisible({
      timeout: 20_000,
    })
    const code = (
      await page.getByTestId('checkin-present-code').innerText()
    ).trim()
    expect(code).toMatch(/^\d{6}$/)
    await shot(page, '02-present')
  })

  test('学生扫码路径签到成功', async ({ browser }) => {
    const live = await readLive(api, sessionUuid)
    const page = await studentPage(browser)
    // 扫码 = 打开二维码里那个带 token 的地址
    await page.goto(`${WEB}/checkin/${sessionUuid}?t=${live.token}`)
    await expect(page.getByTestId('checkin-result-ok')).toBeVisible({
      timeout: 30_000,
    })
    await shot(page, '03-student-qr-ok')
    await page.context().close()
  })

  test('同一个学生再签一次被拒', async ({ browser }) => {
    const page = await studentPage(browser)
    await page.goto(`${WEB}/checkin/${sessionUuid}`)
    await expect(page.getByTestId('checkin-result-ok')).toContainText(
      /已经签过|already/i,
      { timeout: 30_000 }
    )
    await shot(page, '04-student-duplicate')
    await page.context().close()
  })

  test('口令路径：老师账号用当前口令签到成功', async ({ browser }) => {
    // 本地栈只有一个普通学生账号，口令路径用教师账号自己签一次来验证
    // （后端不区分签到者身份，只要求是本组织的登录用户）。
    const live = await readLive(api, sessionUuid)
    const context = await browser.newContext()
    const page = await context.newPage()
    await login(page, TEACHER_EMAIL, TEACHER_PASSWORD)
    await page.goto(`${WEB}/checkin/${sessionUuid}`)
    await page.getByTestId('checkin-code-input').fill(live.code)
    await page.getByTestId('checkin-code-submit').click()
    await expect(page.getByTestId('checkin-result-ok')).toBeVisible({
      timeout: 30_000,
    })
    await shot(page, '05-student-code-ok')
    await context.close()
  })

  test('老师端名单出现签到者，关闭后学生被拒，CSV 能导出', async ({ page }) => {
    await login(page, TEACHER_EMAIL, TEACHER_PASSWORD)
    await page.goto(`${WEB}/dash/tools/checkin/present/${sessionUuid}`)
    await expect(page.getByTestId('checkin-present-list')).toBeVisible({
      timeout: 30_000,
    })
    await expect(page.getByTestId('checkin-present-count')).not.toHaveText('0')
    await shot(page, '06-present-with-records')

    await page.getByTestId('checkin-present-close').click()
    await page
      .getByRole('button', { name: /结束签到|close check-in/i })
      .last()
      .click()
    await page.waitForURL(/\/dash\/tools\/checkin$/, { timeout: 45_000 })
    await shot(page, '07-tool-after-close')

    const closed = await api.get(
      `/api/v1/ext/checkin/sessions/${sessionUuid}/live`
    )
    expect((await closed.json()).status).toBe('closed')

    const download = page.waitForEvent('download')
    await page.getByTestId('checkin-export').first().click()
    const file = await download
    expect(await file.path()).toBeTruthy()
  })

  test('课程页顶部出现「本节课签到」入口条', async ({ browser }) => {
    // 入口条要在学生能打开的课程页上验证，所以这里挑一门公开且已发布的课，
    // 而不是复用上面那门（本地栈里它是未发布的，学生打开是「无法访问此课程」）。
    // 同时换一场新的会话：上一场那个学生已经签过，入口条按设计不会再出现。
    const bannerCourseUuid = await publicCourseUuid()
    const created = await api.post(
      `/api/v1/ext/checkin/courses/${bannerCourseUuid}/sessions`,
      { data: { title: '入口条验证课', refresh_seconds: 20 } }
    )
    expect(created.ok()).toBeTruthy()
    const fresh = await created.json()

    const page = await studentPage(browser)
    // 课程页的路径段不带 course_ 前缀
    await page.goto(
      `${WEB}/course/${bannerCourseUuid.replace('course_', '')}`
    )
    await expect(page.getByTestId('checkin-banner')).toBeVisible({
      timeout: 30_000,
    })
    await expect(page.getByTestId('checkin-banner')).toContainText('入口条验证课')
    await shot(page, '09-course-banner')

    await api.post(
      `/api/v1/ext/checkin/sessions/${fresh.session_uuid}/close`
    )
    await page.context().close()
  })

  test('未登录扫码 → 登录 → 回跳并自动签到', async ({ browser }) => {
    // 单独开一场，避免和前面几条用例的会话状态互相干扰
    const bannerCourseUuid = await publicCourseUuid()
    const created = await api.post(
      `/api/v1/ext/checkin/courses/${bannerCourseUuid}/sessions`,
      { data: { title: '未登录回跳验证', refresh_seconds: 20 } }
    )
    expect(created.ok()).toBeTruthy()
    const fresh = await created.json()
    const live = await readLive(api, fresh.session_uuid)

    const context = await browser.newContext()
    const page = await context.newPage()
    // 没有任何登录态，直接打开二维码里那个地址
    await page.goto(`${WEB}/checkin/${fresh.session_uuid}?t=${live.token}`)
    await expect(page.getByTestId('checkin-login-link')).toBeVisible({
      timeout: 30_000,
    })
    await shot(page, '10-anon-login-prompt')

    await page.getByTestId('checkin-login-link').click()
    // 回跳目标要原样带着 ?t=，否则登录回来还得再扫一次
    await page.waitForURL(/\/login\?next=/, { timeout: 30_000 })
    expect(decodeURIComponent(page.url())).toContain(`?t=${live.token}`)

    await page.locator('input[type="email"]').first().fill(STUDENT_EMAIL)
    await page.locator('input[type="password"]').first().fill(STUDENT_PASSWORD)
    await page.locator('button[type="submit"]').first().click()

    // 登录后回到签到页，带着 token 自动提交
    await page.waitForURL(new RegExp(`/checkin/${fresh.session_uuid}`), {
      timeout: 45_000,
    })
    await expect(page.getByTestId('checkin-result-ok')).toBeVisible({
      timeout: 30_000,
    })
    await shot(page, '11-anon-after-login-ok')

    await api.post(`/api/v1/ext/checkin/sessions/${fresh.session_uuid}/close`)
    await context.close()
  })

  test('关闭之后的会话拒绝签到', async ({ browser }) => {
    const context = await browser.newContext()
    const page = await context.newPage()
    await login(page, STUDENT_EMAIL, STUDENT_PASSWORD)
    await page.goto(`${WEB}/checkin/${sessionUuid}`)
    // 会话已关闭时，状态判定先于「是否已签过」，所以任何人再提交都拿 410
    const res = await api.post(
      `/api/v1/ext/checkin/sessions/${sessionUuid}/check`,
      { data: { code: '000000' } }
    )
    expect(res.status()).toBe(410)
    expect((await res.json()).detail.code).toBe('session_closed')
    await shot(page, '08-student-after-close')
    await context.close()
  })
})
