'use client'
/**
 * 作业工具五个 Tab 共用的小件。都只是把 UI_GUIDE 里的固定写法包一层，
 * 免得每个 Tab 重复抄同样的 class。
 */
import React from 'react'
import { BookOpen, Inbox } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { cn } from '@/lib/utils'

/** 白底卡片。UI_GUIDE 2.3：`bg-white nice-shadow rounded-xl`，不要写 border + shadow-sm。 */
export function Card({
  title,
  description,
  children,
  className,
  testId,
}: {
  title?: string
  description?: string
  children: React.ReactNode
  className?: string
  testId?: string
}) {
  return (
    <div
      data-testid={testId}
      className={cn('bg-white nice-shadow rounded-xl p-5 sm:p-6', className)}
    >
      {title ? (
        <div className="pb-4">
          <div className="text-sm font-semibold text-gray-800">{title}</div>
          {description ? (
            <div className="text-xs text-gray-400 pt-1 leading-relaxed">{description}</div>
          ) : null}
        </div>
      ) : null}
      {children}
    </div>
  )
}

/** 一行表单项：标签在上、控件在下。 */
export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: string
  hint?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <label className={cn('flex flex-col gap-1.5 min-w-0', className)}>
      <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
        {label}
      </span>
      {children}
      {hint ? <span className="text-xs text-gray-400">{hint}</span> : null}
    </label>
  )
}

const CONTROL =
  'bg-white rounded-lg text-sm text-gray-800 px-3 py-2 outline outline-1 outline-neutral-200 ' +
  'focus:outline-gray-400 min-w-0 w-full disabled:opacity-50 disabled:cursor-not-allowed'

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  const { className, ...rest } = props
  return <select {...rest} className={cn(CONTROL, 'cursor-pointer', className)} />
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const { className, ...rest } = props
  return <input {...rest} className={cn(CONTROL, className)} />
}

export function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const { className, ...rest } = props
  return <textarea {...rest} className={cn(CONTROL, 'font-mono leading-relaxed', className)} />
}

/** 主按钮：黑底白字，与 shadcn Button 的 default 变体同款。 */
export function PrimaryButton({
  className,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      className={cn(
        'inline-flex items-center gap-1.5 bg-gray-900 text-white rounded-lg px-4 py-2 text-sm',
        'font-medium hover:bg-gray-800 transition-colors cursor-pointer',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        className
      )}
    />
  )
}

/** 次按钮：白底，用于「校验」「刷新」这类不改数据的动作。 */
export function GhostButton({
  className,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      className={cn(
        'inline-flex items-center gap-1.5 bg-white nice-shadow rounded-lg px-3 py-2 text-sm',
        'font-medium text-gray-700 hover:bg-gray-50 transition-colors cursor-pointer',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        className
      )}
    />
  )
}

/** 空态：圆形灰底图标 + 一行灰字。UI_GUIDE 3.5。 */
export function EmptyState({
  message,
  icon: Icon = Inbox,
  action,
}: {
  message: string
  icon?: React.ComponentType<any>
  action?: React.ReactNode
}) {
  return (
    <div className="py-16 text-center">
      <div className="flex flex-col items-center gap-3">
        <div className="bg-gray-100 p-4 rounded-full">
          <Icon className="w-8 h-8 text-gray-400" />
        </div>
        <p className="text-gray-400 text-sm font-medium">{message}</p>
        {action}
      </div>
    </div>
  )
}

/** 还没选课程时的提示。`courseScoped` 的工具在选课前不要发请求。 */
export function NeedCourse() {
  const { t } = useTranslation()
  return (
    <Card testId="assign-need-course">
      <EmptyState
        icon={BookOpen}
        message={t('ext.common.course_required', { defaultValue: '请先选择一个课程' })}
      />
    </Card>
  )
}

/** 骨架屏：首次加载画它，不要画 spinner。UI_GUIDE 3.5。 */
export function Skeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="animate-pulse space-y-3" data-testid="assign-skeleton">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-4">
          <div className="h-3.5 bg-gray-200 rounded w-40" />
          <div className="h-3 bg-gray-100 rounded w-24" />
          <div className="h-3 bg-gray-100 rounded flex-1" />
        </div>
      ))}
    </div>
  )
}

/** 一条警告。AI 出的题、查重结果都要把后端给的提醒原样显示出来。 */
export function WarningList({ items }: { items: string[] }) {
  if (!items || items.length === 0) return null
  return (
    <ul className="bg-amber-50 rounded-lg px-4 py-3 space-y-1.5" data-testid="assign-warnings">
      {items.map((w, i) => (
        <li key={i} className="text-xs text-amber-800 leading-relaxed">
          {w}
        </li>
      ))}
    </ul>
  )
}

/** 百分比条，随堂测的答对率用。 */
export function RateBar({ value }: { value: number | null }) {
  const { t } = useTranslation()
  if (value === null || value === undefined) {
    return (
      <span className="text-xs text-gray-400">
        {t('ext.tools.assign.quiz.no_answer_yet', { defaultValue: '还没有人作答' })}
      </span>
    )
  }
  const tone =
    value >= 80 ? 'bg-emerald-500' : value >= 50 ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="h-2 bg-gray-100 rounded-full flex-1 min-w-[60px] overflow-hidden">
        <div className={cn('h-full rounded-full', tone)} style={{ width: `${value}%` }} />
      </div>
      <span className="text-xs font-semibold text-gray-700 tabular-nums shrink-0">
        {value}%
      </span>
    </div>
  )
}
