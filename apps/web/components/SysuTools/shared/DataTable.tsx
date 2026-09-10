'use client'
/**
 * 教学工具的表格。手写 `<table>` + Tailwind，样式照 UI_GUIDE 3.4 / 3.5，
 * **不要**换成 shadcn 的 `components/ui/table` —— 密度和字重都不一样。
 *
 * 三态（骨架屏 / 空态 / 翻页遮罩）已经内置，各工具不用重复写。
 */
import React from 'react'
import { Inbox } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import LearnHouseSpinner from '@components/Objects/Loaders/LearnHouseSpinner'
import { cn } from '@/lib/utils'

export interface DataTableColumn<T> {
  key: string
  /** 表头文案，已经 t() 过。 */
  header: string
  /** 单元格渲染。返回 undefined / null 会自动画成灰色的「—」。 */
  cell: (_row: T) => React.ReactNode
  /** 靠右对齐（操作列常用）。 */
  align?: 'start' | 'end'
  /** 表头额外 class。 */
  className?: string
}

interface DataTableProps<T> {
  columns: DataTableColumn<T>[]
  rows: T[]
  rowKey: (_row: T) => string
  /** 首次加载：画骨架屏而不是 spinner。 */
  isInitialLoading?: boolean
  /** 已有数据的刷新/翻页：半透明遮罩 + spinner。 */
  isRefreshing?: boolean
  /** 当前是否有筛选条件 —— 决定空态说「没数据」还是「没结果」。 */
  hasActiveFilters?: boolean
  /** 清除筛选的回调，传了才会在空态里显示按钮。 */
  onClearFilters?: () => void
  /** 空态图标，默认收件箱。 */
  emptyIcon?: React.ComponentType<any>
  /** 覆盖空态文案。 */
  emptyMessage?: string
  /** 骨架屏画几行。 */
  skeletonRows?: number
}

export default function DataTable<T>({
  columns,
  rows,
  rowKey,
  isInitialLoading = false,
  isRefreshing = false,
  hasActiveFilters = false,
  onClearFilters,
  emptyIcon: EmptyIcon = Inbox,
  emptyMessage,
  skeletonRows = 6,
}: DataTableProps<T>) {
  const { t } = useTranslation()

  return (
    <div className="bg-white nice-shadow rounded-xl overflow-hidden max-w-[1600px] mx-auto w-full">
      <div className="overflow-x-auto relative">
        {isInitialLoading ? (
          <div className="animate-pulse px-6 py-4">
            {Array.from({ length: skeletonRows }).map((_, i) => (
              <div
                key={i}
                className="flex items-center gap-4 py-4 border-b border-gray-50 last:border-b-0"
              >
                <div className="h-3.5 bg-gray-200 rounded w-40" />
                <div className="h-3 bg-gray-100 rounded w-24" />
                <div className="h-8 bg-gray-100 rounded-md w-20 ms-auto" />
              </div>
            ))}
          </div>
        ) : rows.length === 0 ? (
          <div className="py-16 text-center">
            <div className="flex flex-col items-center gap-3">
              <div className="bg-gray-100 p-4 rounded-full">
                <EmptyIcon className="w-8 h-8 text-gray-400" />
              </div>
              <p className="text-gray-400 text-sm font-medium">
                {emptyMessage ??
                  (hasActiveFilters
                    ? t('ext.common.no_results', { defaultValue: '没有符合条件的结果' })
                    : t('ext.common.no_data', { defaultValue: '暂无数据' }))}
              </p>
              {hasActiveFilters && onClearFilters ? (
                <button
                  onClick={onClearFilters}
                  className="text-xs text-indigo-600 hover:text-indigo-800 font-medium cursor-pointer"
                >
                  {t('ext.common.clear_filters', { defaultValue: '清除筛选' })}
                </button>
              ) : null}
            </div>
          </div>
        ) : (
          <div className="relative">
            {isRefreshing ? (
              <div className="absolute inset-0 bg-white/60 z-10 flex items-center justify-center rounded-lg">
                <LearnHouseSpinner size={28} />
              </div>
            ) : null}
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100">
                  {columns.map((col) => (
                    <th
                      key={col.key}
                      className={cn(
                        'text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3',
                        col.align === 'end' ? 'text-end' : 'text-start',
                        col.className
                      )}
                    >
                      {col.header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {rows.map((row) => (
                  <tr key={rowKey(row)} className="hover:bg-gray-50 transition-colors">
                    {columns.map((col) => {
                      const content = col.cell(row)
                      return (
                        <td
                          key={col.key}
                          className={cn(
                            'px-6 py-4',
                            col.align === 'end' ? 'text-end' : 'text-start'
                          )}
                        >
                          {content === null || content === undefined || content === '' ? (
                            <span className="text-xs text-gray-400">—</span>
                          ) : (
                            content
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
