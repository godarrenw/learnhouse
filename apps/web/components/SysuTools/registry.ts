/**
 * 教学工具注册表 —— 新工具接入的唯一入口。
 *
 * 加一个工具需要做的事：
 *   1. 在 `components/SysuTools/tools/<YourTool>/` 下写组件，默认导出，
 *      props 类型是 `SysuToolProps`。
 *   2. 在下面 `SYSU_TOOLS` 数组里加一个条目（**只加一行块，不要动别人的**）。
 *   3. 在 `locales/ext/zh.json` 与 `en.json` 的 `tools.<key>` 下补文案。
 *   4. 后端在 `apps/api/src/routers/ext/` 加子模块，并把模块名写进
 *      `src/routers/ext/__init__.py` 的 `SUBMODULES`。
 *
 * 路由、菜单、命令面板、权限过滤都是按这个数组自动生成的，不用再改别的文件。
 * 详见 `docs/sysu-sam/EXT_TOOLS.md`。
 */
import { lazy } from 'react'
import { Activity, ClipboardPen, FileText, GraduationCap, LayoutGrid, UserCheck } from 'lucide-react'

import type { SysuTool, SysuToolRole } from './types'

export type { SysuTool, SysuToolProps, SysuToolRole } from './types'

export const SYSU_TOOLS: SysuTool[] = [
  {
    key: 'overview',
    titleKey: 'ext.overview.title',
    descKey: 'ext.overview.subtitle',
    icon: LayoutGrid,
    component: lazy(() => import('./tools/Overview/ToolsOverview')),
    minRole: 'instructor',
  },
  {
    key: 'content',
    titleKey: 'ext.tools.content.title',
    descKey: 'ext.tools.content.description',
    icon: FileText,
    component: lazy(() => import('./tools/Content/ContentTools')),
    minRole: 'instructor',
    courseScoped: true,
  },
  {
    key: 'example',
    titleKey: 'ext.tools.example.title',
    descKey: 'ext.tools.example.description',
    icon: Activity,
    component: lazy(() => import('./tools/Example/ExampleTool')),
    minRole: 'instructor',
  },
  {
    key: 'learning',
    titleKey: 'ext.tools.learning.title',
    descKey: 'ext.tools.learning.description',
    icon: GraduationCap,
    component: lazy(() => import('./tools/learning/LearningTool')),
    minRole: 'instructor',
    courseScoped: true,
  },
  {
    key: 'assign',
    titleKey: 'ext.tools.assign.title',
    descKey: 'ext.tools.assign.description',
    icon: ClipboardPen,
    component: lazy(() => import('./tools/assign/AssignTools')),
    minRole: 'instructor',
    courseScoped: true,
  },
  {
    key: 'checkin',
    titleKey: 'ext.tools.checkin.title',
    descKey: 'ext.tools.checkin.description',
    icon: UserCheck,
    component: lazy(() => import('./tools/checkin/CheckinTool')),
    minRole: 'instructor',
    courseScoped: true,
  },
]

/** 概览页自己也在注册表里（好让 Tab 条有个「概览」），但不该出现在卡片网格里。 */
export const OVERVIEW_KEY = 'overview'

export function getTool(key: string | undefined): SysuTool | undefined {
  if (!key) return undefined
  return SYSU_TOOLS.find((tool) => tool.key === key)
}

/**
 * 按角色过滤出当前用户能看到的工具。
 *
 * `rights` 来自 `useAdminStatus()`。三档的判断依据：
 * - instructor：能进后台就行（`dashboard.action_access`，与后端 require_teacher 同口径）
 * - maintainer：需要能改用户组（Admin / Maintainer 才有）
 * - admin：需要能改组织（等价于 `canManageOrg`）
 */
export function filterToolsByRights(
  tools: SysuTool[],
  rights: any,
  canManageOrg: boolean
): SysuTool[] {
  const level: Record<SysuToolRole, boolean> = {
    instructor: rights?.dashboard?.action_access === true || canManageOrg,
    maintainer: rights?.usergroups?.action_update === true || canManageOrg,
    admin: canManageOrg,
  }
  return tools.filter((tool) => level[tool.minRole])
}

/** 概览页卡片网格用的列表：过完权限，并去掉概览自己。 */
export function visibleToolCards(rights: any, canManageOrg: boolean): SysuTool[] {
  return filterToolsByRights(SYSU_TOOLS, rights, canManageOrg).filter(
    (tool) => tool.key !== OVERVIEW_KEY
  )
}
