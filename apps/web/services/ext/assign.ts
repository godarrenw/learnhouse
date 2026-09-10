/**
 * 作业工具（教学工具 · assign）的接口封装。
 *
 * 后端在 `apps/api/src/routers/ext/assign_tools.py`，路径前缀 `/ext/assign`。
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

const base = () => `${getAPIUrl()}ext/assign`

type Token = string | null | undefined

async function post(path: string, body: any, access_token: Token) {
  const result: any = await fetch(
    `${base()}${path}`,
    RequestBodyWithAuthHeader('POST', body, null, access_token || undefined)
  )
  return await getResponseMetadata(result)
}

// ---------------------------------------------------------------- spec / LLM

export function getSpecTemplate(types: string[], access_token: Token) {
  const qs = types.length ? `?types=${encodeURIComponent(types.join(','))}` : ''
  return apiFetch(`${base()}/spec/template${qs}`, access_token || undefined)
}

export function getLlmModels(access_token: Token) {
  return apiFetch(`${base()}/llm/models`, access_token || undefined)
}

export function validateSpec(spec: any, access_token: Token) {
  return post('/spec/validate', { spec }, access_token)
}

// ---------------------------------------------------------------- AI 出题

export function draftFromActivity(
  courseUuid: string,
  activityUuid: string,
  body: { n: number; types: string[]; model?: string; name?: string },
  access_token: Token
) {
  return post(`/courses/${courseUuid}/activities/${activityUuid}/draft`, body, access_token)
}

export function createFromSpec(
  courseUuid: string,
  chapterId: number,
  spec: any,
  publish: boolean,
  access_token: Token
) {
  return post(`/courses/${courseUuid}/chapters/${chapterId}/from-spec`, { spec, publish }, access_token)
}

// ---------------------------------------------------------------- 随堂测

export function createQuickQuiz(
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
  return post(`/courses/${courseUuid}/chapters/${chapterId}/quick-quiz`, body, access_token)
}

export function getQuizResults(assignmentUuid: string, access_token: Token) {
  return apiFetch(`${base()}/assignments/${assignmentUuid}/results`, access_token || undefined)
}

// ---------------------------------------------------------------- 查重

export function getSimilarity(
  assignmentUuid: string,
  threshold: number,
  access_token: Token
) {
  return apiFetch(
    `${base()}/assignments/${assignmentUuid}/similarity?threshold=${threshold}`,
    access_token || undefined
  )
}

// ---------------------------------------------------------------- 学期复用

export function cloneTerm(
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
  return post(`/courses/${courseUuid}/clone-term`, body, access_token)
}

export function shiftDue(
  courseUuid: string,
  body: {
    days?: number | null
    due_date?: string | null
    only_future: boolean
    confirm: boolean
  },
  access_token: Token
) {
  return post(`/courses/${courseUuid}/shift-due`, body, access_token)
}

// ---------------------------------------------------------------- 版本回滚

export function getVersions(activityUuid: string, access_token: Token) {
  return apiFetch(`${base()}/activities/${activityUuid}/versions`, access_token || undefined)
}

export function getVersionDiff(
  activityUuid: string,
  a: number | null,
  b: number | null,
  access_token: Token
) {
  const params = new URLSearchParams()
  if (a !== null) params.set('a', String(a))
  if (b !== null) params.set('b', String(b))
  const qs = params.toString() ? `?${params.toString()}` : ''
  return apiFetch(`${base()}/activities/${activityUuid}/diff${qs}`, access_token || undefined)
}

export function restoreVersion(
  activityUuid: string,
  version: number,
  confirm: boolean,
  access_token: Token
) {
  return post(`/activities/${activityUuid}/restore`, { version, confirm }, access_token)
}
