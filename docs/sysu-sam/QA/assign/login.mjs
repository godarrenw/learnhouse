/**
 * 存一份登录态给 shots.mjs 用，省得每次走查都重新登录。
 *
 *   node docs/sysu-sam/QA/assign/login.mjs   （在仓库根目录跑）
 *
 * 账号密码从环境变量读，默认是本地预发栈的管理员。
 */
import { createRequire } from 'node:module'

// 脚本放在 docs/ 下，node 会按脚本所在目录找 node_modules，找不到 playwright。
// 从仓库里唯一装了 playwright 的地方（apps/e2e）解析它。
const require = createRequire(new URL('../../../../apps/e2e/package.json', import.meta.url))
const { chromium } = require('@playwright/test')

const BASE = process.env.BASE || 'http://localhost:3005'
const EMAIL = process.env.LH_EMAIL || 'user1@example.local'
const PASSWORD = process.env.LH_PASSWORD || 'LocalDev#2026'
const STATE = process.env.STATE || './.assign-auth-state.json'

const browser = await chromium.launch()
const context = await browser.newContext()
const page = await context.newPage()

await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(2000)
await page.locator('input[type="email"], input[name="email"]').first().fill(EMAIL)
await page.locator('input[type="password"]').first().fill(PASSWORD)
await page.locator('button[type="submit"]').first().click()
await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 90_000 })
console.log('logged in ->', page.url())

await context.storageState({ path: STATE })
await browser.close()
