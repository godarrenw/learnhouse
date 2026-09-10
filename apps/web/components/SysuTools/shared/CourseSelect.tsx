'use client'
/**
 * 课程选择器。`courseScoped: true` 的工具由路由页统一渲染这个组件，
 * 工具组件自己不要再写一个选课下拉。
 *
 * 会把上次的选择记进 localStorage（按组织分 key），下次进来自动恢复。
 */
import React, { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BookOpen } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { useLHSession } from '@components/Contexts/LHSessionContext'
import { useOrg } from '@components/Contexts/OrgContext'
import { getOrgCourses } from '@services/courses/courses'
import { asArray } from '@services/utils/ts/requests'
import { queryKeys } from '@/lib/query/keys'

const STORAGE_PREFIX = 'sysu-tools:course:'

function readStored(orgSlug: string): string | undefined {
  try {
    return localStorage.getItem(STORAGE_PREFIX + orgSlug) || undefined
  } catch {
    return undefined
  }
}

function writeStored(orgSlug: string, uuid: string) {
  try {
    localStorage.setItem(STORAGE_PREFIX + orgSlug, uuid)
  } catch {
    /* 隐私模式下 localStorage 会抛，忽略即可 */
  }
}

interface CourseSelectProps {
  value?: string
  onChange: (_courseUuid: string) => void
}

export default function CourseSelect({ value, onChange }: CourseSelectProps) {
  const { t } = useTranslation()
  const org = useOrg() as any
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token
  const orgSlug: string = org?.slug ?? ''

  const { data, isFetching } = useQuery({
    queryKey: queryKeys.ext.courses(orgSlug),
    queryFn: () => getOrgCourses(orgSlug, null, access_token, true),
    enabled: !!orgSlug && !!access_token,
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  })

  const courses = useMemo(() => asArray<any>(data), [data])

  // 首次拿到课程列表后，恢复上次的选择；没有记录就选第一门。
  useEffect(() => {
    if (value || courses.length === 0 || !orgSlug) return
    const stored = readStored(orgSlug)
    const match = courses.find((c: any) => c.course_uuid === stored)
    onChange((match ?? courses[0]).course_uuid)
  }, [value, courses, orgSlug, onChange])

  function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const uuid = e.target.value
    if (orgSlug) writeStored(orgSlug, uuid)
    onChange(uuid)
  }

  return (
    <div className="pb-4 flex items-center gap-2 min-w-0">
      <BookOpen className="w-4 h-4 text-gray-400 shrink-0" />
      <label className="text-xs font-semibold text-gray-500 uppercase tracking-wider shrink-0">
        {t('ext.common.course', { defaultValue: '课程' })}
      </label>
      <select
        value={value ?? ''}
        onChange={handleChange}
        disabled={isFetching && courses.length === 0}
        aria-label={t('ext.common.select_course', { defaultValue: '选择课程' })}
        className="bg-white nice-shadow rounded-lg text-sm font-medium text-gray-800 px-3 py-1.5 min-w-0 max-w-full truncate outline-none cursor-pointer disabled:opacity-50"
      >
        {courses.length === 0 ? (
          <option value="">
            {isFetching
              ? t('ext.common.loading', { defaultValue: '正在加载…' })
              : t('ext.common.no_courses', { defaultValue: '该组织下还没有课程' })}
          </option>
        ) : (
          courses.map((course: any) => (
            <option key={course.course_uuid} value={course.course_uuid}>
              {course.name}
            </option>
          ))
        )}
      </select>
    </div>
  )
}
