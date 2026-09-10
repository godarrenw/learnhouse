# 先进智造学堂 · 开发指南

本仓库是 [LearnHouse](https://github.com/learnhouse/learnhouse)（AGPL-3.0）的 fork，
主线分支 `sysu-sam` 基于上游 tag `1.3.6`（线上跑的版本），在其上叠加部署方的改动。

- `origin` = `godarrenw/learnhouse`（本 fork，默认分支已设为 `sysu-sam`）
- `upstream` = `learnhouse/learnhouse`（上游）

## 目录里的东西在哪

| 路径 | 是什么 |
|---|---|
| `apps/web` | Next.js 前端，bun 1.4.0 |
| `apps/api` | FastAPI 后端，Python 3.14.7，uv 管依赖 |
| `apps/collab` | 白板协作 WebSocket 服务 |
| `Dockerfile` | 根目录这个把三者打成一个镜像，就是线上跑的那个 |
| `deploy/` | 生产部署配置，见 `deploy/README.md` |
| `docs/sysu-sam/` | 部署方自己的文档（本文件、`PATCHES.md`） |

## 本地开发

### 后端

```sh
cd apps/api
uv sync
# 需要一个 Postgres(pgvector) 和 Redis。最省事的办法是直接用本地复刻栈里的：
#   /Volumes/D/code/learnhouse-local  （docker compose up -d db redis）
# 然后把连接串写进 apps/api/.env
uv run uvicorn app:app --reload --port 9000
```

`requires-python` 钉死在 `>=3.14.7,<3.14.8`，别用别的小版本，`uv sync` 会直接拒绝。

### 跑后端测试

```sh
cd apps/api
uv run pytest src/tests/ext -q          # 教学工具那部分
uv run ruff check src/routers/ext src/services/ext src/tests/ext
```

**用 `uv run` 而不是直接调 venv 里的 pytest**：`uv run` 会先把环境同步到
`uv.lock` 再执行，本地手动 `pip install` 进去的东西会被它清掉，所以拿它跑到的
结果和 CI 一致。

一个踩过的坑：SQLAlchemy 的 async 引擎运行时必须要 `greenlet`，而它一度没被
装上（marker 在 Apple Silicon 的 macOS 上把它跳过了），症状是所有碰数据库的
测试都报 `ValueError: the greenlet library is required`，而纯逻辑测试全过 ——
看起来像"某几个测试写坏了"。现在 `greenlet` 已经显式钉进 `apps/api/pyproject.toml`
的依赖，`uv sync` 一次就有，不用再手动补装，也**不要**再用
`uv run --no-sync` 绕过同步。

### 前端

```sh
cd apps/web
bun install --frozen-lockfile
bun run dev            # next dev --turbopack，默认 3000 端口
```

`.env.local` 里至少要有（指向上一步的本地后端）：

```
NEXT_PUBLIC_LEARNHOUSE_API_URL=http://localhost:9000/api/v1/
NEXT_PUBLIC_LEARNHOUSE_BACKEND_URL=http://localhost:9000/
NEXT_PUBLIC_LEARNHOUSE_DOMAIN=localhost
NEXT_PUBLIC_LEARNHOUSE_MULTI_ORG=False
NEXT_PUBLIC_LEARNHOUSE_DEFAULT_ORG=default
NEXT_PUBLIC_LEARNHOUSE_HTTPS=False
```

键名全集见 `deploy/.env.example`。

### 想要一份「和线上一样」的环境

`/Volumes/D/code/learnhouse-local` 是生产的本地复刻（同 tag 镜像、同结构 compose、
从生产备份恢复并脱敏的数据），端口 18088。前端连它调试比连真生产安全得多。
**任何时候都不要拿本地代码直接连生产库。**

## 分支策略

```
1.3.6 (upstream tag)
  └── sysu-sam            ← 主线，线上镜像从这里构建
        ├── feat/xxx      ← 功能分支，PR 合回 sysu-sam
        └── fix/xxx
```

- `sysu-sam` 是主线，也是本 fork 的默认分支。push 到它就会触发镜像构建。
- 新功能开 `feat/xxx` 分支，PR 合入 `sysu-sam`。PR 不会触发镜像构建
  （`build-image.yml` 只认 push），合入后才建。
- 上游的 workflow 大多过滤了 `dev` / `main` / `prod` 分支（api-lint、api-tests、web-lint、
  lockfiles、build-community、release、notify-infra），在 `sysu-sam` 上不会跑。
  两个例外已在本 fork 上 `gh workflow disable` 掉：
  - `cli-tests.yaml` 的 push 触发器只有 paths 过滤、**没有分支过滤**，会在本分支上乱跑
  - `e2e.yaml` 是 `schedule: 0 3 * * *`，定时任务只跑默认分支，而本 fork 的默认分支
    就是 `sysu-sam`，缺 secrets 必失败还发邮件

  `gh workflow list -R godarrenw/learnhouse --all` 能看到当前状态。
- 要给上游提 PR，从 `1.3.6` 或 `upstream/dev` 另开干净分支，**不要**从 `sysu-sam` 开 ——
  那上面全是部署方的私有改动。第 2 条和第 5 条补丁是上游真 bug，值得回馈。

## 镜像构建

`.github/workflows/build-image.yml`：push 到 `sysu-sam` 或打 `sysu-v*` tag 时，
构建 **linux/amd64**（NAS 是 x86_64）推到 `ghcr.io/godarrenw/learnhouse`，
tag 为「分支名/标签名」与「分支名-sha7」两个。

```sh
gh run list -R godarrenw/learnhouse --limit 5
gh run watch -R godarrenw/learnhouse <run-id>
```

本地想建同样的镜像（Mac 上建 arm64 原生最快，只能自己跑不能上 NAS）：

```sh
docker build --build-arg LEARNHOUSE_PUBLIC=true -t learnhouse-sysu-sam:local .
```

`LEARNHOUSE_PUBLIC=true` 会 `rm -rf /app/api/ee`（Dockerfile 第 97 行），
与上游 release 构建一致，线上的 1.3.6 就是这么建的。

## 跟上游升级

**不要用官方 `learnhouse update` 命令**，它会把 `content` 迁到 named volume，
破坏本部署的 bind-mount。手工走这套：

```sh
git fetch upstream --tags
git log --oneline 1.3.6..<新 tag>        # 先看上游改了什么
git rebase <新 tag> sysu-sam             # 把部署方的 commit 挪到新 tag 上
```

rebase 中每条补丁冲突了都是信号：说明上游动了同一块代码，先去看它是不是已经修了同一个问题。
对照 `docs/sysu-sam/PATCHES.md` 的「升级时哪些可以删」一栏 —— 上游修了就 `git rebase --skip`
把补丁丢掉，别继续覆盖。

然后：

1. push 到 `sysu-sam`，等 Actions 出新镜像
2. 在本地复刻栈（`learnhouse-local`）里换成新镜像跑一遍，至少验证：登录、课程列表、
   课程内容页、新建作业弹窗能列出章节、AI 生图和 AI 课程规划出中文
3. `PATCHES.md` 的验证命令跑一遍，确认补丁都进了镜像
4. 按 `deploy/README.md` 的步骤部署到 NAS（先 `backup.sh`）

## 新功能放哪

原则：**部署方的代码与上游代码物理隔离**，这样 rebase 时冲突面最小。

### 前端新页面

后台菜单「教学工具」对应 `apps/web/app/orgs/[orgslug]/dash/` 下一个**独立目录**，
与 `courses` / `assignments` / `users` 这些上游目录平级。例如：

```
apps/web/app/orgs/[orgslug]/dash/teaching-tools/
  page.tsx
  _components/...
```

菜单项要加进 `dash` 的布局组件（`ClientAdminLayout.tsx` 一带）—— 这一处会与上游冲突，
是可以接受的最小侵入面，改动尽量压成一行。

### 后端新路由

新模块放 `apps/api/src/routers/ext/`（这个目录是部署方新建的，上游没有），
在 `apps/api/src/router.py` 里加两行挂上去：

```python
from src.routers.ext import teaching_tools as ext_teaching_tools   # import 区

v1_router.include_router(                                          # 注册区
    ext_teaching_tools.router, prefix="/ext/teaching-tools", tags=["ext"]
)
```

`router.py` 是这个仓库里唯一挂载路由的地方（`v1_router.include_router(...)`），
所有上游路由也都在这里注册。把部署方的两行加在文件**最末尾**，
rebase 时冲突最容易解。

API 路径统一带 `/ext/` 前缀，一眼能看出不是上游的接口。

数据库表如果要新增，走 alembic（`apps/api/migrations/`），revision 消息里带 `[sysu-sam]`
前缀，升级时好辨认哪些迁移是自己的。
