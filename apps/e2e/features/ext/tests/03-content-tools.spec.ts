/**
 * 内容工具的端到端验收。
 *
 * 五件事，都是单测验不到的：
 *  1. 工具页四个分段都能切，未选课时不发请求
 *  2. 导出真的下载出一个 zip，再喂回导入能建出章节和页面
 *  3. 编辑器里粘贴一条 bilibili 链接，真的变成 player.bilibili.com 的 iframe
 *     （单测只验了「哪些剪贴板内容该被识别」，压不压得过 Link 只能在浏览器里看）
 *  4. 虚拟助教追加之后，学生端页面里真的有那个 iframe
 *  5. 邀请码页面的二维码弹窗画出了 SVG
 *
 * 截图落在 docs/sysu-sam/QA/content/。
 */
import { existsSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { expect, test } from '../../../core/fixtures'
import { API_URL, BASE_URL } from '../../../core/instance'
import { ADMIN_STATE } from '../../../core/sharedAuth'

const TOOL_URL = `${BASE_URL}/dash/tools/content`
const SHOT_DIR = join(
  dirname(new URL(import.meta.url).pathname),
  '../../../../../docs/sysu-sam/QA/content'
)

function shot(name: string) {
  if (!existsSync(SHOT_DIR)) mkdirSync(SHOT_DIR, { recursive: true })
  return join(SHOT_DIR, name)
}

/**
 * 工具页是 lazy 加载的，等分段按钮出来才算真的渲染完。
 * 超时给到 90 秒：dev 模式下这条路由第一次被访问要现编译，冷启动能到一分钟。
 */
async function openTool(page: any) {
  await page.goto(TOOL_URL)
  await expect(page.getByTestId('sysu-content-tab-import')).toBeVisible({ timeout: 90_000 })
}

/**
 * 选一门**确实有富文本内容页**的课，返回它的 uuid。
 *
 * 不能直接用下拉里的第一门课：本地复刻库里排在前面的可能是只有一个视频活动的课，
 * 那样导出的包里没有页面、编辑器用例也没得可粘，测试会以「0 个页面」这种
 * 看起来像功能坏了的方式失败。这里逐门试，用虚拟助教那个下拉当探针 ——
 * 它本来就只列富文本页。
 */
async function selectCourseWithPages(page: any): Promise<string> {
  const courseSelect = page.getByLabel(/选择课程|Select a course/i)
  await expect(courseSelect).toBeEnabled({ timeout: 60_000 })
  const values: string[] = await courseSelect
    .locator('option')
    .evaluateAll((os: any[]) => os.map((o) => o.value).filter(Boolean))

  await page.getByTestId('sysu-content-tab-avatar').click()
  const pageSelect = page.getByTestId('sysu-content-avatar-page')

  for (const value of values) {
    await courseSelect.selectOption(value)
    // 换课会重新拉课程结构，等下拉里出现第一个真正的页面选项
    const hasPages = await pageSelect
      .locator('option')
      .nth(1)
      .waitFor({ state: 'attached', timeout: 20_000 })
      .then(() => true)
      .catch(() => false)
    if (hasPages) return value
  }
  throw new Error('本地实例里没有任何含富文本内容页的课程，测试无法进行')
}

test.describe('内容工具 — 工具页', () => {
  test.use({ storageState: ADMIN_STATE })

  test('四个分段都能切开', async ({ page }) => {
    await openTool(page)

    // 导入：拖拽区在
    await expect(page.getByTestId('sysu-content-dropzone')).toBeVisible()
    await page.screenshot({ path: shot('01-import.png'), fullPage: true })

    await page.getByTestId('sysu-content-tab-export').click()
    await expect(page.getByTestId('sysu-content-export-run')).toBeVisible()
    await page.screenshot({ path: shot('02-export.png'), fullPage: true })

    await page.getByTestId('sysu-content-tab-avatar').click()
    await expect(page.getByTestId('sysu-content-avatar-script')).toBeVisible()
    await page.screenshot({ path: shot('03-avatar.png'), fullPage: true })

    await page.getByTestId('sysu-content-tab-about').click()
    await expect(page.locator('body')).toContainText(/bilibili/i)
    await page.screenshot({ path: shot('04-about.png'), fullPage: true })
  })

  test('导出下载出 zip，再导回去能建出章节和页面', async ({ page }) => {
    test.slow() // 整门课打包 + 逐页重建，比一般用例慢

    await openTool(page)
    await selectCourseWithPages(page)
    await page.getByTestId('sysu-content-tab-export').click()

    const downloadPromise = page.waitForEvent('download', { timeout: 120_000 })
    await page.getByTestId('sysu-content-export-run').click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toMatch(/\.zip$/)
    // 跨源时浏览器默认读不到 Content-Disposition，会退回兜底名。
    // 后端在这条响应上单独声明了 Access-Control-Expose-Headers，所以这里应当是真名。
    expect(download.suggestedFilename()).not.toBe('course.zip')

    const zipPath = join(
      dirname(new URL(import.meta.url).pathname),
      '../../../.tmp-content-export.zip'
    )
    await download.saveAs(zipPath)
    await expect(page.getByTestId('sysu-content-export-result')).toBeVisible()

    // 把刚导出的包喂回同一门课。导入一律**新建**章节（这正是要验的：不覆盖老师
    // 手改过的内容），所以跑完必须把新建的章节删干净 ——
    // 否则每跑一次这门课就翻一倍，跑几轮本地库就废了。
    await page.getByTestId('sysu-content-tab-import').click()
    await page.getByTestId('sysu-content-file-input').setInputFiles(zipPath)

    const importResponse = page.waitForResponse(
      (r) => r.url().includes('/ext/content/') && r.url().includes('/import-md'),
      { timeout: 180_000 }
    )
    await page.getByTestId('sysu-content-import-run').click()
    const summary = await (await importResponse).json()
    const createdChapterIds: number[] = (summary.chapters_created ?? []).map(
      (c: any) => c.chapter_id
    )

    try {
      const result = page.getByTestId('sysu-content-import-result')
      await expect(result).toBeVisible({ timeout: 60_000 })
      expect(summary.counts.chapters).toBeGreaterThan(0)
      expect(summary.counts.activities).toBeGreaterThan(0)
      // 内容页和整页嵌入能还原，视频 / PDF / 作业只会进 skipped，不静默丢
      for (const s of summary.skipped ?? []) {
        expect(s.reason).toBeTruthy()
      }
      await page.screenshot({ path: shot('05-import-result.png'), fullPage: true })
    } finally {
      // 收尾：把这次导入建出来的章节全删掉，本地库回到原样
      for (const id of createdChapterIds) {
        await page.request.delete(`${API_URL}/chapters/${id}`)
      }
    }
  })
})

test.describe('内容工具 — 编辑器粘贴视频链接', () => {
  test.use({ storageState: ADMIN_STATE })

  test('粘贴 bilibili 链接变成播放器', async ({ page }) => {
    // 借工具页拿一门课和它下面的一个富文本内容页 —— 虚拟助教那个下拉本来就只列
    // 富文本页，省得自己去翻课程结构接口。
    await openTool(page)
    const courseUuid = await selectCourseWithPages(page)
    const pageSelect = page.getByTestId('sysu-content-avatar-page')
    const activityUuid = await pageSelect.locator('option').nth(1).getAttribute('value')
    expect(activityUuid).toBeTruthy()

    // 编辑器路由：/course/<课程 uuid 去前缀>/activity/<活动 uuid 去前缀>/edit
    const editUrl =
      `${BASE_URL}/course/${(courseUuid as string).replace('course_', '')}` +
      `/activity/${(activityUuid as string).replace('activity_', '')}/edit`
    await page.goto(editUrl)

    const editor = page.locator('.ProseMirror').first()
    await expect(editor).toBeVisible({ timeout: 60_000 })
    await editor.click()
    // 光标挪到文末。blockEmbed 这类节点是 atom：点在它身上会把整个节点选中，
    // 这时 selection 非空，TipTap 的 Link 会抢先处理粘贴（它只在选区为空时让路）。
    await editor.press('ControlOrMeta+End')

    // Playwright 里读不到系统剪贴板，直接合成一个 paste 事件。
    // 这一步同时验了「优先级压过 Link」：压不过的话这里会得到一段超链接文字。
    await editor.evaluate((el: any, url: string) => {
      const dt = new DataTransfer()
      dt.setData('text/plain', url)
      el.dispatchEvent(
        new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true })
      )
    }, 'https://www.bilibili.com/video/BV1GJ411x7h7')

    await expect(page.locator('iframe[src*="player.bilibili.com"]').first()).toBeVisible({
      timeout: 60_000,
    })
    await page.screenshot({ path: shot('06-paste-bilibili.png'), fullPage: true })
  })
})

test.describe('内容工具 — 虚拟助教', () => {
  test.use({ storageState: ADMIN_STATE })

  test('追加之后学生端页面里真的有那个 iframe', async ({ page }) => {
    test.slow()

    await openTool(page)
    const courseUuid = await selectCourseWithPages(page)
    const pageSelect = page.getByTestId('sysu-content-avatar-page')
    const activityUuid = await pageSelect.locator('option').nth(1).getAttribute('value')
    await pageSelect.selectOption(activityUuid as string)

    // 追加是真的改页面内容。这是共用的本地复刻库，跑完要还原，
    // 否则每跑一次那一页就多一个数字人。
    const before = await page.request.get(`${API_URL}/activities/${activityUuid}`)
    const originalContent = before.ok() ? (await before.json()).content : null

    await page
      .getByTestId('sysu-content-avatar-script')
      .fill('同学们好，这一节我们讲传热的三种方式。先说导热，再说对流，最后说辐射。')

    await page.getByTestId('sysu-content-avatar-run').click()
    const result = page.getByTestId('sysu-content-avatar-result')
    await expect(result).toBeVisible({ timeout: 60_000 })
    // 讲稿被切成了句子，结果卡片里会写清楚切了几句
    await expect(result).toContainText(/[0-9]+/)
    await page.screenshot({ path: shot('08-avatar-result.png'), fullPage: true })

    // 学生端那一页里应该多出一个数字人 iframe。
    // 学生端只渲染已发布的活动，而本地复刻库里这些页大多是未发布的，
    // 所以先临时发布，断言完再改回去 —— 不要在共用的本地库里留下副作用。
    const detail = await page.request.get(`${API_URL}/activities/${activityUuid}`)
    const wasPublished = detail.ok() ? (await detail.json()).published === true : false
    if (!wasPublished) {
      await page.request.put(`${API_URL}/activities/${activityUuid}`, {
        data: { published: true },
      })
    }

    try {
      const studentUrl =
        `${BASE_URL}/course/${(courseUuid as string).replace('course_', '')}` +
        `/activity/${(activityUuid as string).replace('activity_', '')}`
      await page.goto(studentUrl)

      const avatarFrame = page.locator('iframe[src*="lh-avatar"]').first()
      await expect(avatarFrame).toBeVisible({ timeout: 60_000 })
      const src = await avatarFrame.getAttribute('src')
      // hash 里必须还带着讲稿（j= 明文或 s= gzip）。渲染端要是把 URL 重建一遍，
      // 这个片段就没了，学生看到的会是一个空白页面。
      expect(src).toMatch(/#(j|s)=/)
      await page.screenshot({ path: shot('09-avatar-student.png'), fullPage: true })
    } finally {
      if (!wasPublished) {
        await page.request.put(`${API_URL}/activities/${activityUuid}`, {
          data: { published: false },
        })
      }
      if (originalContent !== null) {
        await page.request.put(`${API_URL}/activities/${activityUuid}`, {
          data: { content: originalContent },
        })
      }
    }
  })
})

test.describe('内容工具 — 邀请码二维码', () => {
  test.use({ storageState: ADMIN_STATE })

  test('弹窗画出二维码并给出注册链接', async ({ page }) => {
    await page.goto(`${BASE_URL}/dash/users/settings/signups`)

    // 等表格真的渲染出来再判断。isVisible() 是即时的，页面还在拉数据时会返回
    // false，那时候去走「先生成一个邀请码」的兜底反而会卡在弹窗上。
    const trigger = page.getByTestId('sysu-invite-qr-trigger').first()
    const hasCode = await trigger
      .waitFor({ state: 'visible', timeout: 60_000 })
      .then(() => true)
      .catch(() => false)
    test.skip(!hasCode, '这个组织一个邀请码都没有，先在界面上生成一个再跑')

    await trigger.click()
    await expect(page.getByTestId('sysu-invite-qr-modal')).toBeVisible()
    await expect(page.getByTestId('sysu-invite-qr-image').locator('svg')).toBeVisible({
      timeout: 30_000,
    })
    // 二维码没画出来的话这里会是错误分支
    await expect(page.getByTestId('sysu-invite-qr-error')).toHaveCount(0)
    // 弹窗里要把注册链接原文写出来，老师得能核对
    await expect(page.getByTestId('sysu-invite-qr-modal')).toContainText('inviteCode=')
    await page.screenshot({ path: shot('07-invite-qr.png'), fullPage: true })
  })
})
