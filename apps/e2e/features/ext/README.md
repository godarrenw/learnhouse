# 教学工具（ext）E2E

部署方自建的「教学工具」后台的端到端用例。复用本目录上层已有的 Playwright
基建（`core/auth.ts`、`core/sharedAuth.ts`、`core/fixtures.ts`），不另起一套。

## 跑法

对着一个**已经在跑**的实例跑（本地开发时最常用）：

```sh
cd apps/e2e
bun install
bun run install-browsers          # 首次

E2E_SKIP_BOOT=1 \
E2E_BASE_URL=http://localhost:3001 \
E2E_API_URL=http://localhost:9001/api/v1 \
E2E_ADMIN_EMAIL=user1@example.local \
E2E_ADMIN_PASSWORD='LocalDev#2026' \
bun run test features/ext
```

`E2E_BASE_URL` 指前端 dev（各代理端口自行错开，骨架用 3001），
`E2E_API_URL` 指自己起的后端（骨架用 9001）。不设这两个的话
`global-setup.ts` 会用 LearnHouse CLI 拉线上镜像新装一套，本地开发不需要。

## 角色

- 管理员会话：`ADMIN_STATE`，就是上面的 `E2E_ADMIN_EMAIL`。
- 普通成员会话：`STUDENT_STATE`，由 `global-setup` 建的一个 User 角色账号。
  本地复刻库里 `user2@example.local`（密码同上）是等价的手工账号。
