'use client'
/**
 * 学生端入口条：该课程当前有开放中的签到时，在课程页与活动页顶部显示
 * 「📍 本节课签到」。没有开放场次、未登录、或者已经签过，都不渲染任何东西。
 */
import React from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ChevronRight, MapPin } from 'lucide-react'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { getUriWithOrg } from '@services/config/config'
import { queryKeys } from '@/lib/query/keys'
import { CheckinPublicSession, getMyOpenCheckin } from '@services/ext/checkin'

type Props = {
  orgslug: string
  courseUuid?: string
}

export default function CheckinBanner({ orgslug, courseUuid }: Props) {
  const { t } = useTranslation()
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token

  const { data } = useQuery({
    queryKey: queryKeys.checkin.openForCourse(courseUuid ?? ''),
    queryFn: async () => {
      const res = await getMyOpenCheckin(courseUuid as string, access_token)
      // 学生不在这个组织、或者课程不存在时静默返回空，入口条不该把错误抛到课程页上
      if (!res.success) return null
      return (res.data as CheckinPublicSession) ?? null
    },
    enabled: !!courseUuid && !!access_token,
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: false,
  })

  const open = data as CheckinPublicSession | null | undefined
  if (!open || open.status !== 'open' || open.already_checked_in) return null

  return (
    <Link
      href={getUriWithOrg(orgslug, `/checkin/${open.session_uuid}`)}
      className="flex items-center gap-3 rounded-xl bg-emerald-50 hover:bg-emerald-100 px-4 py-3 mb-4 transition-colors group"
      data-testid="checkin-banner"
    >
      <MapPin className="w-5 h-5 text-emerald-600 shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold text-emerald-900 truncate">
          {t('ext.tools.checkin.banner.title', { defaultValue: '本节课签到' })}
        </div>
        <div className="text-xs text-emerald-700/70 truncate">{open.title}</div>
      </div>
      <ChevronRight className="w-4 h-4 text-emerald-600 shrink-0 group-hover:translate-x-0.5 transition-transform" />
    </Link>
  )
}
