'use client'
/**
 * 概览页的「最近学习动态」小卡片：组织级，列最近 N 条学习事件。
 *
 * 数据来自学情工具的 `GET /ext/learning/recent`（组织级，不用选课）。那个接口
 * 原本没有前端入口，集成时把它接到这里 —— 老师打开教学工具第一眼就能看到
 * 「最近谁在学什么」，不用先选课程再进具体工具。
 *
 * 拿不到数据时整张卡片不渲染（比如学情工具没装、或者接口 403），概览页的
 * 工具网格不受影响。
 */
import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, BookOpen, CheckCircle2, PlayCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { useLHSession } from '@components/Contexts/LHSessionContext'
import { useOrg } from '@components/Contexts/OrgContext'
import { getRecent } from '@services/ext/learning'
import { queryKeys } from '@/lib/query/keys'

const DAYS = 7
const MAX_ROWS = 8

interface RecentEvent {
  user_id: number
  name: string | null
  email: string | null
  kind: 'activity_completed' | 'activity_opened' | 'course_started'
  at: string | null
  course_name: string | null
  activity_name: string | null
}

/** 事件类型 → 图标与颜色。未知类型退回一个中性图标，不至于渲染成空白。 */
function iconFor(kind: string) {
  if (kind === 'activity_completed') {
    return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
  }
  if (kind === 'course_started') {
    return <BookOpen className="w-3.5 h-3.5 text-indigo-600 shrink-0" />
  }
  if (kind === 'activity_opened') {
    return <PlayCircle className="w-3.5 h-3.5 text-gray-400 shrink-0" />
  }
  return <Activity className="w-3.5 h-3.5 text-gray-400 shrink-0" />
}

/** 只取 HH:MM，日期在同一天的居多，全量时间戳反而看不清。 */
function timeOf(at: string | null): string {
  if (!at) return ''
  const d = new Date(at)
  if (Number.isNaN(d.getTime())) return ''
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export default function RecentActivityCard() {
  const { t } = useTranslation()
  const org = useOrg() as any
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token
  const orgId: number = org?.id ?? 0

  const { data, isFetching, isError } = useQuery({
    queryKey: queryKeys.ext.learning.recent(orgId, DAYS),
    queryFn: () => getRecent(orgId, access_token, DAYS, MAX_ROWS * 3),
    enabled: !!orgId && !!access_token,
    staleTime: 60_000,
    // 学情工具可能没装（接口 404）或当前角色没权限（403）。这张卡片是锦上添花，
    // 失败就整块不显示，不要在概览页上摆一个红色错误框。
    retry: false,
  })

  // 首次加载画一条窄骨架，避免卡片突然跳出来把工具网格顶下去
  if (isFetching && !data) {
    return (
      <div className="bg-white nice-shadow rounded-xl p-5 max-w-[1600px] mx-auto w-full animate-pulse">
        <div className="h-3.5 bg-gray-200 rounded w-32 mb-4" />
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-3 bg-gray-100 rounded w-full my-3" />
        ))}
      </div>
    )
  }

  if (isError || !data) return null

  const events: RecentEvent[] = Array.isArray(data.events) ? data.events.slice(0, MAX_ROWS) : []
  if (events.length === 0) return null

  return (
    <div
      className="bg-white nice-shadow rounded-xl p-5 max-w-[1600px] mx-auto w-full"
      data-testid="sysu-recent-activity"
    >
      <div className="flex items-baseline justify-between gap-3 pb-3 min-w-0">
        <span className="font-semibold text-gray-800 text-sm truncate">
          {t('ext.overview.recent.title', { defaultValue: '最近学习动态' })}
        </span>
        <span className="text-gray-400 text-xs font-medium shrink-0">
          {t('ext.overview.recent.summary', {
            days: DAYS,
            learners: data.active_learner_count ?? 0,
            defaultValue: '近 {{days}} 天 {{learners}} 人在学',
          })}
        </span>
      </div>

      <ul className="divide-y divide-gray-50">
        {events.map((e, i) => (
          <li key={`${e.user_id}-${e.at}-${i}`} className="flex items-center gap-2 py-2 min-w-0">
            {iconFor(e.kind)}
            <span className="text-gray-800 text-xs font-semibold truncate shrink-0 max-w-[8rem]">
              {e.name || e.email || t('ext.overview.recent.someone', { defaultValue: '某位学员' })}
            </span>
            <span className="text-gray-400 text-xs truncate min-w-0">
              {e.activity_name || e.course_name || ''}
            </span>
            <span className="text-gray-400 text-xs ms-auto shrink-0 font-mono">
              {timeOf(e.at)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
