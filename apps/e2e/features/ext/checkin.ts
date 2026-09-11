/**
 * 上课签到的 API 辅助 —— 只做 e2e 的种子数据与读回断言，页面操作留给 spec。
 *
 * 之所以要这一层：投屏上的二维码和口令是服务端每隔 refresh_seconds 秒轮换的，
 * 浏览器里没法「解码二维码」，所以用教师身份读一次 `/live` 拿到当前窗口的
 * token 与口令——这跟学生用手机扫屏幕拿到的是同一个东西。
 */
import { login, req } from '../../core/client'
import { ADMIN_EMAIL, ADMIN_PASSWORD, API_URL, ORG_SLUG } from '../../core/instance'

export interface CheckinSession {
  session_uuid: string
  title: string
  course_uuid: string
  course_name: string
  status: 'open' | 'closed'
  refresh_seconds: number
  code_length: number
  checked_count: number
}

export interface CheckinLive extends CheckinSession {
  token: string
  code: string
  seconds_remaining: number
  recent: Array<{ user_id: number; full_name: string; method: string; ip: string }>
}

function teacherToken(): Promise<string> {
  return login(ADMIN_EMAIL, ADMIN_PASSWORD)
}

/** 开一场签到（教师身份）。 */
export async function createSession(
  courseUuid: string,
  title: string,
  refreshSeconds = 20,
): Promise<CheckinSession> {
  const token = await teacherToken()
  return req<CheckinSession>(
    'POST',
    `/ext/checkin/courses/${courseUuid}/sessions`,
    token,
    { title, refresh_seconds: refreshSeconds },
  )
}

/** 读投屏页那份实时状态：当前 token、口令、剩余秒数、已签人数、最新名单。 */
export async function readLive(sessionUuid: string): Promise<CheckinLive> {
  const token = await teacherToken()
  return req<CheckinLive>('GET', `/ext/checkin/sessions/${sessionUuid}/live`, token)
}

export async function closeSession(sessionUuid: string): Promise<CheckinSession> {
  const token = await teacherToken()
  return req<CheckinSession>('POST', `/ext/checkin/sessions/${sessionUuid}/close`, token)
}

/** 直接调签到接口，返回 HTTP 状态与 detail.code —— 用来断言四种错误码。 */
export async function rawCheck(
  sessionUuid: string,
  body: { token?: string; code?: string },
  bearer: string,
): Promise<{ status: number; code: string | null }> {
  const res = await fetch(
    `${API_URL}/ext/checkin/sessions/${sessionUuid}/check`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${bearer}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    },
  )
  const text = await res.text()
  let code: string | null = null
  try {
    const parsed = JSON.parse(text)
    code = typeof parsed?.detail?.code === 'string' ? parsed.detail.code : null
  } catch {
    /* 非 JSON 响应，code 保持 null */
  }
  return { status: res.status, code }
}

/**
 * CSV 导出（教师身份）。
 *
 * 返回 `hasBom` 而不是让调用方自己去看正文开头：`Response.text()` 按规范会把
 * 前导 BOM 吃掉，所以只能从原始字节里判断。BOM 是给 Excel 用的，没有它中文会乱码。
 */
export async function exportCsv(
  sessionUuid: string,
): Promise<{ text: string; hasBom: boolean }> {
  const token = await teacherToken()
  const res = await fetch(
    `${API_URL}/ext/checkin/sessions/${sessionUuid}/records?format=csv`,
    { headers: { Authorization: `Bearer ${token}` } },
  )
  if (!res.ok) throw new Error(`CSV export -> ${res.status}`)
  const bytes = new Uint8Array(await res.arrayBuffer())
  const hasBom = bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf
  return { text: new TextDecoder('utf-8').decode(bytes), hasBom }
}

/**
 * 挑一门课来做签到。
 *
 * `publicOnly` 为真时只挑公开且已发布的——学生端课程页只有这种打得开，
 * 验证课程页顶部的签到入口条要用它。
 */
export async function pickCourse(publicOnly = false): Promise<string> {
  const token = await teacherToken()
  const list = await req<any[]>(
    'GET',
    `/courses/org_slug/${ORG_SLUG}/page/1/limit/100?include_unpublished=true`,
    token,
  )
  const courses = Array.isArray(list) ? list : []
  const found = publicOnly
    ? courses.find((c) => c.public && c.published)
    : courses[0]
  if (!found) {
    throw new Error(
      publicOnly
        ? '本地库里需要至少一门公开且已发布的课程'
        : '本地库里需要至少一门课程',
    )
  }
  return found.course_uuid as string
}

/** 关掉某门课上所有还开着的会话，避免用例之间互相看见对方的入口条。 */
export async function closeAllOpen(courseUuid: string): Promise<void> {
  const token = await teacherToken()
  const sessions = await req<CheckinSession[]>(
    'GET',
    `/ext/checkin/courses/${courseUuid}/sessions`,
    token,
  )
  for (const s of sessions) {
    if (s.status === 'open') await closeSession(s.session_uuid)
  }
}

/** 课程页路径段不带 `course_` 前缀（页面自己会补回去）。 */
export function courseSlug(courseUuid: string): string {
  return courseUuid.replace('course_', '')
}
