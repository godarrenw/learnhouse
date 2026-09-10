/* --- SYSU-SAM: 内容工具 · 编辑器粘贴视频链接 --- */
import { getAPIUrl } from '@services/config/config'
import {
  RequestBodyWithAuthHeader,
  getResponseMetadata,
} from '@services/utils/ts/requests'

export interface EmbedResolveResult {
  embed_url: string
  provider: string
  /** 这个站点的 iframe 我们有没有在浏览器里实际验证过（抖音、腾讯是 false） */
  confirmed: boolean
  source_url: string
}

/**
 * 把视频链接交给后端规范化成播放器地址。
 *
 * 走后端而不是在前端拼，是因为 b23.tv 短链要跟 302 才知道真实 BV 号，
 * 浏览器里跨域拿不到 Location 头。
 */
export async function resolveEmbedUrl(url: string, access_token: string) {
  const result: any = await fetch(
    `${getAPIUrl()}ext/content/embed/resolve`,
    RequestBodyWithAuthHeader('POST', { url }, null, access_token)
  )
  return (await getResponseMetadata(result)) as {
    success: boolean
    data: EmbedResolveResult | { detail?: string }
    status: number
  }
}
/* --- /SYSU-SAM --- */
