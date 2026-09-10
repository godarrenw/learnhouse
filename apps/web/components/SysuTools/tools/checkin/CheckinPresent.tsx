'use client'
/**
 * 投屏页主体。
 *
 * 这是整个 fork 里**唯一**允许不用后台灰白配色的页面：它要在教室投影上从最后一排
 * 看清，所以用深色高对比配色。其余教学工具页面一律沿用 UI_GUIDE 的浅色规范。
 *
 * 实时数据用 react-query 每秒轮询 `/live`，而不是 SSE —— 投屏页只有教师一个人开着，
 * 一秒一次的 JSON 请求量可以忽略，而 SSE 在 NAS 反代加 Cloudflare 隧道的链路上要额外
 * 处理缓冲与超时断连，收益不抵成本。
 */
import React from 'react'
import { useRouter } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Users, X } from 'lucide-react'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import ConfirmationModal from '@components/Objects/StyledElements/ConfirmationModal/ConfirmationModal'
import { getAbsoluteUriWithOrg, getUriWithOrg } from '@services/config/config'
import { queryKeys } from '@/lib/query/keys'
import {
  CheckinLive,
  closeCheckinSession,
  getCheckinLive,
  readCheckinErrorMessage,
} from '@services/ext/checkin'
import CheckinQrCode from './CheckinQrCode'

type Props = {
  orgslug: string
  sessionUuid: string
}

function CountdownRing({ value, total }: { value: number; total: number }) {
  const radius = 26
  const circumference = 2 * Math.PI * radius
  const ratio = total > 0 ? Math.min(1, Math.max(0, value / total)) : 0
  return (
    <svg width="64" height="64" viewBox="0 0 64 64" aria-hidden="true">
      <circle
        cx="32"
        cy="32"
        r={radius}
        fill="none"
        stroke="rgba(255,255,255,0.15)"
        strokeWidth="6"
      />
      <circle
        cx="32"
        cy="32"
        r={radius}
        fill="none"
        stroke="#4ade80"
        strokeWidth="6"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - ratio)}
        transform="rotate(-90 32 32)"
        style={{ transition: 'stroke-dashoffset 0.9s linear' }}
      />
      <text
        x="32"
        y="38"
        textAnchor="middle"
        fill="#ffffff"
        fontSize="20"
        fontWeight="700"
      >
        {value}
      </text>
    </svg>
  )
}

export default function CheckinPresent({ orgslug, sessionUuid }: Props) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token

  const { data, isFetching, error } = useQuery({
    queryKey: queryKeys.checkin.live(sessionUuid),
    queryFn: async () => {
      const res = await getCheckinLive(sessionUuid, access_token)
      if (!res.success) throw new Error(readCheckinErrorMessage(res.data))
      return res.data as CheckinLive
    },
    enabled: !!sessionUuid && !!access_token,
    refetchInterval: 1000,
    refetchIntervalInBackground: true,
    staleTime: 0,
    placeholderData: (prev) => prev,
  })

  const live = data as CheckinLive | undefined
  const isInitialLoading = !live && isFetching
  const isOpen = live?.status === 'open'

  const checkinUrl = React.useMemo(() => {
    if (!live?.token) return ''
    return getAbsoluteUriWithOrg(
      orgslug,
      `/checkin/${sessionUuid}?t=${encodeURIComponent(live.token)}`
    )
  }, [orgslug, sessionUuid, live?.token])

  async function handleClose() {
    const toastId = toast.loading(
      t('ext.tools.checkin.present.closing', { defaultValue: '正在结束…' })
    )
    const res = await closeCheckinSession(sessionUuid, access_token)
    if (res.success) {
      queryClient.invalidateQueries({
        queryKey: queryKeys.checkin.live(sessionUuid),
      })
      toast.success(
        t('ext.tools.checkin.present.closed', { defaultValue: '签到已结束' }),
        { id: toastId }
      )
      router.push(getUriWithOrg(orgslug, '') + '/dash/tools/checkin')
    } else {
      toast.error(
        readCheckinErrorMessage(res.data) ||
          t('ext.tools.checkin.present.close_error', { defaultValue: '结束失败' }),
        { id: toastId }
      )
    }
  }

  return (
    <div
      className="fixed inset-0 bg-[#0b0f19] text-white overflow-y-auto"
      style={{ zIndex: 'var(--z-overlay)' }}
      data-testid="checkin-present"
    >
      <div className="min-h-full flex flex-col px-6 py-6 sm:px-12 sm:py-10">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-white/50 text-sm sm:text-base truncate">
              {live?.course_name || ''}
            </div>
            <div className="text-2xl sm:text-4xl font-bold tracking-tight truncate">
              {live?.title ||
                t('ext.tools.checkin.present.title', { defaultValue: '课堂签到' })}
            </div>
          </div>
          <ConfirmationModal
            confirmationMessage={t('ext.tools.checkin.present.close_confirm', {
              defaultValue: '结束后学生无法再签到，记录仍会保留。',
            })}
            confirmationButtonText={t('ext.tools.checkin.present.close', {
              defaultValue: '结束签到',
            })}
            pendingButtonText={t('ext.tools.checkin.present.closing', {
              defaultValue: '正在结束…',
            })}
            dialogTitle={t('ext.tools.checkin.present.close_title', {
              defaultValue: '结束本次签到？',
            })}
            functionToExecute={handleClose}
            status="warning"
            dialogTrigger={
              <button
                className="flex items-center gap-2 rounded-full bg-white/10 hover:bg-white/20 px-4 py-2 text-sm font-medium cursor-pointer transition-colors"
                data-testid="checkin-present-close"
              >
                <X className="w-4 h-4" />
                {t('ext.tools.checkin.present.close', { defaultValue: '结束签到' })}
              </button>
            }
          />
        </div>

        {isInitialLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="animate-pulse h-64 w-64 rounded-2xl bg-white/10" />
          </div>
        ) : error ? (
          <div className="flex-1 flex items-center justify-center text-white/60">
            {t('ext.tools.checkin.present.load_error', {
              defaultValue: '加载失败，请刷新页面',
            })}
          </div>
        ) : (
          <div className="flex-1 flex flex-col lg:flex-row gap-8 lg:gap-12 items-center lg:items-stretch justify-center pt-8">
            <div className="flex flex-col items-center gap-6">
              {isOpen ? (
                <div className="bg-white p-4 sm:p-6 rounded-3xl">
                  <CheckinQrCode value={checkinUrl} size={340} />
                </div>
              ) : (
                <div className="bg-white/10 rounded-3xl w-[340px] max-w-full aspect-square flex items-center justify-center text-white/50 text-lg px-6 text-center">
                  {t('ext.tools.checkin.present.session_closed', {
                    defaultValue: '本次签到已结束',
                  })}
                </div>
              )}

              {isOpen && (
                <div className="flex items-center gap-6">
                  <div className="text-center">
                    <div className="text-white/50 text-sm mb-1">
                      {t('ext.tools.checkin.present.code_label', { defaultValue: '口令' })}
                    </div>
                    <div
                      className="font-mono font-bold tracking-[0.25em] text-5xl sm:text-7xl"
                      data-testid="checkin-present-code"
                    >
                      {live?.code}
                    </div>
                  </div>
                  <CountdownRing
                    value={live?.seconds_remaining ?? 0}
                    total={live?.refresh_seconds ?? 20}
                  />
                </div>
              )}
            </div>

            <div className="w-full lg:w-[380px] flex flex-col">
              <div className="flex items-center gap-3 pb-4">
                <Users className="w-6 h-6 text-white/50" />
                <span
                  className="text-4xl sm:text-5xl font-bold"
                  data-testid="checkin-present-count"
                >
                  {live?.checked_count ?? 0}
                </span>
                <span className="text-white/50 text-lg">
                  {t('ext.tools.checkin.present.checked', { defaultValue: '人已签到' })}
                </span>
              </div>
              <div className="flex-1 rounded-2xl bg-white/5 p-4 overflow-y-auto max-h-[46vh]">
                {(live?.recent?.length ?? 0) === 0 ? (
                  <div className="h-full flex items-center justify-center text-white/40 text-sm py-10">
                    {t('ext.tools.checkin.present.no_one_yet', {
                      defaultValue: '还没有人签到',
                    })}
                  </div>
                ) : (
                  <ul className="space-y-2" data-testid="checkin-present-list">
                    {live?.recent?.map((record) => (
                      <li
                        key={`${record.user_id}-${record.checked_at}`}
                        className="flex items-center justify-between gap-3 rounded-xl bg-white/5 px-4 py-3"
                      >
                        <span className="truncate text-lg">
                          {record.full_name || record.username}
                        </span>
                        <span className="text-white/40 text-xs shrink-0">
                          {record.method === 'code'
                            ? t('ext.tools.checkin.method.code', { defaultValue: '口令' })
                            : t('ext.tools.checkin.method.qr', { defaultValue: '扫码' })}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>
        )}

        <div className="pt-8 text-center text-white/40 text-sm sm:text-base">
          {t('ext.tools.checkin.present.hint', {
            defaultValue: '用手机扫码，或在课程页输入口令签到',
          })}
        </div>
      </div>
    </div>
  )
}
