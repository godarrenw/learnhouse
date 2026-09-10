# 生产补丁 → 源码提交 映射表

线上（NAS `/volume1/docker/learnhouse/patches/`）原本用 bind-mount 把改过的文件覆盖进
上游镜像 `ghcr.io/learnhouse/app:1.3.6`。本分支把每一条都还原成了源码改动，一条一个 commit，
基于 tag `1.3.6`（commit `01c64586`）。

列出全部移植提交：

```sh
git log --oneline 1.3.6..sysu-sam
```

## 映射表

| # | 生产补丁文件 | 日期 | 源码路径 | commit | 还原方式 |
|---|---|---|---|---|---|
| 1 | `patches/generator.py` | 2026-09-08 | `apps/api/src/services/ai/image/generator.py` | `8e3fddfb` | 直接对应，逐字节 |
| 2 | `patches/courseplanning.py` | 2026-09-08 | `apps/api/src/services/ai/courseplanning.py` | `bec96339` | 直接对应，逐字节 |
| 3 | `patches/magic_login.py` | 2026-09-08 | `apps/api/src/services/auth/magic_login.py` | `ef5a9c68` | 直接对应，逐字节 |
| 4 | `patches/web/zh.json` + `patches/web/zh.chunk.js` | 2026-09-08 | `apps/web/locales/zh.json` | `9611cf90` | 改源文件，chunk 由构建重新产出 |
| 5 | `patches/web/assign.chunk.js` | 2026-09-10 | `apps/web/app/orgs/[orgslug]/dash/assignments/_components/NewAssignmentModal.tsx` | `830ca231` | 从编译产物反推源码，等价 |

**没有一条补丁无法还原。**

### 还原的可信度

第 1–3 条：`patches/*.py.orig` 与 `git show 1.3.6:<对应路径>` 逐字节相同，所以直接
`cp patches/X.py` 到源码路径就是精确移植，没有任何转录风险。只改了文件头「原始文件保存在
同目录下的 X.py.orig」那一句 —— 在仓库里 `.orig` 不存在，改成指向 `git show 1.3.6:<路径>`。

第 4 条：`zh.chunk.js` 是 `zh.json` 的编译产物（`lib/i18n.ts` 用
`import('../locales/zh.json')` 动态加载，语言包被单独打成一个纯 `JSON.parse('...')` 的
chunk）。改源文件即可，chunk 由构建自动产出。`diff` 上游 `zh.json` 与补丁版只有 8 处差异，
全部是学生可见的品牌文案。

第 5 条：编译产物里唯一的改动是一处调用参数
`getCourse(f, …)` → `getCourse("course_"+f+"/meta?slim=true", …)`。源码侧改为调用同仓库
已有的 `getCourseMetadata(uuid, null, token, { slim: true })`，它拼出的 URL 正是
`courses/course_{uuid}/meta?slim=true`，与线上补丁的请求完全一致 —— 换成这个 helper 而不是
硬拼字符串，是因为源码里本来就有它，硬拼反而是编译产物的痕迹。

## 升级时哪些可以删

| # | 上游状态 | 升级后怎么办 |
|---|---|---|
| 1 生图 | 上游仍是 Google-only（`dev` 分支未改） | **保留**。除非上游把生图接进 provider 抽象层 |
| 2 语言码 | 上游 `dev` 仍是 `language_names.get(code, "English")` | **保留**，可考虑给上游提 PR |
| 3 登录邮件 | 上游 `dev` 的 `f0bc5f85` 已从根上解决 | **升级到含该提交的版本后删掉**，见下 |
| 4 语言包 | 上游 `dev` 的 `f0bc5f85` 顺带 de-brand 了 20 个语言包 | 升级后重新 diff，多半只剩「先进智造学堂」这个名字要留，其余可删 |
| 5 作业弹窗 | 上游 `dev` 仍未修 | **保留**，应该给上游提 PR |

关于第 3 条：上游 `f0bc5f85 feat(emails): white-label org-scoped system emails` 引入了
`branding.py` 作为组织名/语言/发件人/Logo/主题色的统一解析器，把所有 org 级发信点都接了上去，
并为 magic_login 补齐了 20 个语言包的翻译。

```
apps/api/src/routers/auth.py                       |  23 +-
apps/api/src/services/auth/magic_login.py          |  49 +-
apps/api/src/services/email/branding.py            | 170 +++++
apps/api/src/services/email/translations.py        | 360 ++++++++----
apps/api/src/services/email/utils.py               |  39 +
apps/api/src/services/nudges/eligibility.py        |  21 +
apps/api/src/services/nudges/runner.py             |  20 +-
apps/api/src/services/nudges/snapshot.py           |   6 +
apps/api/src/services/orgs/invites.py              |  13 +-
apps/api/src/services/orgs/join_notifications.py   |  11 +-
apps/api/src/services/orgs/users.py                |  11 +-
apps/api/src/services/users/email_verification.py  |  14 +-
apps/api/src/services/users/emails.py              | 180 ++++-
```

13 个文件、含新增模块和 nudges / invites 等多处改动，**cherry-pick 到 1.3.6 风险太高**，
所以本次仍按移植补丁处理。等升级到包含它的上游版本，删掉 commit `ef5a9c68` 的改动，
改为在组织设置里配置品牌信息即可。

## 补丁生效的验证方法

镜像建好后，三条都要有输出才算前后端补丁都进去了：

```sh
docker run --rm --entrypoint sh <镜像> -c "
  grep -c 'PATCH(nas)'        /app/api/src/services/ai/courseplanning.py
  grep -c 'images/generations' /app/api/src/services/ai/image/generator.py
  grep -c '登录先进智造学堂'    /app/api/src/services/auth/magic_login.py
  grep -rl '先进智造学堂' /app/web/.next/static/chunks/ | head -3
  grep -rl assignment-course-structure /app/web/.next/static/chunks/ | xargs grep -l getCourseMetadata
"
```

第 5 条别去 grep `meta?slim=true`：`getCourseMetadata` 是用 `URLSearchParams` 在运行时拼
query string 的，编译产物里只有 `course_${e}/meta` 和单独的 `slim`，那个字面量永远搜不到。
要确认得更死一点，就把含 `assignment-course-structure` 的 chunk 拷出来看这一段：

```js
queryKey:["assignment-course-structure",f],
queryFn:()=>(0,o.getCourseMetadata)(f,null,g,{slim:!0})
```

2026-09-10 在本地 arm64 镜像上实测：5 条全部命中，`/app/api/ee` 已被
`LEARNHOUSE_PUBLIC=true` 剔除。

## AGPL-3.0 合规

原来 `patches/README.md` 承担 AGPL 第 5(a) 条的「修改说明」和第 13 条的「向使用者提供
修改后源码」。切到自建镜像后，这个义务由本仓库履行：`godarrenw/learnhouse` 的 `sysu-sam`
分支就是修改后的完整源码，每条改动一个 commit，附原因和日期。平台页脚的源码获取指引
应指向本仓库。三个 `.py` 文件头部保留了单独的修改声明。
