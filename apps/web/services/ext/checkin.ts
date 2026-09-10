/**
 * 上课签到（SYSU-SAM 扩展）的 API 封装。
 *
 * 写操作统一返回 `getResponseMetadata` 的 `{ success, data, status }`，
 * 错误码在 `data.detail.code`（后端约定，见 apps/api/src/services/ext/checkin）。
 */
import { getAPIUrl } from '@services/config/config'
import {
  RequestBodyWithAuthHeader,
  getResponseMetadata,
} from '@services/utils/ts/requests'

export type CheckinErrorCode =
  | 'already_checked_in'
  | 'invalid_or_expired_code'
  | 'session_closed'
  | 'session_not_found'
  | 'not_org_member'
  | 'rate_limited'
  | 'missing_credential'
  | 'invalid_refresh_seconds'

export type CheckinSession = {
  session_uuid: string
  title: string
  org_id: number
  course_id: number
  course_uuid: string
  course_name: string
  created_by: number
  status: 'open' | 'closed'
  refresh_seconds: number
  code_length: number
  started_at: string
  closed_at: string | null
  checked_count: number
}

export type CheckinRecord = {
  user_id: number
  full_name: string
  username: string
  email: string
  checked_at: string
  method: 'qr' | 'code'
  ip: string
}

export type CheckinLive = {
  session_uuid: string
  title: string
  course_name: string
  status: 'open' | 'closed'
  refresh_seconds: number
  token: string
  code: string
  seconds_remaining: number
  checked_count: number
  recent: CheckinRecord[]
}

export type CheckinPublicSession = {
  session_uuid: string
  title: string
  course_uuid: string
  course_name: string
  status: 'open' | 'closed'
  refresh_seconds: number
  code_length: number
  already_checked_in: boolean
}

/** 从后端错误体里取出机器可读的错误码，取不到时返回 null。 */
export function readCheckinErrorCode(data: any): CheckinErrorCode | null {
  const detail = data?.detail
  if (detail && typeof detail === 'object' && typeof detail.code === 'string') {
    return detail.code as CheckinErrorCode
  }
  return null
}

/** 取出可直接展示的错误文案（拿不到 i18n 映射时的兜底）。 */
export function readCheckinErrorMessage(data: any): string {
  const detail = data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
    return detail.message
  }
  return ''
}

async function get(url: string, access_token: string) {
  const result: any = await fetch(
    url,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  )
  return await getResponseMetadata(result)
}

export async function createCheckinSession(
  courseUuid: string,
  body: { title?: string; refresh_seconds: number },
  access_token: string
) {
  const result: any = await fetch(
    `${getAPIUrl()}ext/checkin/courses/${courseUuid}/sessions`,
    RequestBodyWithAuthHeader('POST', body, null, access_token)
  )
  return await getResponseMetadata(result)
}

export async function getCheckinSessions(courseUuid: string, access_token: string) {
  return await get(
    `${getAPIUrl()}ext/checkin/courses/${courseUuid}/sessions`,
    access_token
  )
}

export async function getCheckinLive(sessionUuid: string, access_token: string) {
  return await get(
    `${getAPIUrl()}ext/checkin/sessions/${sessionUuid}/live`,
    access_token
  )
}

export async function closeCheckinSession(
  sessionUuid: string,
  access_token: string
) {
  const result: any = await fetch(
    `${getAPIUrl()}ext/checkin/sessions/${sessionUuid}/close`,
    RequestBodyWithAuthHeader('POST', null, null, access_token)
  )
  return await getResponseMetadata(result)
}

export async function getCheckinRecords(
  sessionUuid: string,
  access_token: string
) {
  return await get(
    `${getAPIUrl()}ext/checkin/sessions/${sessionUuid}/records`,
    access_token
  )
}

/**
 * 下载 CSV。浏览器沙箱里 `<a download>` 对跨源响应不生效，所以先取 blob 再触发。
 */
export async function downloadCheckinRecordsCsv(
  sessionUuid: string,
  access_token: string
): Promise<boolean> {
  const response = await fetch(
    `${getAPIUrl()}ext/checkin/sessions/${sessionUuid}/records?format=csv`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  )
  if (!response.ok) return false
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `checkin_${sessionUuid}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
  return true
}

export async function getPublicCheckinSession(
  sessionUuid: string,
  access_token: string
) {
  return await get(
    `${getAPIUrl()}ext/checkin/sessions/${sessionUuid}/public`,
    access_token
  )
}

export async function submitCheckin(
  sessionUuid: string,
  body: { token?: string; code?: string },
  access_token: string
) {
  const result: any = await fetch(
    `${getAPIUrl()}ext/checkin/sessions/${sessionUuid}/check`,
    RequestBodyWithAuthHeader('POST', body, null, access_token)
  )
  return await getResponseMetadata(result)
}

export async function getMyOpenCheckin(courseUuid: string, access_token: string) {
  return await get(
    `${getAPIUrl()}ext/checkin/my/open?course_uuid=${encodeURIComponent(courseUuid)}`,
    access_token
  )
}
