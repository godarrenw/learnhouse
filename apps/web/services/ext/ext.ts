/**
 * 教学工具（ext）扩展层的 API 封装。
 *
 * 这个目录是部署方新增的，上游没有。每个工具建议自己开一个文件
 * （services/ext/<tool>.ts），本文件只放所有工具共用的东西。
 *
 * 约定：
 * - URL 一律 `${getAPIUrl()}ext/...` 拼出来，不要硬编码后端地址
 *   （services/utils/ts/requests.ts 的 validateApiUrl 会拒掉不合规的 URL）。
 * - 读操作用 apiFetch（失败时 throw，配合 react-query 的 error 分支）。
 * - 写操作用 getResponseMetadata（永不 throw，判 res.success，错误取 res.data?.detail）。
 * - 挂了后端 require_teacher 依赖的接口必须带 ?org_id=<org.id>。
 */
import { getAPIUrl } from '@services/config/config'
import {
  RequestBodyWithAuthHeader,
  apiFetch,
  getResponseMetadata,
} from '@services/utils/ts/requests'

export interface ExtHealth {
  status: string
  ext_version: string
  org_id: number
  user_id: number
  username: string
  role: string | null
  tools: string[]
}

/** GET /ext/health —— 扩展层自检，示例工具页用它。 */
export async function getExtHealth(
  orgId: number,
  access_token: string
): Promise<ExtHealth> {
  return apiFetch(`${getAPIUrl()}ext/health?org_id=${orgId}`, access_token)
}

/**
 * 各工具写操作的统一入口，省得每个工具重复拼 RequestBodyWithAuthHeader。
 * `path` 不带前导斜杠，例如 `'gradebook/export'`。
 */
export async function extWrite(
  path: string,
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  body: any,
  access_token: string
) {
  const result: any = await fetch(
    `${getAPIUrl()}ext/${path}`,
    RequestBodyWithAuthHeader(method, body, null, access_token)
  )
  return await getResponseMetadata(result)
}
