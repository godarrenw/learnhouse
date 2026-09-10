'use client'
/**
 * 学生扫码后落地的签到页 `/checkin/<session>?t=<token>`。
 *
 * 未登录 → 引导去登录并带 `?next=` 回跳（token 留在 URL 里，登录回来后自动提交）。
 * 已登录 → 显示课程名与「确认签到」按钮；也可以手输投屏上的口令。
 * 结果分四种状态：成功 / 已签过 / 口令过期或无效 / 会话已关闭。
 */
import React from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, CircleAlert, Clock, LogIn, MapPin } from 'lucide-react'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import GeneralWrapperStyled from '@components/Objects/StyledElements/Wrappers/GeneralWrapper'
import LearnHouseSpinner from '@components/Objects/Loaders/LearnHouseSpinner'
import { getUriWithOrg } from '@services/config/config'
import { queryKeys } from '@/lib/query/keys'
import {
  CheckinErrorCode,
  CheckinPublicSession,
  getPublicCheckinSession,
  readCheckinErrorCode,
  readCheckinErrorMessage,
  submitCheckin,
} from '@services/ext/checkin'

type Props = {
  orgslug: string
  sessionUuid: string
}

type Outcome =
  | { kind: 'idle' }
  | { kind: 'ok' }
  | { kind: 'error'; code: CheckinErrorCode | null; message: string }

export default function CheckinClient({ orgslug, sessionUuid }: Props) {
  const { t } = useTranslation()
  const searchParams = useSearchParams()
  const tokenFromUrl = searchParams.get('t') || ''
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token
  const authStatus = session?.status

  const [code, setCode] = React.useState('')
  const [submitting, setSubmitting] = React.useState(false)
  const [outcome, setOutcome] = React.useState<Outcome>({ kind: 'idle' })
  const autoSubmitted = React.useRef(false)

  const { data, isFetching } = useQuery({
    queryKey: queryKeys.checkin.publicSession(sessionUuid),
    queryFn: async () => {
      const res = await getPublicCheckinSession(sessionUuid, access_token)
      if (!res.success) throw new Error(readCheckinErrorMessage(res.data))
      return res.data as CheckinPublicSession
    },
    enabled: !!sessionUuid && !!access_token,
    staleTime: 10_000,
  })

  const info = data as CheckinPublicSession | undefined

  const doSubmit = React.useCallback(
    async (body: { token?: string; code?: string }) => {
      setSubmitting(true)
      const res = await submitCheckin(sessionUuid, body, access_token)
      setSubmitting(false)
      if (res.success) {
        setOutcome({ kind: 'ok' })
        return
      }
      setOutcome({
        kind: 'error',
        code: readCheckinErrorCode(res.data),
        message: readCheckinErrorMessage(res.data),
      })
    },
    [sessionUuid, access_token]
  )

  // 扫码进来且会话开放时自动提交一次，学生不用再点一下。
  // 提交推到微任务里发，避免在 effect 体内同步 setState 引起级联渲染。
  React.useEffect(() => {
    if (autoSubmitted.current) return
    if (!access_token || !tokenFromUrl || !info) return
    if (info.status !== 'open' || info.already_checked_in) return
    autoSubmitted.current = true
    let cancelled = false
    const run = async () => {
      await Promise.resolve()
      if (!cancelled) await doSubmit({ token: tokenFromUrl })
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [access_token, tokenFromUrl, info, doSubmit])

  // ---- 未登录 ----------------------------------------------------------
  if (authStatus === 'loading') {
    return (
      <GeneralWrapperStyled>
        <div className="py-20 flex justify-center">
          <LearnHouseSpinner size={28} />
        </div>
      </GeneralWrapperStyled>
    )
  }

  if (!access_token) {
    const next = `/orgs/${orgslug}/checkin/${sessionUuid}${
      tokenFromUrl ? `?t=${encodeURIComponent(tokenFromUrl)}` : ''
    }`
    return (
      <GeneralWrapperStyled>
        <Card
          icon={<LogIn className="w-7 h-7 text-gray-400" />}
          title={t('ext.tools.checkin.student.login_needed', {
            defaultValue: '请先登录再签到',
          })}
          description={t('ext.tools.checkin.student.login_hint', {
            defaultValue: '签到会绑定到你的账号，登录后会自动回到这个页面。',
          })}
        >
          <Link
            href={`/auth/login?next=${encodeURIComponent(next)}`}
            className="inline-flex items-center justify-center rounded-lg bg-black text-white px-5 py-2.5 text-sm font-semibold hover:bg-gray-800 transition-colors"
            data-testid="checkin-login-link"
          >
            {t('ext.tools.checkin.student.login', { defaultValue: '去登录' })}
          </Link>
        </Card>
      </GeneralWrapperStyled>
    )
  }

  // ---- 加载中 ----------------------------------------------------------
  if (!info && isFetching) {
    return (
      <GeneralWrapperStyled>
        <div className="max-w-md mx-auto py-10">
          <div className="animate-pulse bg-white nice-shadow rounded-xl p-8 space-y-4">
            <div className="h-4 bg-gray-200 rounded w-32" />
            <div className="h-6 bg-gray-200 rounded w-56" />
            <div className="h-10 bg-gray-100 rounded-lg w-full" />
          </div>
        </div>
      </GeneralWrapperStyled>
    )
  }

  if (!info) {
    return (
      <GeneralWrapperStyled>
        <Card
          icon={<CircleAlert className="w-7 h-7 text-gray-400" />}
          title={t('ext.tools.checkin.error.session_not_found', {
            defaultValue: '找不到这场签到',
          })}
          description={t('ext.tools.checkin.student.check_link', {
            defaultValue: '二维码可能已经失效，请向老师确认。',
          })}
        />
      </GeneralWrapperStyled>
    )
  }

  const courseHref = getUriWithOrg(orgslug, `/course/${info.course_uuid}`)

  // ---- 结果态 ----------------------------------------------------------
  if (outcome.kind === 'ok' || info.already_checked_in) {
    const alreadyOnly = outcome.kind !== 'ok'
    return (
      <GeneralWrapperStyled>
        <Card
          icon={<CheckCircle2 className="w-7 h-7 text-emerald-600" />}
          title={
            alreadyOnly
              ? t('ext.tools.checkin.result.already', { defaultValue: '你已经签过到了' })
              : t('ext.tools.checkin.result.ok', { defaultValue: '签到成功' })
          }
          description={`${info.course_name} · ${info.title}`}
          testId="checkin-result-ok"
        >
          <Link
            href={courseHref}
            className="text-sm font-medium text-indigo-600 hover:text-indigo-800"
          >
            {t('ext.tools.checkin.student.back_to_course', { defaultValue: '回到课程' })}
          </Link>
        </Card>
      </GeneralWrapperStyled>
    )
  }

  if (
    info.status !== 'open' ||
    (outcome.kind === 'error' && outcome.code === 'session_closed')
  ) {
    return (
      <GeneralWrapperStyled>
        <Card
          icon={<Clock className="w-7 h-7 text-gray-400" />}
          title={t('ext.tools.checkin.result.closed', { defaultValue: '本次签到已结束' })}
          description={`${info.course_name} · ${info.title}`}
          testId="checkin-result-closed"
        >
          <Link
            href={courseHref}
            className="text-sm font-medium text-indigo-600 hover:text-indigo-800"
          >
            {t('ext.tools.checkin.student.back_to_course', { defaultValue: '回到课程' })}
          </Link>
        </Card>
      </GeneralWrapperStyled>
    )
  }

  // ---- 待签到 ----------------------------------------------------------
  const errorText =
    outcome.kind === 'error'
      ? errorTextFor(t, outcome.code, outcome.message)
      : ''

  return (
    <GeneralWrapperStyled>
      <div className="max-w-md mx-auto py-8" data-testid="checkin-form">
        <div className="bg-white nice-shadow rounded-xl p-7 space-y-5">
          <div className="flex items-center gap-3">
            <div className="bg-gray-100 p-3 rounded-full">
              <MapPin className="w-6 h-6 text-gray-500" />
            </div>
            <div className="min-w-0">
              <div className="text-xs text-gray-400 truncate">
                {info.course_name}
              </div>
              <div className="text-lg font-bold tracking-tight truncate">
                {info.title}
              </div>
            </div>
          </div>

          {errorText && (
            <div
              className="rounded-lg bg-red-50 text-red-600 text-sm px-4 py-3"
              data-testid="checkin-error"
            >
              {errorText}
            </div>
          )}

          {tokenFromUrl && (
            <button
              onClick={() => doSubmit({ token: tokenFromUrl })}
              disabled={submitting}
              className="w-full rounded-lg bg-black text-white px-5 py-3 text-sm font-semibold hover:bg-gray-800 disabled:opacity-50 transition-colors cursor-pointer"
              data-testid="checkin-confirm"
            >
              {submitting
                ? t('ext.tools.checkin.student.submitting', { defaultValue: '正在签到…' })
                : t('ext.tools.checkin.student.confirm', { defaultValue: '确认签到' })}
            </button>
          )}

          <div className="space-y-2">
            <label
              htmlFor="checkin-code"
              className="block text-xs font-medium text-gray-500"
            >
              {t('ext.tools.checkin.student.code_label', {
                defaultValue: '或输入屏幕上的口令',
              })}
            </label>
            <div className="flex gap-2">
              <input
                id="checkin-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={info.code_length}
                value={code}
                onChange={(e) =>
                  setCode(e.target.value.replace(/\D/g, '').slice(0, info.code_length))
                }
                placeholder={'0'.repeat(info.code_length)}
                className="flex-1 min-w-0 rounded-lg border border-gray-200 px-4 py-2.5 font-mono tracking-[0.3em] text-center focus:outline-none focus:ring-2 focus:ring-gray-300"
                data-testid="checkin-code-input"
              />
              <button
                onClick={() => doSubmit({ code })}
                disabled={submitting || code.length !== info.code_length}
                className="rounded-lg bg-gray-900 text-white px-5 py-2.5 text-sm font-semibold hover:bg-gray-700 disabled:opacity-40 transition-colors cursor-pointer shrink-0"
                data-testid="checkin-code-submit"
              >
                {t('ext.tools.checkin.student.submit_code', { defaultValue: '签到' })}
              </button>
            </div>
          </div>
        </div>
      </div>
    </GeneralWrapperStyled>
  )
}

function errorTextFor(
  t: (_key: string, _options?: any) => string,
  code: CheckinErrorCode | null,
  fallback: string
) {
  switch (code) {
    case 'invalid_or_expired_code':
      return t('ext.tools.checkin.error.invalid_or_expired_code', {
        defaultValue: '口令已经过期或不正确，看一眼屏幕上的最新口令再试。',
      })
    case 'already_checked_in':
      return t('ext.tools.checkin.error.already_checked_in', {
        defaultValue: '你已经签过到了。',
      })
    case 'session_closed':
      return t('ext.tools.checkin.error.session_closed', {
        defaultValue: '本次签到已经结束。',
      })
    case 'not_org_member':
      return t('ext.tools.checkin.error.not_org_member', {
        defaultValue: '你不在这个组织里，无法签到。',
      })
    case 'rate_limited':
      return t('ext.tools.checkin.error.rate_limited', {
        defaultValue: '提交太频繁，等一秒再试。',
      })
    default:
      return (
        fallback ||
        t('ext.tools.checkin.error.unknown', { defaultValue: '签到失败，请重试。' })
      )
  }
}

function Card({
  icon,
  title,
  description,
  children,
  testId,
}: {
  icon: React.ReactNode
  title: string
  description?: string
  children?: React.ReactNode
  testId?: string
}) {
  return (
    <div className="max-w-md mx-auto py-10" data-testid={testId}>
      <div className="bg-white nice-shadow rounded-xl p-8 flex flex-col items-center text-center gap-4">
        <div className="bg-gray-100 p-4 rounded-full">{icon}</div>
        <div className="space-y-1 min-w-0">
          <div className="text-xl font-bold tracking-tight">{title}</div>
          {description && (
            <div className="text-sm text-gray-400">{description}</div>
          )}
        </div>
        {children}
      </div>
    </div>
  )
}
