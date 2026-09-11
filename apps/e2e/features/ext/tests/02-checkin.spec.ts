/**
 * 上课签到的端到端验收。
 *
 * 覆盖一节课的完整流程：老师在教学工具里开一场签到 → 投屏页出二维码与六位口令
 * → 学生扫码签到 → 另一条路径用口令签到 → 重复签被拒 → 老师端名单出现 → 结束
 * → 结束后再签被拒 → 导出 CSV。另外单独验两件事：课程页顶部的入口条，
 * 以及完全没有登录态时扫码 → 登录 → 回跳并自动签到。
 *
 * 投屏上的二维码没法在浏览器里解码，所以当前窗口的 token 与口令用教师身份读
 * `/ext/checkin/sessions/<uuid>/live` 拿——那就是屏幕上显示的同一份东西。
 */
import { mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from '../../../core/fixtures'
import { login } from '../../../core/client'
import { BASE_URL } from '../../../core/instance'
import { ADMIN_STATE, STUDENT_STATE, sharedStudent } from '../../../core/sharedAuth'
import {
  closeAllOpen,
  closeSession,
  courseSlug,
  createSession,
  exportCsv,
  pickCourse,
  rawCheck,
  readLive,
} from '../checkin'

const TOOL_URL = `${BASE_URL}/dash/tools/checkin`

/**
 * QA 截图落到 docs/sysu-sam/QA/checkin/。
 * 交付要求里要有截图，跑一次用例就顺手把它们更新掉，省得手工补。
 */
const SHOTS = join(
  dirname(fileURLToPath(import.meta.url)),
  '../../../../../docs/sysu-sam/QA/checkin',
)

async function shot(page: import('@playwright/test').Page, name: string) {
  mkdirSync(SHOTS, { recursive: true })
  await page.screenshot({ path: join(SHOTS, `${name}.png`) })
}

test.describe('上课签到 — 一节课的完整流程', () => {
  test.describe.configure({ mode: 'serial' })
  test.use({ storageState: ADMIN_STATE })

  let courseUuid = ''
  let sessionUuid = ''

  test.beforeAll(async () => {
    courseUuid = await pickCourse()
    // 同一门课上如果还留着别的开着的会话，学生端入口条会指向那一场
    await closeAllOpen(courseUuid)
  })

  test('老师在教学工具里开一场签到，投屏页出二维码与六位口令', async ({ page }) => {
    await page.goto(TOOL_URL)

    // 课程下拉由骨架的 CourseSelect 渲染在页头里（registry 的 courseScoped），
    // 签到组件自己不再有选择框，所以按 aria-label 定位。
    const courseSelect = page.getByRole('combobox', {
      name: /选择课程|Select a course/i,
    })
    await expect(courseSelect).toBeVisible()
    await expect
      .poll(async () => await courseSelect.inputValue())
      .toMatch(/^course_/)
    await courseSelect.selectOption(courseUuid)

    await page.getByTestId('checkin-title-input').fill('端到端验证课')
    await shot(page, '01-tool-form')
    await page.getByTestId('checkin-start').click()

    await page.waitForURL(/\/dash\/tools\/checkin\/present\//)
    sessionUuid = page.url().split('/present/')[1].split('?')[0]

    await expect(page.getByTestId('checkin-present')).toBeVisible()
    // 二维码是内联 SVG（用仓库已有的 qrcode 依赖渲染），不是 <img>
    await expect(page.locator('[data-testid="checkin-qr"] svg')).toBeVisible()
    const code = (await page.getByTestId('checkin-present-code').innerText()).trim()
    expect(code).toMatch(/^\d{6}$/)
    // 口令与投屏页显示的必须是同一个窗口派生出来的
    const live = await readLive(sessionUuid)
    expect(live.code).toBe(code)
    await shot(page, '02-present')
  })

})

test.describe('上课签到 — 学生视角', () => {
  test.describe.configure({ mode: 'serial' })

  let courseUuid = ''
  let sessionUuid = ''

  test.beforeAll(async () => {
    courseUuid = await pickCourse()
    await closeAllOpen(courseUuid)
    const created = await createSession(courseUuid, '学生视角验证课')
    sessionUuid = created.session_uuid
  })

  test.afterAll(async () => {
    await closeSession(sessionUuid).catch(() => undefined)
  })

  test.describe('扫码与口令两条路径', () => {
    test.use({ storageState: STUDENT_STATE })

    test('扫码路径签到成功', async ({ page }) => {
      const live = await readLive(sessionUuid)
      // 扫码等价于打开二维码里那个带 token 的地址
      await page.goto(`${BASE_URL}/checkin/${sessionUuid}?t=${live.token}`)
      await expect(page.getByTestId('checkin-result-ok')).toBeVisible()
      await expect(page.getByTestId('checkin-result-ok')).toContainText(
        /签到成功|Checked in/i,
      )
      await shot(page, '03-student-qr-ok')
    })

    test('同一个账号再签一次落在「已经签过」', async ({ page }) => {
      await page.goto(`${BASE_URL}/checkin/${sessionUuid}`)
      await expect(page.getByTestId('checkin-result-ok')).toContainText(
        /已经签过|already checked in/i,
      )
      await shot(page, '04-student-duplicate')
    })

    test('老师端名单里出现这个学生，人数不为 0', async () => {
      const live = await readLive(sessionUuid)
      expect(live.checked_count).toBeGreaterThan(0)
      const student = sharedStudent()
      const csv = await exportCsv(sessionUuid)
      expect(csv.hasBom).toBe(true) // 带 BOM，Excel 打开中文不乱码
      expect(csv.text).toContain('课程,场次,姓名,邮箱,签到时间,方式,IP')
      expect(csv.text).toContain(student.email)
      expect(csv.text).toContain('qr')
    })
  })

  test.describe('口令路径与关闭之后', () => {
    test.use({ storageState: ADMIN_STATE })

    test('输口令也能签到（换一个账号走这条路径）', async ({ page }) => {
      const live = await readLive(sessionUuid)
      await page.goto(`${BASE_URL}/checkin/${sessionUuid}`)
      await page.getByTestId('checkin-code-input').fill(live.code)
      await page.getByTestId('checkin-code-submit').click()
      await expect(page.getByTestId('checkin-result-ok')).toBeVisible()
      const after = await readLive(sessionUuid)
      expect(after.checked_count).toBeGreaterThanOrEqual(2)
      await shot(page, '05-student-code-ok')
    })

    test('结束之后任何人再提交都拿 410 session_closed', async () => {
      await closeSession(sessionUuid)
      const student = sharedStudent()
      const bearer = await login(student.email, student.password)
      const res = await rawCheck(sessionUuid, { code: '000000' }, bearer)
      // 状态判定先于「是否已签过」，所以已签过的人再提交也是 410 而不是 409
      expect(res.status).toBe(410)
      expect(res.code).toBe('session_closed')
    })

    test('结束后的投屏页不再显示二维码与口令', async ({ page }) => {
      await page.goto(`${BASE_URL}/dash/tools/checkin/present/${sessionUuid}`)
      await expect(page.getByTestId('checkin-present')).toBeVisible()
      await expect(page.getByTestId('checkin-present-code')).toHaveCount(0)
      await expect(page.locator('[data-testid="checkin-qr"] svg')).toHaveCount(0)
      await shot(page, '06-present-after-close')
    })
  })
})

test.describe('上课签到 — 学生端入口条', () => {
  test.use({ storageState: STUDENT_STATE })

  let courseUuid = ''
  let sessionUuid = ''

  test.beforeAll(async () => {
    // 入口条要在学生打得开的课程页上验，所以挑一门公开且已发布的课
    courseUuid = await pickCourse(true)
    await closeAllOpen(courseUuid)
    const created = await createSession(courseUuid, '入口条验证课')
    sessionUuid = created.session_uuid
  })

  test.afterAll(async () => {
    await closeSession(sessionUuid).catch(() => undefined)
  })

  test('课程页顶部出现「本节课签到」，点进去是这场签到', async ({ page }) => {
    await page.goto(`${BASE_URL}/course/${courseSlug(courseUuid)}`)
    const banner = page.getByTestId('checkin-banner')
    await expect(banner).toBeVisible()
    await expect(banner).toContainText('入口条验证课')

    await shot(page, '07-course-banner')

    await banner.click()
    await page.waitForURL(new RegExp(`/checkin/${sessionUuid}`))
    await expect(page.getByTestId('checkin-form')).toBeVisible()
    await shot(page, '08-student-form')
  })
})

test.describe('上课签到 — 未登录扫码', () => {
  // 干净上下文：这条用例的重点就是「没有任何登录态」
  test.use({ storageState: { cookies: [], origins: [] } })

  let courseUuid = ''
  let sessionUuid = ''

  test.beforeAll(async () => {
    courseUuid = await pickCourse(true)
    await closeAllOpen(courseUuid)
    const created = await createSession(courseUuid, '未登录回跳验证')
    sessionUuid = created.session_uuid
  })

  test.afterAll(async () => {
    await closeSession(sessionUuid).catch(() => undefined)
  })

  test('未登录扫码 → 登录 → 回跳并自动签到', async ({ page }) => {
    const live = await readLive(sessionUuid)
    await page.goto(`${BASE_URL}/checkin/${sessionUuid}?t=${live.token}`)

    const loginLink = page.getByTestId('checkin-login-link')
    await expect(loginLink).toBeVisible()
    await shot(page, '09-anon-login-prompt')
    await loginLink.click()

    // 回跳目标要原样带着 ?t=，否则登录回来还得再扫一次
    await page.waitForURL(/\/login\?next=/)
    expect(decodeURIComponent(page.url())).toContain(`?t=${live.token}`)

    const student = sharedStudent()
    await page.locator('input[type="email"]').first().fill(student.email)
    await page.locator('input[type="password"]').first().fill(student.password)
    await page.locator('button[type="submit"]').first().click()

    await page.waitForURL(new RegExp(`/checkin/${sessionUuid}`))
    // token 跟着回来了，页面自动提交，不用学生再点一次
    await expect(page.getByTestId('checkin-result-ok')).toBeVisible()
    await shot(page, '10-anon-after-login-ok')
  })
})
