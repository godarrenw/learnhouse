/**
 * 只给 ext（教学工具）的端到端用例用。仓库主测试仍是 `bun test tests`，
 * 这份配置靠 `bunx playwright test -c tests/ext/playwright.config.ts` 单独跑。
 */
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    headless: true,
    viewport: { width: 1440, height: 900 },
    ignoreHTTPSErrors: true,
    locale: 'zh-CN',
  },
})
