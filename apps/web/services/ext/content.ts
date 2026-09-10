/**
 * 内容工具（ext/content）的 API 封装。
 *
 * 后端挂了 `require_teacher`，它把 org_id 声明成 query 参数，所以**每个接口都要带
 * `?org_id=<org.id>`**（前端 `useOrg()` 里就有）。漏了会直接 422。
 */
import { getAPIUrl } from '@services/config/config'
import {
  RequestBodyWithAuthHeader,
  apiFetch,
  getResponseMetadata,
} from '@services/utils/ts/requests'

// ------------------------------------------------------------ 视频嵌入

export interface EmbedResolveResult {
  embed_url: string
  provider: string
  /** 这个站点的 iframe 有没有在浏览器里实际验证过（抖音、腾讯是 false） */
  confirmed: boolean
  source_url: string
}

/**
 * 把视频链接交给后端规范化成播放器地址。
 *
 * 走后端而不是在前端拼，是因为 b23.tv 短链要跟 302 才知道真实 BV 号，
 * 浏览器里跨域拿不到 Location 头。
 */
export async function resolveEmbedUrl(
  url: string,
  orgId: number,
  access_token: string
) {
  const result: any = await fetch(
    `${getAPIUrl()}ext/content/embed/resolve?org_id=${orgId}`,
    RequestBodyWithAuthHeader('POST', { url }, null, access_token)
  )
  return (await getResponseMetadata(result)) as {
    success: boolean
    data: EmbedResolveResult | { detail?: string }
    status: number
  }
}

// ------------------------------------------------------------ 导入导出

export interface ImportSummary {
  course_uuid: string
  course_name: string
  chapters_created: { chapter_id: number; name: string }[]
  activities_created: {
    activity_uuid: string
    name: string
    type: string
    warnings: string[]
  }[]
  skipped: { file: string; name?: string; type?: string; reason: string }[]
  counts: { chapters: number; activities: number; skipped: number }
}

/**
 * 上传 zip 导入课程内容。
 *
 * 不用 `RequestBodyFormWithAuthHeader` 是因为那个封装会锁死 Content-Type；
 * multipart 的 boundary 必须让浏览器自己生成，手写一定会错。
 */
export async function importCourseMarkdown(
  courseUuid: string,
  orgId: number,
  file: File,
  access_token: string,
  publish?: boolean
) {
  const form = new FormData()
  form.append('file', file)
  const publishParam = publish === undefined ? '' : `&publish=${publish}`
  const result: any = await fetch(
    `${getAPIUrl()}ext/content/courses/${courseUuid}/import-md` +
      `?org_id=${orgId}${publishParam}`,
    {
      method: 'POST',
      headers: { Authorization: `Bearer ${access_token}` },
      body: form,
      cache: 'no-store',
    }
  )
  return (await getResponseMetadata(result)) as {
    success: boolean
    data: ImportSummary | { detail?: string }
    status: number
  }
}

export interface ExportResult {
  blob: Blob
  filename: string
  /** 后端用响应头回的统计，省得再发一次请求 */
  stats: { chapters: number; files: number; images: number; notes: number }
}

/**
 * 下载课程的 Markdown 压缩包。
 *
 * 接口要 Bearer token，所以不能直接 `window.open` 一个链接 —— 那样带不了 header
 * 会 401。这里 fetch 成 Blob 再用临时 a 标签存盘。
 */
export async function exportCourseMarkdown(
  courseUuid: string,
  orgId: number,
  access_token: string
): Promise<ExportResult> {
  const res = await fetch(
    `${getAPIUrl()}ext/content/courses/${courseUuid}/export-md?org_id=${orgId}`,
    { headers: { Authorization: `Bearer ${access_token}` }, cache: 'no-store' }
  )
  if (!res.ok) {
    let detail = ''
    try {
      detail = (await res.json())?.detail ?? ''
    } catch {
      /* 非 JSON 的错误体，忽略 */
    }
    throw new Error(detail || String(res.status))
  }
  return {
    blob: await res.blob(),
    filename: filenameFromDisposition(res.headers.get('content-disposition')),
    stats: {
      chapters: Number(res.headers.get('x-export-chapters') ?? 0),
      files: Number(res.headers.get('x-export-files') ?? 0),
      images: Number(res.headers.get('x-export-images') ?? 0),
      notes: Number(res.headers.get('x-export-notes') ?? 0),
    },
  }
}

/**
 * 从 Content-Disposition 里取文件名。课程名多半是中文，后端发的是 RFC 5987 的
 * `filename*=UTF-8''…` 形式，优先读它；读不到退回 ASCII 那份，再不行给个兜底名。
 */
export function filenameFromDisposition(header: string | null): string {
  if (!header) return 'course.zip'
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (star) {
    try {
      return decodeURIComponent(star[1])
    } catch {
      /* 编码坏了就往下走 */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header)
  return plain ? plain[1] : 'course.zip'
}

// ------------------------------------------------------------ 虚拟助教

export interface AvatarConfig {
  page_url: string
  /** 这次地址是从哪一层取到的：org_config / env / default */
  source: string
}

export async function getAvatarConfig(
  orgId: number,
  access_token: string
): Promise<AvatarConfig> {
  return apiFetch(
    `${getAPIUrl()}ext/content/avatar/config?org_id=${orgId}`,
    access_token
  )
}

export interface AvatarAppendResult {
  activity_uuid: string
  activity_name: string
  embed_url: string
  title: string
  line_count: number
  url_length: number
  encoding: string
  page_url: string
  page_url_source: string
  nodes_before: number
  nodes_after: number
  version_saved: boolean
}

export async function appendAvatarToPage(
  activityUuid: string,
  orgId: number,
  body: { script: string; title?: string; page_url?: string },
  access_token: string
) {
  const result: any = await fetch(
    `${getAPIUrl()}ext/content/activities/${activityUuid}/avatar?org_id=${orgId}`,
    RequestBodyWithAuthHeader('POST', body, null, access_token)
  )
  return (await getResponseMetadata(result)) as {
    success: boolean
    data: AvatarAppendResult | { detail?: string }
    status: number
  }
}

// ------------------------------------------------------------ 二维码

/**
 * 取 SVG 二维码的文本。
 *
 * 之所以不直接把地址塞进 `<img src>`：接口要 Bearer token，`<img>` 带不了，
 * 会 401 出一个碎图。拿到文本后内联渲染即可。
 */
export async function fetchQrSvg(
  text: string,
  orgId: number,
  access_token: string,
  scale = 8
): Promise<string> {
  const res = await fetch(
    `${getAPIUrl()}ext/content/qr.svg` +
      `?org_id=${orgId}&text=${encodeURIComponent(text)}&scale=${scale}`,
    { headers: { Authorization: `Bearer ${access_token}` }, cache: 'no-store' }
  )
  if (!res.ok) throw new Error(String(res.status))
  return res.text()
}

/** 把内存里的内容存成一个文件。浏览器里没有别的存盘办法。 */
export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
