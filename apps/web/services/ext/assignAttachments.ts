/**
 * 作业题目附件（SYSU-SAM 扩展）的 API 封装。
 *
 * 一份作业可以挂多个题目附件（题目 PDF、数据文件、Word 模板），学生打开
 * 作业即可下载，不受参考答案揭晓规则限制。契约见
 * apps/api/src/routers/ext/assign_attachments.py。
 *
 * 约定同 services/ext/ext.ts：读操作用 apiFetch（失败时 throw，交给
 * react-query 的 error 分支），写操作用 getResponseMetadata（不 throw，
 * 错误取 res.data?.detail）。
 */
import { getAPIUrl } from '@services/config/config'
import {
  RequestBodyFormWithAuthHeader,
  RequestBodyWithAuthHeader,
  apiFetch,
  getResponseMetadata,
} from '@services/utils/ts/requests'

export type AssignmentAttachment = {
  attachment_uuid: string
  assignment_uuid: string
  /** 原始文件名（已去路径、控制字符，最长 200 字符），列表与下载都用它 */
  original_name: string
  content_type: string
  /** 字节数 */
  size: number
  position: number
  creation_date: string
  /** 相对 API 根，例如 ext/assign-attachments/<uuid>/download */
  download_path: string
}

/** 一份作业最多挂几个附件，与后端 MAX_ATTACHMENTS_PER_ASSIGNMENT 一致。 */
export const MAX_ASSIGNMENT_ATTACHMENTS = 10

/** 单个附件上限 100MB，与后端 MAX_ATTACHMENT_BYTES 一致。 */
export const MAX_ASSIGNMENT_ATTACHMENT_BYTES = 100 * 1024 * 1024

/** 取出可直接展示的错误文案：detail 可能是字符串，也可能是 {code,message}。 */
export function readAssignmentAttachmentError(data: any): string {
  const detail = data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
    return detail.message
  }
  return ''
}

/** GET 列表。非本课程老师且作业未发布时后端返回 []。 */
export async function listAssignmentAttachments(
  assignmentUuid: string,
  access_token: string
): Promise<AssignmentAttachment[]> {
  const data = await apiFetch(
    `${getAPIUrl()}ext/assign-attachments/assignments/${assignmentUuid}`,
    access_token
  )
  return Array.isArray(data) ? (data as AssignmentAttachment[]) : []
}

/** POST 单个附件（multipart，字段名 file）。多个文件由调用方逐个上传。 */
export async function uploadAssignmentAttachment(
  assignmentUuid: string,
  file: File,
  access_token: string
) {
  const formData = new FormData()
  formData.append('file', file)
  const result: any = await fetch(
    `${getAPIUrl()}ext/assign-attachments/assignments/${assignmentUuid}`,
    RequestBodyFormWithAuthHeader('POST', formData, null, access_token)
  )
  return await getResponseMetadata(result)
}

/** PUT 重排。attachment_uuids 必须恰好是该作业现有附件的一个排列。 */
export async function reorderAssignmentAttachments(
  assignmentUuid: string,
  attachmentUuids: string[],
  access_token: string
) {
  const result: any = await fetch(
    `${getAPIUrl()}ext/assign-attachments/assignments/${assignmentUuid}/order`,
    RequestBodyWithAuthHeader(
      'PUT',
      { attachment_uuids: attachmentUuids },
      null,
      access_token
    )
  )
  return await getResponseMetadata(result)
}

/** DELETE 单个附件。后端会尽力删掉磁盘文件。 */
export async function deleteAssignmentAttachment(
  attachmentUuid: string,
  access_token: string
) {
  const result: any = await fetch(
    `${getAPIUrl()}ext/assign-attachments/${attachmentUuid}`,
    RequestBodyWithAuthHeader('DELETE', null, null, access_token)
  )
  return await getResponseMetadata(result)
}

/** 下载地址。后端用原始文件名下发 Content-Disposition。 */
export function getAssignmentAttachmentDownloadUrl(att: AssignmentAttachment): string {
  return `${getAPIUrl()}${att.download_path}`
}

/** Fetch with the same cookie + Bearer credentials as the list request. */
export async function downloadAssignmentAttachment(
  att: AssignmentAttachment,
  accessToken?: string
): Promise<Blob> {
  const response = await fetch(getAssignmentAttachmentDownloadUrl(att),
    RequestBodyWithAuthHeader('GET', null, null, accessToken))
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    throw new Error(readAssignmentAttachmentError(data) || `HTTP ${response.status}`)
  }
  return response.blob()
}
