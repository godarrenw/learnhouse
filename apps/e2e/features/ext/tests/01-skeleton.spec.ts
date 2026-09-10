/**
 * 教学工具骨架的端到端验收。
 *
 * 证明四件事：
 *  1. 教师身份能在后台左侧菜单看到「教学工具」入口
 *  2. 概览页按注册表渲染出工具卡片
 *  3. 示例工具页真的拿到了后端 /ext/health 的数据
 *  4. 普通成员（User 角色）看不到菜单，直接访问 /dash/tools 会被拦
 */
import { expect, test } from '../../../core/fixtures'
import { BASE_URL, ORG_SLUG } from '../../../core/instance'
import { ADMIN_STATE, STUDENT_STATE } from '../../../core/sharedAuth'

const DASH_TOOLS = `${BASE_URL}/dash/tools`

test.describe('教学工具骨架 — 教师视角', () => {
  test.use({ storageState: ADMIN_STATE })

  test('左侧菜单出现「教学工具」入口', async ({ page }) => {
    await page.goto(`${BASE_URL}/dash`)
    const entry = page.getByRole('navigation').getByRole('link', { name: /Teaching Tools|教学工具/ })
    await expect(entry.first()).toBeVisible()
  })

  test('概览页按注册表渲染工具卡片', async ({ page }) => {
    await page.goto(DASH_TOOLS)
    await expect(page.getByTestId('sysu-tools-grid')).toBeVisible()
    // 骨架自带的示例工具必须在，其他代理加的工具会让卡片变多，所以只断言下界。
    await expect(page.getByTestId('sysu-tool-card-example')).toBeVisible()
    const cards = page.locator('[data-testid^="sysu-tool-card-"]')
    expect(await cards.count()).toBeGreaterThanOrEqual(1)
  })

  test('示例工具页拿到 /ext/health 的数据', async ({ page }) => {
    await page.goto(`${BASE_URL}/dash/tools/example`)

    const health = page.getByTestId('sysu-ext-health')
    await expect(health).toBeVisible()
    await expect(page.getByTestId('sysu-ext-error')).toHaveCount(0)

    // 后端回的 status 是 "ok"，工具列表里至少有 health。
    await expect(health).toContainText('ok')
    await expect(health).toContainText('health')
    // 组织内角色回显 —— 证明这条数据确实过了 require_teacher 那道门。
    await expect(health).toContainText(/Admin|Maintainer|Instructor|Superadmin/i)
  })

  test('未知工具返回 404', async ({ page }) => {
    const res = await page.goto(`${BASE_URL}/dash/tools/no-such-tool`)
    // Next 的 notFound() 在客户端触发时状态码仍是 200，所以断言页面内容。
    expect(res).not.toBeNull()
    await expect(page.getByTestId('sysu-tools-grid')).toHaveCount(0)
    await expect(page.locator('body')).toContainText(/404|not found|页面不存在/i)
  })
})

test.describe('教学工具骨架 — 普通成员视角', () => {
  test.use({ storageState: STUDENT_STATE })

  test('学生端顶栏没有「教学工具」入口', async ({ page }) => {
    await page.goto(`${BASE_URL}/org/${ORG_SLUG}`.replace('/org/', '/'))
    await expect(
      page.getByRole('link', { name: /Teaching Tools|教学工具/ })
    ).toHaveCount(0)
  })

  test('直接访问 /dash/tools 被拦', async ({ page }) => {
    await page.goto(DASH_TOOLS)
    // 上游的 AdminAuthorization（page 模式）渲染 403 错误页，不做重定向。
    await expect(page.getByTestId('sysu-tools-grid')).toHaveCount(0)
    await expect(page.locator('body')).toContainText(
      /don't have access|permission|没有权限/i
    )
  })
})
