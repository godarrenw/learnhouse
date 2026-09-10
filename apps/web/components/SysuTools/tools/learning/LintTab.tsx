'use client'
/** 课程体检：按级别着色的结论列表，外加「一键发布未发布活动」。 */
import React from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { AlertTriangle, Info, ShieldCheck, XCircle } from 'lucide-react'

import { useLHSession } from '@components/Contexts/LHSessionContext'
import { useOrg } from '@components/Contexts/OrgContext'
import useAdminStatus from '@components/Hooks/useAdminStatus'
import ConfirmDanger from '@components/SysuTools/shared/ConfirmDanger'
import { queryKeys } from '@/lib/query/keys'
import { cn } from '@/lib/utils'
import { fixPublish, getLint, LintFinding } from '@services/ext/learning'

import { NeedCourse, ToolBody, Toolbar } from './shared'

const LEVEL_STYLE: Record<string, { row: string; badge: string; Icon: React.ComponentType<any> }> = {
  error: { row: 'border-s-4 border-red-500', badge: 'bg-red-50 text-red-600', Icon: XCircle },
  warn: {
    row: 'border-s-4 border-amber-500',
    badge: 'bg-amber-50 text-amber-600',
    Icon: AlertTriangle,
  },
  info: { row: 'border-s-4 border-blue-400', badge: 'bg-blue-50 text-blue-600', Icon: Info },
}

export default function LintTab({ courseUuid }: { courseUuid?: string }) {
  const { t } = useTranslation()
  const org = useOrg() as any
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token
  const orgId: number = org?.id ?? 0
  const queryClient = useQueryClient()
  const { rights } = useAdminStatus()
  // 后端这个写操作要求对课程有 update 权限，前端按同一口径决定按钮显不显示
  const canUpdate = rights?.courses?.action_update === true

  const { data, isFetching } = useQuery({
    queryKey: queryKeys.ext.learning.lint(courseUuid ?? ''),
    queryFn: () => getLint(courseUuid as string, orgId, access_token),
    enabled: !!courseUuid && !!orgId && !!access_token,
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  })

  const findings: LintFinding[] = data?.findings ?? []
  const counts = data?.counts ?? { error: 0, warn: 0, info: 0 }
  const fixableCount: number = data?.fixable_count ?? 0

  async function handleFixPublish() {
    const toastId = toast.loading(t('ext.tools.learning.lint.publishing'))
    const result = await fixPublish(courseUuid as string, orgId, access_token)
    if (result.success) {
      queryClient.invalidateQueries({
        queryKey: queryKeys.ext.learning.lint(courseUuid ?? ''),
      })
      toast.success(
        t('ext.tools.learning.lint.publish_done', {
          published: result.data?.published_count ?? 0,
          skipped: result.data?.skipped_count ?? 0,
        }),
        { id: toastId }
      )
    } else {
      toast.error(result.data?.detail || t('ext.tools.learning.lint.publish_error'), {
        id: toastId,
      })
    }
  }

  if (!courseUuid) {
    return <NeedCourse message={t('ext.common.course_required')} />
  }

  const isInitialLoading = !data && isFetching

  return (
    <>
      <Toolbar
        start={
          <div className="flex flex-wrap items-center gap-2" data-testid="learning-lint-counts">
            {(['error', 'warn', 'info'] as const).map((level) => (
              <span
                key={level}
                className={cn('px-2 py-1 rounded-md text-xs font-medium', LEVEL_STYLE[level].badge)}
              >
                {t(`ext.tools.learning.lint.level_${level}`)}：{counts[level] ?? 0}
              </span>
            ))}
          </div>
        }
        end={
          canUpdate && fixableCount > 0 ? (
            <ConfirmDanger
              title={t('ext.tools.learning.lint.publish_title')}
              message={t('ext.tools.learning.lint.publish_confirm')}
              confirmText={t('ext.tools.learning.lint.publish_button')}
              onConfirm={handleFixPublish}
              status="warning"
              trigger={
                <button
                  type="button"
                  data-testid="learning-fix-publish"
                  className="inline-flex items-center gap-1.5 text-xs font-medium text-white bg-red-500 hover:bg-red-600 rounded-md px-3 py-2 transition-colors cursor-pointer"
                >
                  {t('ext.tools.learning.lint.publish_action', { count: fixableCount })}
                </button>
              }
            />
          ) : null
        }
      />
      <ToolBody>
        <div className="bg-white nice-shadow rounded-xl overflow-hidden max-w-[1600px] mx-auto w-full">
          {isInitialLoading ? (
            <div className="animate-pulse px-6 py-4" data-testid="learning-skeleton">
              {Array.from({ length: 5 }).map((_, index) => (
                <div
                  key={index}
                  className="flex items-center gap-4 py-4 border-b border-gray-50 last:border-b-0"
                >
                  <div className="h-3.5 bg-gray-200 rounded w-64" />
                  <div className="h-3 bg-gray-100 rounded w-24 ms-auto" />
                </div>
              ))}
            </div>
          ) : findings.length === 0 ? (
            <div className="py-16 text-center" data-testid="learning-empty">
              <div className="flex flex-col items-center gap-3">
                <div className="bg-gray-100 p-4 rounded-full">
                  <ShieldCheck className="w-8 h-8 text-gray-400" />
                </div>
                <p className="text-gray-400 text-sm font-medium">
                  {t('ext.tools.learning.lint.clean')}
                </p>
              </div>
            </div>
          ) : (
            <ul className="divide-y divide-gray-50" data-testid="learning-lint-list">
              {findings.map((finding, index) => {
                const style = LEVEL_STYLE[finding.level] ?? LEVEL_STYLE.info
                const Icon = style.Icon
                return (
                  <li
                    key={`${finding.code}-${index}`}
                    className={cn('px-6 py-4 flex items-start gap-3 min-w-0', style.row)}
                  >
                    <Icon className={cn('w-4 h-4 shrink-0 mt-0.5', style.badge, 'bg-transparent')} />
                    <div className="min-w-0 flex-1">
                      <div className="text-gray-800 font-semibold text-sm">{finding.message}</div>
                      {finding.fix_hint ? (
                        <div className="text-gray-400 text-xs mt-1">{finding.fix_hint}</div>
                      ) : null}
                    </div>
                    <span
                      className={cn(
                        'px-2 py-1 rounded-md text-xs font-medium shrink-0',
                        style.badge
                      )}
                    >
                      {finding.code}
                    </span>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </ToolBody>
    </>
  )
}
