# 作业截止前重新提交

日期：2026-11-12。验证使用隔离工作副本中的源码和已有依赖，后端数据库为内存 SQLite。

## 行为

作业设置中已有的“允许重试”开关继续控制重新提交，默认关闭。开启后，计分作业不再要求先评分：已提交、迟交或已评分的作业均可在截止前重新作答。没有截止日期的作业沿用原来的不限时规则。最大尝试次数仍包括首次提交，0 表示不限次数。

学生确认重试后，旧答案会立即清空，提交回到待作答状态；学生需要在截止前重新完成并提交。前端确认提示已明确这一点。这沿用现有的重试流程，并不在编辑期间保留旧的已提交答案。重新提交复用同一条用户提交记录，不增加历史提交行，后续评分覆盖旧成绩。重试也继续沿用原有的学习进度重置及证书撤销逻辑。

未评分作业的状态旁新增重试入口，中英文说明均已更新。计分作业的“评分中”状态提示保留。未开启重试、次数耗尽或已过截止日期时不展示该入口，后端继续检查相同条件。

## 验证

- 后端：`PYTHONDONTWRITEBYTECODE=1 apps/api/.venv/bin/python -m pytest -p no:cacheprovider apps/api/src/tests/routers/test_assignments_retry.py apps/api/src/tests/services/test_retry_attempt_caps_edge.py apps/api/src/tests/services/test_assignment_formative_mode.py apps/api/src/tests/services/test_assignments_service.py -q`，186 passed。
- 前端类型：在 `apps/web` 运行 `node node_modules/typescript/bin/tsc --noEmit --incremental false --types next,next/image-types/global -p .`，通过。显式指定 Next 类型，供未生成 `next-env.d.ts` 的离线副本使用。
- 前端 ESLint：在 `apps/web` 对修改的活动页执行现有 ESLint，0 errors、17 warnings；最终使用 `--quiet` 复查通过。警告位于本次未修改的已有代码。
- 中英文语言包 JSON 解析与本次所需文案键检查通过。

回归测试包含三种已交状态的重试、清空本人旧答案而保留他人答案、复用提交记录且不产生重复行、待作答状态不可重复重试、关闭开关、次数限制、无限次数和截止后拒绝操作并保留原记录。

## 发布状态

已实现，待本批统一验证与部署。未执行生产操作、数据库迁移、提交、镜像构建或发布。浏览器端到端交互和移动端视觉未实测，交由本批统一验收。发布入口仍需形成可追溯提交及 CI 镜像，完成整批构建与生产预检后部署。
