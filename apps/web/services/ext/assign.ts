/**
 * 作业工具（教学工具 · assign）的接口封装。
 *
 * 后端在 `apps/api/src/routers/ext/assign_tools.py`，路径前缀 `/ext/assign`。
 * 所有接口都挂了骨架的 `require_teacher`，**因此每个请求都要带 `?org_id=<org.id>`**。
 * 读接口用 `apiFetch`（失败会 throw，交给 react-query 的 error 分支）；
 * 写接口用 `getResponseMetadata`（永不 throw，调用方判断 `res.success`，
 * 错误文案从 `res.data?.detail` 取）。
 */
import { getAPIUrl } from '@services/config/config'
import {
  RequestBodyWithAuthHeader,
  apiFetch,
  getResponseMetadata,
} from '@services/utils/ts/requests'

type Token = string | null | undefined

/** 拼 `${getAPIUrl()}ext/assign<path>?org_id=…&…`，org_id 永远在最前面。 */
function url(path: string, orgId: number, params?: Record<string, string | number>) {
  const search = new URLSearchParams({ org_id: String(orgId) })
  for (const [k, v] of Object.entries(params ?? {})) search.set(k, String(v))
  return `${getAPIUrl()}ext/assign${path}?${search.toString()}`
}

async function post(path: string, orgId: number, body: any, access_token: Token) {
  const result: any = await fetch(
    url(path, orgId),
    RequestBodyWithAuthHeader('POST', body, null, access_token || undefined)
  )
  return await getResponseMetadata(result)
}

// ---------------------------------------------------------------- spec / LLM

export function getSpecTemplate(orgId: number, types: string[], access_token: Token) {
  const params = types.length ? { types: types.join(',') } : undefined
  return apiFetch(url('/spec/template', orgId, params), access_token || undefined)
}

export function getLlmModels(orgId: number, access_token: Token) {
  return apiFetch(url('/llm/models', orgId), access_token || undefined)
}

export function validateSpec(orgId: number, spec: any, access_token: Token) {
  return post('/spec/validate', orgId, { spec }, access_token)
}

// ---------------------------------------------------------------- AI 出题

export function draftFromActivity(
  orgId: number,
  courseUuid: string,
  activityUuid: string,
  body: { n: number; types: string[]; model?: string; name?: string },
  access_token: Token
) {
  return post(
    `/courses/${courseUuid}/activities/${activityUuid}/draft`,
    orgId,
    body,
    access_token
  )
}

export function createFromSpec(
  orgId: number,
  courseUuid: string,
  chapterId: number,
  spec: any,
  publish: boolean,
  access_token: Token
) {
  return post(
    `/courses/${courseUuid}/chapters/${chapterId}/from-spec`,
    orgId,
    { spec, publish },
    access_token
  )
}

// ---------------------------------------------------------------- 随堂测

export function createQuickQuiz(
  orgId: number,
  courseUuid: string,
  chapterId: number,
  body: {
    title: string
    questions: any[]
    formative: boolean
    publish: boolean
    due_date?: string | null
    description?: string
  },
  access_token: Token
) {
  return post(
    `/courses/${courseUuid}/chapters/${chapterId}/quick-quiz`,
    orgId,
    body,
    access_token
  )
}

export function getQuizResults(orgId: number, assignmentUuid: string, access_token: Token) {
  return apiFetch(url(`/assignments/${assignmentUuid}/results`, orgId), access_token || undefined)
}

// ---------------------------------------------------------------- 查重

export function getSimilarity(
  orgId: number,
  assignmentUuid: string,
  threshold: number,
  access_token: Token
) {
  return apiFetch(
    url(`/assignments/${assignmentUuid}/similarity`, orgId, { threshold }),
    access_token || undefined
  )
}

// ---------------------------------------------------------------- 学期复用

export function cloneTerm(
  orgId: number,
  courseUuid: string,
  body: {
    name?: string
    shift_days?: number | null
    due_date?: string | null
    unpublish: boolean
    confirm: boolean
  },
  access_token: Token
) {
  return post(`/courses/${courseUuid}/clone-term`, orgId, body, access_token)
}

export function shiftDue(
  orgId: number,
  courseUuid: string,
  body: {
    days?: number | null
    due_date?: string | null
    only_future: boolean
    confirm: boolean
  },
  access_token: Token
) {
  return post(`/courses/${courseUuid}/shift-due`, orgId, body, access_token)
}

// ---------------------------------------------------------------- 版本回滚

export function getVersions(orgId: number, activityUuid: string, access_token: Token) {
  return apiFetch(url(`/activities/${activityUuid}/versions`, orgId), access_token || undefined)
}

export function getVersionDiff(
  orgId: number,
  activityUuid: string,
  a: number | null,
  b: number | null,
  access_token: Token
) {
  const params: Record<string, number> = {}
  if (a !== null) params.a = a
  if (b !== null) params.b = b
  return apiFetch(
    url(`/activities/${activityUuid}/diff`, orgId, params),
    access_token || undefined
  )
}

export function restoreVersion(
  orgId: number,
  activityUuid: string,
  version: number,
  confirm: boolean,
  access_token: Token
) {
  return post(
    `/activities/${activityUuid}/restore`,
    orgId,
    { version, confirm },
    access_token
  )
}
