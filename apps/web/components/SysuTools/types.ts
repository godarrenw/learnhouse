/**
 * 教学工具（ext）的公共类型。
 *
 * 单独一个文件是为了让 registry.ts 与各工具组件都能引它，而不用互相 import
 * 造成循环依赖。
 */
import type { ComponentType, LazyExoticComponent } from 'react'

/** 工具页面组件统一收到的 props。 */
export interface SysuToolProps {
  /**
   * 当前选中的课程 uuid。只有 `courseScoped: true` 的工具会拿到它。
   *
   * 选课下拉由路由页统一渲染（见 `dash/tools/[tool]/page.tsx`），工具组件
   * 不要自己再写一个。未选课时是 `undefined`，此时组件应渲染一句提示而不是
   * 发请求。
   */
  courseUuid?: string
}

/** 允许的最低角色。与后端 `require_teacher` 的口径一致。 */
export type SysuToolRole = 'instructor' | 'maintainer' | 'admin'

export interface SysuTool {
  /** 路由段，`/dash/tools/<key>`。全局唯一，用小写连字符。 */
  key: string
  /** 标题的 i18n key，例如 `ext.tools.example.title`。 */
  titleKey: string
  /** 一句话说明的 i18n key。概览页卡片上会显示。 */
  descKey: string
  /** 卡片与 Tab 上的图标，用 lucide-react（页面内容一律 Lucide）。 */
  icon: ComponentType<any>
  /** 工具主体组件，必须 lazy 以免拖慢概览页首屏。 */
  component: LazyExoticComponent<ComponentType<SysuToolProps>>
  /**
   * 能看到这个工具的最低角色。
   * - `instructor`：Admin / Maintainer / Instructor 都能看（默认，等价于能进后台）
   * - `maintainer`：只有 Admin / Maintainer
   * - `admin`：只有组织管理员
   */
  minRole: SysuToolRole
  /**
   * 是否需要先选课程。为 true 时路由页会在页头下渲染 CourseSelect，
   * 并把选中的课程 uuid 通过 `courseUuid` prop 传给组件。
   */
  courseScoped?: boolean
}
