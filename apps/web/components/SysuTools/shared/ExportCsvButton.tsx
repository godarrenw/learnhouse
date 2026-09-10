'use client'
/**
 * 导出 CSV 按钮。在浏览器里就地生成文件，不经过后端。
 *
 * 加了 UTF-8 BOM —— 没有它 Excel 打开中文列名会乱码，这是教务场景的必备项。
 */
import React from 'react'
import { Download } from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'

export interface CsvColumn<T> {
  /** 表头文案，已经 t() 过。 */
  header: string
  /** 取值。返回 null / undefined 会写成空串。 */
  value: (_row: T) => string | number | null | undefined
}

interface ExportCsvButtonProps<T> {
  /** 文件名，不带扩展名。会自动追加日期。 */
  filename: string
  columns: CsvColumn<T>[]
  /** 惰性求值：点了才算，避免每次渲染都拼一遍大数组。 */
  rows: () => T[]
  disabled?: boolean
  label?: string
}

/** 按 RFC 4180 转义：含逗号、引号、换行的字段要包引号，内部引号翻倍。 */
function escapeCell(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return ''
  const s = String(value)
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export function toCsv<T>(columns: CsvColumn<T>[], rows: T[]): string {
  const head = columns.map((c) => escapeCell(c.header)).join(',')
  const body = rows.map((row) => columns.map((c) => escapeCell(c.value(row))).join(','))
  return [head, ...body].join('\r\n')
}

export default function ExportCsvButton<T>({
  filename,
  columns,
  rows,
  disabled,
  label,
}: ExportCsvButtonProps<T>) {
  const { t } = useTranslation()

  function handleExport() {
    const data = rows()
    if (data.length === 0) {
      toast.error(t('ext.common.export_empty', { defaultValue: '没有可导出的数据' }))
      return
    }
    const csv = toCsv(columns, data)
    // U+FEFF = UTF-8 BOM。没有它 Excel 打开中文列名会乱码。
    // 写成转义序列而不是字面量：ESLint 的 no-irregular-whitespace 会拦字面量 BOM。
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    const stamp = new Date().toISOString().slice(0, 10)
    link.href = url
    link.download = `${filename}-${stamp}.csv`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
    toast.success(t('ext.common.export_success', { count: data.length }))
  }

  return (
    <button
      onClick={handleExport}
      disabled={disabled}
      className="flex items-center gap-1.5 bg-white nice-shadow rounded-lg px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <Download className="w-4 h-4" />
      {label ?? t('ext.common.export_csv', { defaultValue: '导出 CSV' })}
    </button>
  )
}
