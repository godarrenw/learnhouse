'use client'
/**
 * 可排序表格。
 *
 * 为什么不用 `shared/DataTable`：它的 `header` 是 `string`，塞不进
 * ArrowUp/ArrowDown 图标，也没有表头点击回调，而 UI_GUIDE 3.4 要求可排序表头
 * 必须显示方向图标。样式（表头字重、行 hover、三态、空态）与 DataTable 逐字一致，
 * 只多了排序。骨架把 `DataTableColumn.header` 放宽成 ReactNode 之后，
 * 这个文件可以删掉，改回直接用 DataTable。
 */
import React from 'react'
import { ArrowDown, ArrowUp, Inbox } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import LearnHouseSpinner from '@components/Objects/Loaders/LearnHouseSpinner'
import { cn } from '@/lib/utils'

export interface SortableColumn<T> {
  key: string
  header: string
  cell: (_row: T) => React.ReactNode
  align?: 'start' | 'end'
  /** 传了才可点排序。 */
  sortKey?: string
}

interface SortableTableProps<T, K extends string = string> {
  columns: SortableColumn<T>[]
  rows: T[]
  rowKey: (_row: T) => string
  sortKey?: K
  sortDirection?: 'asc' | 'desc'
  onSort?: (_key: K) => void
  isInitialLoading?: boolean
  isRefreshing?: boolean
  emptyIcon?: React.ComponentType<any>
  emptyMessage?: string
  skeletonRows?: number
  testId?: string
}

export default function SortableTable<T, K extends string = string>({
  columns,
  rows,
  rowKey,
  sortKey,
  sortDirection = 'asc',
  onSort,
  isInitialLoading = false,
  isRefreshing = false,
  emptyIcon: EmptyIcon = Inbox,
  emptyMessage,
  skeletonRows = 6,
  testId,
}: SortableTableProps<T, K>) {
  const { t } = useTranslation()

  return (
    <div className="bg-white nice-shadow rounded-xl overflow-hidden max-w-[1600px] mx-auto w-full">
      <div className="overflow-x-auto relative">
        {isInitialLoading ? (
          <div className="animate-pulse px-6 py-4" data-testid="learning-skeleton">
            {Array.from({ length: skeletonRows }).map((_, index) => (
              <div
                key={index}
                className="flex items-center gap-4 py-4 border-b border-gray-50 last:border-b-0"
              >
                <div className="h-3.5 bg-gray-200 rounded w-40" />
                <div className="h-3 bg-gray-100 rounded w-24" />
                <div className="h-8 bg-gray-100 rounded-md w-20 ms-auto" />
              </div>
            ))}
          </div>
        ) : rows.length === 0 ? (
          <div className="py-16 text-center" data-testid="learning-empty">
            <div className="flex flex-col items-center gap-3">
              <div className="bg-gray-100 p-4 rounded-full">
                <EmptyIcon className="w-8 h-8 text-gray-400" />
              </div>
              <p className="text-gray-400 text-sm font-medium">
                {emptyMessage ?? t('ext.common.no_data', { defaultValue: '暂无数据' })}
              </p>
            </div>
          </div>
        ) : (
          <div className="relative">
            {isRefreshing ? (
              <div className="absolute inset-0 bg-white/60 z-10 flex items-center justify-center rounded-lg">
                <LearnHouseSpinner size={28} />
              </div>
            ) : null}
            <table className="w-full" data-testid={testId}>
              <thead>
                <tr className="border-b border-gray-100">
                  {columns.map((col) => {
                    const sortable = !!col.sortKey && !!onSort
                    const active = !!col.sortKey && col.sortKey === sortKey
                    return (
                      <th
                        key={col.key}
                        onClick={sortable ? () => onSort?.(col.sortKey as K) : undefined}
                        className={cn(
                          'text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3 whitespace-nowrap',
                          col.align === 'end' ? 'text-end' : 'text-start',
                          sortable &&
                            'cursor-pointer select-none hover:text-gray-700 transition-colors'
                        )}
                      >
                        <span
                          className={cn(
                            'inline-flex items-center gap-1',
                            col.align === 'end' && 'flex-row-reverse'
                          )}
                        >
                          {col.header}
                          {active &&
                            (sortDirection === 'asc' ? (
                              <ArrowUp className="w-3.5 h-3.5" />
                            ) : (
                              <ArrowDown className="w-3.5 h-3.5" />
                            ))}
                        </span>
                      </th>
                    )
                  })}
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
