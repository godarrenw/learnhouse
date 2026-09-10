/**
 * 学情工具（成绩册 / 缺交 / 学习进度 / 课程体检）的 API 封装。
 *
 * 后端接口都挂了 `require_teacher`，所以每个请求必须带 `?org_id=<org.id>`。
 * 读操作用 apiFetch（失败 throw，交给 react-query 的 error 分支），
 * 写操作用 extWrite（永不 throw，判 res.success）。
 */
import { getAPIUrl } from '@services/config/config'
import { extWrite } from '@services/ext/ext'
import { apiFetch } from '@services/utils/ts/requests'

const base = () => `${getAPIUrl()}ext/learning`

export interface GradebookCell {
  assignment_uuid: string
  title: string
  status_code: string
  status: string
  late: boolean
  score: number | null
  max_grade: number
  percentage: number | null
  display_grade: string | null
  submitted_at: string | null
}

export interface GradebookStudent {
  user_id: number
  user_uuid: string
  name: string
  email: string
  usergroup: string
  cells: GradebookCell[]
  submitted: number
  assignment_total: number
  total_score: number
  average_percentage: number | null
}

export interface LintFinding {
  level: 'error' | 'warn' | 'info'
  code: string
  message: string
  target_uuid: string | null
  target_type: string | null
  fix_hint: string
  fixable: boolean
}

export function getGradebook(courseUuid: string, orgId: number, token: string) {
  return apiFetch(`${base()}/courses/${courseUuid}/gradebook?org_id=${orgId}`, token)
}

export function getMissing(
  courseUuid: string,
  orgId: number,
  assignmentUuid: string | null,
  token: string
) {
  const filter = assignmentUuid
    ? `&assignment_uuid=${encodeURIComponent(assignmentUuid)}`
    : ''
  return apiFetch(`${base()}/courses/${courseUuid}/missing?org_id=${orgId}${filter}`, token)
}

export function getProgress(courseUuid: string, orgId: number, token: string) {
  return apiFetch(`${base()}/courses/${courseUuid}/progress?org_id=${orgId}`, token)
}

export function getStudentProgress(
  courseUuid: string,
  orgId: number,
  student: string,
  token: string
) {
  return apiFetch(
    `${base()}/courses/${courseUuid}/progress?org_id=${orgId}&student=${encodeURIComponent(student)}`,
    token
  )
}

export function getLint(courseUuid: string, orgId: number, token: string) {
  return apiFetch(`${base()}/courses/${courseUuid}/lint?org_id=${orgId}`, token)
}

/** 一键发布未发布活动。后端要求请求体里带 confirm: true。 */
export function fixPublish(courseUuid: string, orgId: number, token: string) {
  return extWrite(
    `learning/courses/${courseUuid}/lint/fix-publish?org_id=${orgId}`,
    'POST',
    { confirm: true },
    token
  )
}

/** 组织级的最近学习动态。概览页的小卡片用，不需要选课。 */
export function getRecent(orgId: number, token: string, days = 7, limit = 20) {
  return apiFetch(`${base()}/recent?org_id=${orgId}&days=${days}&limit=${limit}`, token)
}
