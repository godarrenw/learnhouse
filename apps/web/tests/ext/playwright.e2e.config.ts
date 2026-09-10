// @ts-nocheck —— @playwright/test 不是本仓库的依赖（见文件头注释），
// 留着类型检查会让 `next build` 挂在 TS2307 上。
/**
 * 只给 ext（教学工具）的端到端用例用。仓库主测试仍是 `bun test tests`，
 * 这份配置靠 `bunx playwright test -c tests/ext/playwright.config.ts` 单独跑。
 */
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  // 文件名用 .e2e.ts 而不是 .spec.ts：bun 的测试发现会把 *.spec.ts 当单测跑，
  // 而 `bun test tests` 里没有 @playwright/test，整个仓库的单测会红。
  testMatch: /\.e2e\.ts$/,
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
