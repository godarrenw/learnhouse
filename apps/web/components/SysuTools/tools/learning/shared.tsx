'use client'
/** 学情工具四个 Tab 共用的小件。表格本体一律用 shared/DataTable（它自带排序表头与三态）。 */
import React from 'react'

/** 排序状态：点同一列翻转方向，点别的列换列并回到升序。 */
export function useSort<T extends string>(initial: T) {
  const [key, setKey] = React.useState<T>(initial)
  const [direction, setDirection] = React.useState<'asc' | 'desc'>('asc')
  const toggle = React.useCallback(
    (next: T) => {
      setDirection((prev) => (next === key && prev === 'asc' ? 'desc' : 'asc'))
      setKey(next)
    },
    [key]
  )
  return { key, direction, toggle }
}

/**
 * 数值比较：空值永远排在最后，不受升降序影响。
 * 否则「没交」的空单元格会在降序时顶到第一名。
 */
export function compareNullable(
  left: number | null | undefined,
  right: number | null | undefined,
  factor: number
) {
  if (left === null || left === undefined) return 1
  if (right === null || right === undefined) return -1
  return factor * (left - right)
}

/** 中文姓名按拼音排。 */
export function compareText(left: unknown, right: unknown, factor: number) {
  return factor * String(left ?? '').localeCompare(String(right ?? ''), 'zh-Hans-CN')
}

/** 后端已经把时间转成展示时区并带 offset，这里只做本地化显示。 */
export function formatTime(iso: string | null | undefined): string | null {
  if (!iso) return null
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString()
}

/** 姓名 + 邮箱两行，四个 Tab 的第一列都是这个形状。 */
export function PersonCell({ name, email }: { name?: string; email?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-gray-800 font-semibold text-sm truncate">{name}</div>
      <div className="text-gray-400 text-xs truncate">{email}</div>
    </div>
  )
}

/** 接口返回的 note（例如「这门课没绑用户组」）统一这样显示。 */
export function ToolNote({ text }: { text?: string }) {
  if (!text) return null
  return (
    <p className="px-4 sm:px-10 pb-3 max-w-[1600px] mx-auto w-full text-xs text-amber-600 font-medium">
      {text}
    </p>
  )
}

/** 一行工具栏：左边筛选，右边动作。 */
export function Toolbar({ start, end }: { start?: React.ReactNode; end?: React.ReactNode }) {
  return (
    <div className="px-4 sm:px-10 pb-4 max-w-[1600px] mx-auto w-full flex flex-wrap items-center gap-3">
      <div className="flex flex-wrap items-center gap-3 min-w-0">{start}</div>
      <div className="flex items-center gap-3 ms-auto">{end}</div>
    </div>
  )
}

/** 工具内容区的外边距，和 DataTable 的最大宽度对齐。 */
export function ToolBody({ children }: { children: React.ReactNode }) {
  return <div className="px-4 sm:px-10 pb-10">{children}</div>
}

/** 没选课程时的提示，`courseScoped` 的工具首屏会走到这里。 */
export function NeedCourse({ message }: { message: string }) {
  return (
    <div className="py-16 text-center text-gray-400 text-sm font-medium">{message}</div>
  )
}
