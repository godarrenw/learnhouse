# 页内小测 / 翻卡 / 提示框 / 图片 / 表格：手机端 QA

2026-09-21。本地复刻栈 `learnhouse-local`（`http://localhost:18088`，镜像 `learnhouse-sysu-sam:local`，2026-09-10 构建），
**未碰生产**。这 5 个组件相关的前端文件（Quiz、Flipcard、Callout、Image 扩展，`styles/globals.css`、`lib/quiz`）
在镜像构建之后没有新提交，所以本地结果就代表当前 sysu-sam 的行为。

## 结论

| 组件 | 手机 390×844 | 说明 |
|---|---|---|
| 页内小测 `blockQuiz` | **能用** | 学生和管理员（在查看页）都能点选、提交、重置。提交后每个选项标绿/红，底部给「所有答案都正确!」/「某些答案不正确!」，全对时撒彩带。小问题：题号「QUESTION 1」是英文（zh.json 缺 `question_label`，多选题提示 `select_all_that_apply` 也缺）|
| 连续翻卡 `flipcardGrid` + `flipcard` | **能用，但长文字会溢出** | 3 张连续卡：手机上 1 列（318px 宽），桌面上 3 列（284px 宽）。点击翻面、再点翻回都正常。**卡片高度固定为 192px（medium）**，背面文字约 70 字以上就溢出：图标和「点击翻回」被挤出卡外（见 `ch07-student-390-explain-all-flipped.png`） |
| 提示框 `calloutInfo` | **能用** | 自动换行，高度随内容，粗体 mark 也能显示 |
| 图片 `blockImage` | **能用** | 设了 620px 宽，手机上缩到 318px、等比例；2169px 宽的原图加载正常 |
| 4 列表格 `table` | **能用，挤** | 390 宽下 4 列刚好放进 318px，不用横向滚动，但「主轴转速」「8000 rpm」这类单元格会折成两三行。4 列就是上限了 |

其他发现：

- **编辑器在手机上根本不开**。宽度 390 下，`/course/…/activity/…/edit` 只显示「仅限桌面端」（`admin-390-07-editor.png`）。
  这是平台设计如此。桌面端编辑器能正常加载 2 道小测（8 个输入框）和翻卡网格（`admin-1280-07-editor.png`）。
- 所有活动页都会报 `Minified React error #418`（hydration 不一致）。已排除这几个组件的原因：
  一个不含小测、翻卡的旧活动页也报，课程列表和首页不报。实测不影响交互。
- 手机上页面底部有一个浮层「点击以将此活动标记为完成」，会盖住最后一个块的下沿，但可以关掉。
- **`blockQuiz` 没有解析字段**。attrs 只有 `quizId` 和 `questions`，题目的解析需要另外放一个块。

## blockQuiz 节点结构（从源码读出来，并经过实例回读验证）

来源：`apps/web/components/Objects/Editor/Extensions/Quiz/QuizBlock.ts`、`QuizBlockComponent.tsx`、`apps/web/lib/quiz/modes.ts`。
上游 `apps/api/src/services/demo/content.py` 和 `services/ai/quiz.py` 生成的也是这个形状。

```json
{"type": "blockQuiz", "attrs": {
  "quizId": "quiz_ch01",
  "questions": [{
    "question_id": "question_ch01-q1", "question": "…", "type": "multiple_choice",
    "response_type": "single",
    "answers": [{"answer_id": "answer_ch01-q1_0", "answer": "…", "correct": true}]
  }]}}
```

- `response_type` 取 `single` 或 `multiple`，不写时按正确答案个数推断（≥2 个就是多选）
- 只读模式（`isEditable=false`）下能作答。单选是 radio 语义，新选的会替换旧选的。一个都没选时「提交」不可点。
  判分是纯前端、全对才算对，不存成绩，刷新就清空
- 没有标正确答案的题判不了对错，提交时会被跳过

⚠️ **skill 文档写错了**：`~/.claude/skills/learnhouse-teaching/reference/content-authoring.md` §2.12 给的
`{"id", "options": [{"id", "text"}]}` 和组件实际读的字段对不上，组件会在 `question.answers.map` 处报错。
应该改成上面的形状（本次没有改 skill 文档）。

## 翻卡为什么会溢出

`FlipcardExtension.tsx` 的 `getSizeClass()`：small `h-36` / medium `h-48` / large `h-60`，正反两面是绝对定位，
所以高度不跟内容走。在网格里宽度随格子变，高度仍然用这个固定值。实测（medium，text-lg 字号）：

| 背面字数 | 390 宽（318px） | 1280 宽，3 列（284px） |
|---|---|---|
| 62~63 | 刚好放下 | 63 字溢出 6px |
| 73 | 溢出 6px | 溢出 20px |
| 137 | 溢出 20px，图标和提示被挤出去 | 溢出 48px |

换成 large 也没用：高度多了 48px，但字号变成 text-xl，每行放的字更少。

## 转换器 `idsr-course/tools/quiz_to_tiptap.py`

`quiz_yaml_to_nodes(path, explain_style="auto") -> list[dict]`，输出一整页：

1. 一个 `blockQuiz`，装本章所有题。一题一个块的话，每块都显示「Question 1」
2. 「答案解析」标题和一句提示
3. 解析部分：本章所有 `explain` 都在 60 字以内时，每题一张翻卡，放进 2 列 `flipcardGrid`；
   有任何一条更长时，每题一个 `calloutInfo`，写成「**第 N 题（答案 X）**：解析」

所有 id 都从 yaml 的 `id` 派生，同一个文件每次转出来完全一样，`sync_to_learn.py` 靠哈希判断有没有改动，依赖这一点。
格式不对时抛 `QuizYamlError`（是 `ValueError` 的子类），错误信息里带题号。

现有 8 章：ch01、ch02 用翻卡，ch03~ch08 用提示框（它们的解析最长 64~132 字）。

实例验证：

- `python3 tools/quiz_to_tiptap.py`：内置自测通过，8 份 quiz.yaml 全部能转
- 把 ch01 前 2 题转出来 PUT 到本地实例，GET 回来的 JSON 和发出去的逐字节一致。学生账号在 390 和 1280 宽下都真实点选、提交、看解析过
- ch07 整份（5 题，含 132 字的解析）：翻卡版实测溢出，于是改成自动选择；提示框版重新 PUT、截图，粗体和答案字母都对

## 截图

`docs/sysu-sam/QA/shots/quiz-mobile/`，文件名是 `{角色}-{宽度}-{步骤}`：

- `01-page` 整页，`02-flipcards-flipped` 3 张全翻开，`03-quiz-answered` 已选未交，
  `04-quiz-submitted-one-wrong` 错一题的反馈，`05-quiz-all-correct` 全对，`05b-viewport-confetti` 彩带，
  `06-explain-flipped` 解析卡翻开，`07-editor` 编辑器（390 下是「仅限桌面端」）
- `ch07-student-*` 翻卡版长解析（溢出的证据），`ch07-callout-student-*` 提示框版

## 复现

脚本在会话 scratchpad 里，没有进仓库。本地测试数据：课程「【测试】QA 小测翻卡手机」
（`course_323cf31f-1fed-4c09-a421-ab1d2fce5b31`），里面有两个活动。管理员用 `user1@example.local`，
学生用 `user2@example.local` / `LocalDev#2026`。不需要时在本地删掉即可。
