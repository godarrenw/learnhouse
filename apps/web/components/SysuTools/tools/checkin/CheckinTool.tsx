'use client'
/**
 * 教学工具「上课签到」的主体：选课程 → 看历史场次 → 开一场新的 → 跳投屏页。
 *
 * 视觉沿用 UI_GUIDE 的后台规范（浅色、nice-shadow 卡片、手写表格、骨架屏、空态）。
 * 唯一的深色页面是投屏页 CheckinPresent。
 */
import React from 'react'
import { useRouter } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { CalendarCheck, Download, Monitor, Users } from 'lucide-react'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { useOrg } from '@components/Contexts/OrgContext'
import LearnHouseSpinner from '@components/Objects/Loaders/LearnHouseSpinner'
import ConfirmationModal from '@components/Objects/StyledElements/ConfirmationModal/ConfirmationModal'
import { getUriWithOrg } from '@services/config/config'
import { asArray } from '@services/utils/ts/requests'
import { queryKeys } from '@/lib/query/keys'
import type { SysuToolProps } from '@components/SysuTools/types'
import {
  CheckinSession,
  closeCheckinSession,
  createCheckinSession,
  downloadCheckinRecordsCsv,
  getCheckinSessions,
  readCheckinErrorMessage,
} from '@services/ext/checkin'

const REFRESH_MIN = 10
const REFRESH_MAX = 120
const REFRESH_DEFAULT = 20

export default function CheckinTool({ courseUuid: selected }: SysuToolProps) {
  // 未选课时按空串处理：所有 query 的 enabled 都会因此为 false，不会发请求
  const courseUuid = selected ?? ''
  const { t } = useTranslation()
  const router = useRouter()
  const org = useOrg() as any
  const orgslug = org?.slug
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token
  const queryClient = useQueryClient()

  const [title, setTitle] = React.useState('')
  const [refreshSeconds, setRefreshSeconds] = React.useState(REFRESH_DEFAULT)
  const [creating, setCreating] = React.useState(false)

  // 课程下拉由路由页统一渲染（registry 里 courseScoped: true），这里只收结果。

  const { data: sessionsData, isFetching } = useQuery({
    queryKey: queryKeys.checkin.sessions(courseUuid),
    queryFn: async () => {
      const res = await getCheckinSessions(courseUuid, access_token)
      if (!res.success) throw new Error(readCheckinErrorMessage(res.data))
      return res.data as CheckinSession[]
    },
    enabled: !!courseUuid && !!access_token,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  })

  const sessions = asArray<CheckinSession>(sessionsData)
  const isInitialLoading = !sessionsData && isFetching
  const isRefreshing = !!sessionsData && isFetching

  const nextDefaultTitle = t('ext.tools.checkin.tool.default_title', {
    defaultValue: '第 {{n}} 次课',
    n: sessions.length + 1,
  })

  async function handleStart() {
    if (!courseUuid) return
    setCreating(true)
    const toastId = toast.loading(
      t('ext.tools.checkin.tool.starting', { defaultValue: '正在开启签到…' })
    )
    const res = await createCheckinSession(
      courseUuid,
      { title: title.trim() || undefined, refresh_seconds: refreshSeconds },
      access_token
    )
    setCreating(false)
    if (!res.success) {
      toast.error(
        readCheckinErrorMessage(res.data) ||
          t('ext.tools.checkin.tool.start_error', { defaultValue: '开启失败' }),
        { id: toastId }
      )
      return
    }
    toast.success(
      t('ext.tools.checkin.tool.started', { defaultValue: '签到已开启' }),
      { id: toastId }
    )
    setTitle('')
    queryClient.invalidateQueries({
      queryKey: queryKeys.checkin.sessions(courseUuid),
    })
    router.push(
      getUriWithOrg(orgslug, '') +
        `/dash/tools/checkin/present/${res.data.session_uuid}`
    )
  }

  async function handleClose(sessionUuid: string) {
    const toastId = toast.loading(
      t('ext.tools.checkin.tool.closing', { defaultValue: '正在结束…' })
    )
    const res = await closeCheckinSession(sessionUuid, access_token)
    if (res.success) {
      queryClient.invalidateQueries({
        queryKey: queryKeys.checkin.sessions(courseUuid),
      })
      toast.success(t('ext.tools.checkin.tool.closed', { defaultValue: '已结束' }), {
        id: toastId,
      })
    } else {
      toast.error(
        readCheckinErrorMessage(res.data) ||
          t('ext.tools.checkin.tool.close_error', { defaultValue: '结束失败' }),
        { id: toastId }
      )
    }
  }

  async function handleExport(sessionUuid: string) {
    const toastId = toast.loading(
      t('ext.tools.checkin.tool.exporting', { defaultValue: '正在导出…' })
    )
    const ok = await downloadCheckinRecordsCsv(sessionUuid, access_token)
    if (ok) {
      toast.success(t('ext.tools.checkin.tool.exported', { defaultValue: '已导出 CSV' }), {
        id: toastId,
      })
    } else {
      toast.error(
        t('ext.tools.checkin.tool.export_error', { defaultValue: '导出失败' }),
        { id: toastId }
      )
    }
  }

  return (
    <div className="px-4 sm:px-10 pb-10 space-y-6">
      <div className="bg-white nice-shadow rounded-xl p-6 max-w-[1600px] mx-auto w-full">
        <div className="flex flex-col lg:flex-row lg:items-end gap-4">
          <div className="flex-1 min-w-0 space-y-1.5">
            <label
              htmlFor="checkin-title"
              className="block text-xs font-semibold text-gray-500 uppercase tracking-wider"
            >
              {t('ext.tools.checkin.tool.title_label', { defaultValue: '本次标题' })}
            </label>
            <input
              id="checkin-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={nextDefaultTitle}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-300"
              data-testid="checkin-title-input"
            />
          </div>

          <div className="flex-1 min-w-0 space-y-1.5">
            <label
              htmlFor="checkin-refresh"
              className="block text-xs font-semibold text-gray-500 uppercase tracking-wider"
            >
              {t('ext.tools.checkin.tool.refresh_label', {
                defaultValue: '刷新间隔 {{n}} 秒',
                n: refreshSeconds,
              })}
            </label>
            <input
              id="checkin-refresh"
              type="range"
              min={REFRESH_MIN}
              max={REFRESH_MAX}
              step={5}
              value={refreshSeconds}
              onChange={(e) => setRefreshSeconds(Number(e.target.value))}
              className="w-full accent-gray-900"
              data-testid="checkin-refresh-slider"
            />
          </div>

          <button
            onClick={handleStart}
            disabled={!courseUuid || creating}
            className="rounded-lg bg-black text-white px-5 py-2.5 text-sm font-semibold hover:bg-gray-800 disabled:opacity-40 transition-colors cursor-pointer shrink-0"
            data-testid="checkin-start"
          >
            {creating
              ? t('ext.tools.checkin.tool.starting', { defaultValue: '正在开启签到…' })
              : t('ext.tools.checkin.tool.start', { defaultValue: '开始签到' })}
          </button>
        </div>
      </div>

      <div className="bg-white nice-shadow rounded-xl overflow-hidden max-w-[1600px] mx-auto w-full">
        <div className="overflow-x-auto relative">
          {isInitialLoading ? (
            <div className="animate-pulse px-6 py-4">
              {Array.from({ length: 5 }).map((_, i) => (
                <div
                  key={i}
                  className="flex items-center gap-4 py-4 border-b border-gray-50"
                >
                  <div className="h-3.5 bg-gray-200 rounded w-40" />
                  <div className="h-3 bg-gray-100 rounded w-24" />
                  <div className="h-8 bg-gray-100 rounded-md w-20 ms-auto" />
                </div>
              ))}
            </div>
          ) : sessions.length === 0 ? (
            <div className="py-16 text-center" data-testid="checkin-empty">
              <div className="flex flex-col items-center gap-3">
                <div className="bg-gray-100 p-4 rounded-full">
                  <CalendarCheck className="w-8 h-8 text-gray-400" />
                </div>
                <p className="text-gray-400 text-sm font-medium">
                  {courseUuid
                    ? t('ext.tools.checkin.tool.empty', {
                        defaultValue: '这门课还没有签到记录',
                      })
                    : t('ext.tools.checkin.tool.pick_course', {
                        defaultValue: '先选择一门课程',
                      })}
                </p>
              </div>
            </div>
          ) : (
            <div className="relative">
              {isRefreshing && (
                <div className="absolute inset-0 bg-white/60 z-10 flex items-center justify-center rounded-lg">
                  <LearnHouseSpinner size={28} />
                </div>
              )}
              <table className="w-full" data-testid="checkin-sessions-table">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                      {t('ext.tools.checkin.tool.table.title', { defaultValue: '场次' })}
                    </th>
                    <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                      {t('ext.tools.checkin.tool.table.status', { defaultValue: '状态' })}
                    </th>
                    <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                      {t('ext.tools.checkin.tool.table.count', { defaultValue: '已签到' })}
                    </th>
                    <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                      {t('ext.tools.checkin.tool.table.started', {
                        defaultValue: '开始时间',
                      })}
                    </th>
                    <th className="text-end text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                      {t('ext.tools.checkin.tool.table.actions', { defaultValue: '操作' })}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {sessions.map((s) => (
                    <tr
                      key={s.session_uuid}
                      className="hover:bg-gray-50 transition-colors"
                    >
                      <td className="px-6 py-4">
                        <span className="font-semibold text-gray-800 text-sm">
                          {s.title}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        {s.status === 'open' ? (
                          <span className="bg-emerald-50 text-emerald-600 px-2 py-1 rounded-md text-xs font-medium">
                            {t('ext.tools.checkin.status.open', { defaultValue: '进行中' })}
                          </span>
                        ) : (
                          <span className="bg-gray-100 text-gray-500 px-2 py-1 rounded-md text-xs font-medium">
                            {t('ext.tools.checkin.status.closed', {
                              defaultValue: '已结束',
                            })}
                          </span>
                        )}
                      </td>
                      <td className="px-6 py-4">
                        <span className="inline-flex items-center gap-1.5 text-gray-800 font-semibold text-sm">
                          <Users className="w-3.5 h-3.5 text-gray-400" />
                          {s.checked_count}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <span className="text-gray-400 text-xs">
                          {s.started_at
                            ? s.started_at.slice(0, 19)
                            : '—'}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-end">
                        <div className="flex items-center justify-end gap-3">
                          {s.status === 'open' && (
                            <button
                              onClick={() =>
                                router.push(
                                  getUriWithOrg(orgslug, '') +
                                    `/dash/tools/checkin/present/${s.session_uuid}`
                                )
                              }
                              className="inline-flex items-center gap-1.5 text-xs font-medium text-indigo-600 hover:text-indigo-800 cursor-pointer"
                              data-testid="checkin-present-link"
                            >
                              <Monitor className="w-3.5 h-3.5" />
                              {t('ext.tools.checkin.tool.present', {
                                defaultValue: '投屏',
                              })}
                            </button>
                          )}
                          <button
                            onClick={() => handleExport(s.session_uuid)}
                            className="inline-flex items-center gap-1.5 text-xs font-medium text-gray-600 hover:text-gray-900 cursor-pointer"
                            data-testid="checkin-export"
                          >
                            <Download className="w-3.5 h-3.5" />
                            {t('ext.tools.checkin.tool.export', { defaultValue: '导出' })}
                          </button>
                          {s.status === 'open' && (
                            <ConfirmationModal
                              confirmationMessage={t(
                                'checkin.tool.close_confirm',
                                {
                                  defaultValue:
                                    '结束后学生无法再签到，记录仍会保留。',
                                }
                              )}
                              confirmationButtonText={t('ext.tools.checkin.tool.close', {
                                defaultValue: '结束',
                              })}
                              pendingButtonText={t('ext.tools.checkin.tool.closing', {
                                defaultValue: '正在结束…',
                              })}
                              dialogTitle={t('ext.tools.checkin.tool.close_title', {
                                defaultValue: '结束这场签到？',
                              })}
                              functionToExecute={() =>
                                handleClose(s.session_uuid)
                              }
                              status="warning"
                              dialogTrigger={
                                <button
                                  className="text-xs font-medium text-red-600 hover:text-red-800 cursor-pointer"
                                  data-testid="checkin-close"
                                >
                                  {t('ext.tools.checkin.tool.close', {
                                    defaultValue: '结束',
                                  })}
                                </button>
                              }
                            />
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
