# 高鹏 9/18「网站显示咋出问题了」+ IDSR Course 命名排查

调查日期 2026-09-21。全程只读：没有登录网站，没有提交表单，没有改代码，没有发飞书消息。
证据图在 `gaopeng-0918/` 目录。

## 结论

1. **问题已复现，根因确定。** 后台「用户 → 用户」表格（`/dash/users/settings/users`）的「群组」列里，
   用户组徽章 `智能决策与系统可靠性工程` 被逐字竖排。原因是徽章没设 `whitespace-nowrap`，
   而中文在任意两个字之间都允许换行。于是浏览器认为这一列最窄可以压到一个字宽，
   窗口一窄，它就先挤这一列，不会让表格出现横向滚动条。这个 bug 来自上游 LearnHouse 代码，不是我们的补丁引入的。
   线上现在跑的就是这份代码，至今没修。
2. **错名是封面图上的英文错字，文字字段里没有。** 冯老师 9/18 14:57 圈出的是课程卡片封面图
   （AI 生成）上的 `RELAIBILITY IMILIGENT`，正确写法应为 RELIABILITY / INTELLIGENT。
   老师的要求是「有错别字，直接一点，就 "IDSR Course"」。
   仓库、learnhouse-teaching 技能、网站匿名可见页面里都**没有**这个错误写法。它只存在于线上课程的封面图文件里。

## 任务一：高鹏反馈的显示问题

### 消息上下文（lark-brain，与高鹏的单聊 `oc_3ee81f93…`）

| 时间 | 谁 | 内容 |
|---|---|---|
| 09-15 19:30 | 高鹏 | 「师兄，网站的用户审批在哪里啊」+ 截图（截图含学生姓名与邮箱，不入库） |
| 09-15 19:30–31 | 朱奕樟 | 现在没有审批功能，只能通过邀请码注册，注册后进入对应分组、看到对应的课 |
| 09-15 19:33 | 高鹏 | 「我靠，确实，那就是我发出去半天居然没有一个人注册」 |
| 09-18 11:43 | 高鹏 | 「师兄，网站显示咋出问题了」+ 截图（截图含学生姓名与邮箱，不入库） |
| 09-18 14:25 | 朱奕樟 | 「我查不到了诶，因为我现在系统被更新了，看不到了」 |
| 09-18 14:26 | 朱奕樟 | 「它没想到我们的群组会这么长吧，一般群组就一两个英文单词」 |

之后没有人再跟进，也没有相关提交。`git log 831f7095..HEAD -- apps/web` 只有一个文档提交，
所以线上镜像 `sysu-sam-831f709` 里这个文件和当前源码一致。

「用户审批」那条不是 bug：`signup_mode` 是 `inviteOnly`（匿名 GET `/api/v1/orgs/slug/default` 可以确认），
本来就没有审批流程，当时已经当面回答过。

### 截图说明了什么

- **页面**：管理后台 → 用户 → 用户（活跃用户表），登录身份是高鹏（Admin）。
- **设备**：桌面浏览器，不是手机。两张图都是桌面布局，有完整的标签栏和筛选行。
  9/15 那张窗口较宽（有左侧栏、8 位用户），徽章在一行里显示正常。
  9/18 那张（14 位用户）明显更窄或缩放更大，除了徽章被逐字竖排，操作列的「分析」「从组织中移除」
  也折成了两三行，说明整张表的可用宽度被压缩了。
- 用户数从 8 增加到 14，新增的学生都在这个长名字的组里，所以受影响的行变多了，问题更显眼。

### 复现

- `https://learn.sysu-sam.com` 从本机可以访问（HTTP 200）；备用地址 `http://172.25.5.162:8088` 访问不到（超时）。
- 出问题的页面需要管理员登录，按要求不能登录，所以**没有在线上直接复现**。
  用 Playwright 只读打开了首页，未登录状态只显示「登录以查看你的课程」。
- **本地复现成功**：本地 repro 页（含真实用户数据，不入库）用和 `OrgUsers.tsx` 相同的表格结构和样式
  （`table w-full` 放在 `overflow-x-auto` 里，徽章是 `inline-flex`，不设 nowrap）。
  - 视口 780px：徽章逐字竖排，和高鹏的截图一致（截图不入库）。
  - 视口 1000px：徽章折成三行（截图不入库）。
  - 同一结构只给徽章加上 `white-space:nowrap`（B 表）：徽章保持一行，表格改为横向滚动。

### 根因（代码位置）

`apps/web/components/Dashboard/Pages/Users/OrgUsers/OrgUsers.tsx`

- L442 `<div className="overflow-x-auto relative">`，L510 `<table className="w-full">`：
  表格在自动布局下会先压缩各列，压到最小内容宽度为止。只有压不下去时，外层的 `overflow-x-auto` 才会生效。
- L608–617 群组单元格：
  ```tsx
  <div className="flex items-center gap-1.5 flex-wrap">
    <span className="inline-flex items-center gap-1 text-xs bg-blue-50 text-blue-600 px-2 py-1 rounded-md font-medium" ...>
  ```
  没有 `whitespace-nowrap`，所以中文组名的最小内容宽度只有一个字，这一列最先被挤窄。
- L742–743 操作列 `inline-flex items-center gap-1.5` 同样没有 nowrap，
  这就是截图里「分析」「从组织中移除」折行的原因。

### 修复建议（没有改代码）

都只改 `OrgUsers.tsx` 一个文件：

1. L612 徽章 class 加 `whitespace-nowrap`。如果不希望特别长的组名把表格撑得太宽，可以再加
   `max-w-[16rem] truncate`（`title` 属性已经设了，但目前放的是 `group.description`，
   建议改成 `group.description || group.name`，这样截断后鼠标悬停能看到全名）。
2. L743 操作按钮容器加 `whitespace-nowrap`；L742 的 `<td>` 也可以加 `whitespace-nowrap`。
3. 可选：L510 改成 `<table className="w-full min-w-[960px]">`。窄屏时直接横向滚动，不再压缩各列。

改完需要重新构建镜像并部署，才能在线上生效。另外，把用户组改成更短的名字（比如 `IDSR Course`，
见任务二）也能让现象消失，但这只是绕过问题，代码的缺陷还在。
同类的徽章还出现在 `OrgUserGroups.tsx:170`、`EditCourseAccess.tsx:331`、`OrgAccess.tsx:235`，
这次没有逐个验证。修的时候建议顺便检查。

## 任务二：统一为 "IDSR Course"

### 老师原话与错误写法（lark-brain，「2026秋季学期课程教学群」`oc_5a6d1b5f…`）

- 09-18 14:57 冯建设发了一张图片（`03-feng-0918-cover-typo.jpg`）：课程卡片，
  标题是「智能决策与系统可靠性工程」，副标题是「面向博士研究生的智能决策、系统可靠性与智能运维方法课程」。
  红框圈出的是封面图上的英文 **`RELAIBILITY` / `IMILIGENT`**。
- 09-18 14:57 冯建设：「有错别字，直接一点，就 "IDSR Course"」，并 @ 了高鹏。
- 09-18 19:37 冯建设：「我的IDSR的课程，也需要单独弄一个repo」→ `github.com/JiansheFengRe/idsr-course`。
- IDSR 是 Intelligent Decision-Making and System Reliability（Engineering）的缩写，
  实验室官网课程页的英文副标题就是这么写的。

所以错名的具体写法是 **RELAIBILITY**（正确为 RELIABILITY）和 **IMILIGENT**（正确为 INTELLIGENT）。
这是 AI 生成封面时产生的乱码拼写，不在任何文字字段里。归档消息里全文搜 `RELAIB|IMILIG` 也没有命中。

### 出现位置清单

**A. 错误写法（RELAIBILITY / IMILIGENT）**

| 位置 | 状态 |
|---|---|
| 线上课程「智能决策与系统可靠性工程」的封面图（课程列表卡片、课程详情页头图） | **有错字，需要换图。** 图片存在生产环境的媒体存储里，不在仓库中；课程 uuid 和图片文件名要登录后才能查到 |
| `/Volumes/D/code/learnhouse`（全仓库，已排除 node_modules/.git/缓存） | 无 |
| `~/.claude/skills/learnhouse-teaching`（软链接到 `~/.agents/skills/learnhouse-teaching`） | 无 |
| learn.sysu-sam.com 匿名可见页面：`/`、`/courses`、`/library`、`/podcasts`、`/communities`、`/playgrounds`、`/signup`、`/login`，以及匿名 API `/api/v1/courses/org_slug/default/page/1/limit/50`（返回 `[]`） | 无（匿名用户看不到任何课程） |

**B. 如果要把课程命名统一成 "IDSR Course"，还需要改的旧名（不是错字，是现在用的中文名）**

| 位置 | 当前值 |
|---|---|
| 线上课程标题（登录后可见） | 智能决策与系统可靠性工程 |
| 线上课程简介 | 面向博士研究生的智能决策、系统可靠性与智能运维方法课程 |
| 线上用户组名（后台「用户」表群组列、邀请码关联组） | 智能决策与系统可靠性工程（也就是任务一里被竖排的那个徽章） |
| 实验室官网 https://ai.sysu-sam.com/teaching/courses/intelligent-decision-reliability/ | `<title>`、面包屑、H1 都是「智能决策与系统可靠性工程」，H2 是「Intelligent Decision-Making and System Reliability Engineering」。**拼写正确**，不属于 learnhouse，列在这里仅供参考 |

仓库和技能里没有这门课的名字（`智能决策与系统|IDSR|decision…reliab` 都没有命中），所以代码侧不需要改。

### 需要人确认的一点

老师的话是针对封面图说的，至少要把**封面图换成写 "IDSR Course" 的版本**。
课程标题和用户组名要不要也改成 "IDSR Course"，从原话里看不出来，需要跟冯老师或高鹏确认。
按高鹏 9/16 转述的老师分工（高鹏负责内容、朱奕樟负责功能），封面和标题属于内容，归高鹏。
