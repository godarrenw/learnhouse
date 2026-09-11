import { getBackendUrl, getConfig } from '@services/config/config'

function getMediaUrl() {
  const raw = getConfig('NEXT_PUBLIC_LEARNHOUSE_MEDIA_URL') || getBackendUrl();
  // Guarantee a trailing slash so callers can concatenate "content/..." without
  // producing "https://api.example.iocontent/..." when the base lacks a slash.
  return raw.endsWith('/') ? raw : `${raw}/`;
}

function getApiUrl() {
  // Normalize so URL building is correct whether or not the configured backend
  // URL carries a trailing slash (otherwise we'd get "...ioapi/v1/...").
  const base = getBackendUrl();
  return base.endsWith('/') ? base : `${base}/`;
}

/**
 * Get the streaming URL for an activity video.
 * Uses the optimized streaming endpoint with proper Range request support.
 */
export function getActivityVideoStreamUrl(
  orgUUID: string,
  courseUUID: string,
  activityUUID: string,
  filename: string
) {
  return `${getApiUrl()}api/v1/stream/video/${orgUUID}/${courseUUID}/${activityUUID}/${filename}`
}

/**
 * Get the HLS master-playlist URL for an activity video.
 * The API returns the playlist (after an RBAC check) with segment URLs
 * presigned to R2, so hls.js streams segments directly from object storage.
 */
export function getActivityHlsMasterUrl(
  orgUUID: string,
  courseUUID: string,
  activityUUID: string
) {
  return `${getApiUrl()}api/v1/stream/hls/${orgUUID}/${courseUUID}/${activityUUID}/master.m3u8`
}

/**
 * Get the URL of an activity's HLS hover-preview sprite sheet. The API redirects
 * this to a presigned R2 URL; it's loaded as a CSS background image (no CORS).
 */
export function getActivityHlsThumbnailsUrl(
  orgUUID: string,
  courseUUID: string,
  activityUUID: string,
  spritePath: string
) {
  return `${getApiUrl()}api/v1/stream/hls/${orgUUID}/${courseUUID}/${activityUUID}/${spritePath}`
}

/**
 * Get the URL of an activity's WebVTT caption track for a language. Served inline
 * by the API after an RBAC check (same access as the video).
 */
export function getActivityCaptionUrl(
  orgUUID: string,
  courseUUID: string,
  activityUUID: string,
  lang: string
) {
  return `${getApiUrl()}api/v1/stream/captions/${orgUUID}/${courseUUID}/${activityUUID}/${lang}.vtt`
}

/**
 * Get the streaming URL for a video block.
 * Uses the optimized streaming endpoint with proper Range request support.
 */
export function getVideoBlockStreamUrl(
  orgUUID: string,
  courseUUID: string,
  activityUUID: string,
  blockUUID: string,
  filename: string
) {
  return `${getApiUrl()}api/v1/stream/block/${orgUUID}/${courseUUID}/${activityUUID}/${blockUUID}/${filename}`
}

/**
 * HLS master-playlist URL for a video BLOCK (adaptive streaming). The API
 * presigns segment URLs to R2 — same pipeline as activity videos.
 */
export function getVideoBlockHlsMasterUrl(
  orgUUID: string,
  courseUUID: string,
  activityUUID: string,
  blockUUID: string
) {
  return `${getApiUrl()}api/v1/stream/block-hls/${orgUUID}/${courseUUID}/${activityUUID}/${blockUUID}/master.m3u8`
}

/** URL of a video block's HLS hover-preview sprite sheet. */
export function getVideoBlockHlsThumbnailsUrl(
  orgUUID: string,
  courseUUID: string,
  activityUUID: string,
  blockUUID: string,
  spritePath: string
) {
  return `${getApiUrl()}api/v1/stream/block-hls/${orgUUID}/${courseUUID}/${activityUUID}/${blockUUID}/${spritePath}`
}

/**
 * Get the streaming URL for an audio block.
 * Uses the optimized streaming endpoint with proper Range request support.
 */
export function getAudioBlockStreamUrl(
  orgUUID: string,
  courseUUID: string,
  activityUUID: string,
  blockUUID: string,
  filename: string
) {
  return `${getApiUrl()}api/v1/stream/block/audio/${orgUUID}/${courseUUID}/${activityUUID}/${blockUUID}/${filename}`
}

export function getCourseThumbnailMediaDirectory(
  orgUUID: string,
  courseUUID: string,
  fileId: string
) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/courses/${courseUUID}/thumbnails/${fileId}`
  return uri
}

/**
 * Absolute URL for an AI-generated image (nano banana). Stored per-org under
 * content/orgs/{orgUUID}/ai_images/{fileId}, mirroring the other media helpers.
 */
export function getAIImageMediaDirectory(orgUUID: string, fileId: string) {
  return `${getMediaUrl()}content/orgs/${orgUUID}/ai_images/${fileId}`
}

export function getFolderThumbnailMediaDirectory(
  orgUUID: string,
  folderUUID: string,
  fileId: string
) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/folders/${folderUUID}/thumbnails/${fileId}`
  return uri
}

export function getBoardThumbnailMediaDirectory(
  orgUUID: string,
  boardUUID: string,
  fileId: string
) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/boards/${boardUUID}/thumbnails/${fileId}`
  return uri
}

export function getPlaygroundThumbnailMediaDirectory(
  orgUUID: string,
  playgroundUUID: string,
  fileId: string
) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/playgrounds/${playgroundUUID}/thumbnails/${fileId}`
  return uri
}

export function getCommunityThumbnailMediaDirectory(
  orgUUID: string,
  communityUUID: string,
  fileId: string
) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/communities/${communityUUID}/thumbnails/${fileId}`
  return uri
}

export function getOrgLandingMediaDirectory(orgUUID: string, fileId: string) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/landing/${fileId}`
  return uri
}

export function getUserAvatarMediaDirectory(userUUID: string, fileId: string) {
  let uri = `${getMediaUrl()}content/users/${userUUID}/avatars/${fileId}`
  return uri
}

export function getActivityBlockMediaDirectory(
  orgUUID: string,
  courseId: string,
  activityId: string,
  blockId: any,
  fileId: any,
  type: string
) {
  if (type == 'pdfBlock') {
    let uri = `${getMediaUrl()}content/orgs/${orgUUID}/courses/${courseId}/activities/${activityId}/dynamic/blocks/pdfBlock/${blockId}/${fileId}`
    return uri
  }
  if (type == 'videoBlock') {
    let uri = `${getMediaUrl()}content/orgs/${orgUUID}/courses/${courseId}/activities/${activityId}/dynamic/blocks/videoBlock/${blockId}/${fileId}`
    return uri
  }
  if (type == 'imageBlock') {
    let uri = `${getMediaUrl()}content/orgs/${orgUUID}/courses/${courseId}/activities/${activityId}/dynamic/blocks/imageBlock/${blockId}/${fileId}`
    return uri
  }
  if (type == 'audioBlock') {
    let uri = `${getMediaUrl()}content/orgs/${orgUUID}/courses/${courseId}/activities/${activityId}/dynamic/blocks/audioBlock/${blockId}/${fileId}`
    return uri
  }
}

export function getTaskRefFileDir(
  orgUUID: string,
  courseUUID: string,
  activityUUID: string,
  assignmentUUID: string,
  assignmentTaskUUID: string,
  fileID : string

) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/courses/${courseUUID}/activities/${activityUUID}/assignments/${assignmentUUID}/tasks/${assignmentTaskUUID}/${fileID}`
  return uri
}

// The assignment-level model answer ("corrigé") document. Mirrors the task
// reference-file layout but hangs off the assignment, matching
// `upload_solution_file` on the API side.
export function getAssignmentSolutionFileDir(
  orgUUID: string,
  courseUUID: string,
  activityUUID: string,
  assignmentUUID: string,
  fileID: string
) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/courses/${courseUUID}/activities/${activityUUID}/assignments/${assignmentUUID}/solution/${fileID}`
  return uri
}

export function getTaskFileSubmissionDir(
  orgUUID: string,
  courseUUID: string,
  activityUUID: string,
  assignmentUUID: string,
  assignmentTaskUUID: string,
  fileSubID : string
) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/courses/${courseUUID}/activities/${activityUUID}/assignments/${assignmentUUID}/tasks/${assignmentTaskUUID}/subs/${fileSubID}`
  return uri
}

export function getActivityMediaDirectory(
  orgUUID: string,
  courseUUID: string,
  activityUUID: string,
  fileId: string,
  activityType: string
) {
  if (activityType == 'video') {
    let uri = `${getMediaUrl()}content/orgs/${orgUUID}/courses/${courseUUID}/activities/${activityUUID}/video/${fileId}`
    return uri
  }
  if (activityType == 'documentpdf') {
    let uri = `${getMediaUrl()}content/orgs/${orgUUID}/courses/${courseUUID}/activities/${activityUUID}/documentpdf/${fileId}`
    return uri
  }
}

export function getOrgLogoMediaDirectory(orgUUID: string, fileId: string) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/logos/${fileId}`
  return uri
}

export function getOrgThumbnailMediaDirectory(orgUUID: string, fileId: string) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/thumbnails/${fileId}`
  return uri
}

export function getOrgPreviewMediaDirectory(orgUUID: string, fileId: string) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/previews/${fileId}`
  return uri
}

export function getOrgOgImageMediaDirectory(orgUUID: string, fileId: string) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/og_images/${fileId}`
  return uri
}

export function getOrgAuthBackgroundMediaDirectory(orgUUID: string, fileId: string) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/auth_backgrounds/${fileId}`
  return uri
}

export function getOrgFaviconMediaDirectory(orgUUID: string, fileId: string) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/favicons/${fileId}`
  return uri
}

/**
 * Get the URL for SCORM content files
 * Routes through a local proxy to ensure same-origin for SCORM API injection
 */
export function getScormContentUrl(
  orgUUID: string,
  courseUUID: string,
  activityUUID: string,
  filePath: string
): string {
  // Use local proxy route to serve SCORM content from same origin
  // This is required for the SCORM API to work properly in iframes
  return `/api/scorm/${activityUUID}/content/${filePath}`
}

/**
 * Get the thumbnail URL for a podcast
 */
export function getPodcastThumbnailMediaDirectory(
  orgUUID: string,
  podcastUUID: string,
  fileId: string
) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/podcasts/${podcastUUID}/thumbnails/${fileId}`
  return uri
}

/**
 * Get the thumbnail URL for a podcast episode
 */
export function getEpisodeThumbnailMediaDirectory(
  orgUUID: string,
  podcastUUID: string,
  episodeUUID: string,
  fileId: string
) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/podcasts/${podcastUUID}/episodes/${episodeUUID}/thumbnails/${fileId}`
  return uri
}

/**
 * Get the direct media URL for a podcast episode audio file.
 */
export function getEpisodeAudioMediaDirectory(
  orgUUID: string,
  podcastUUID: string,
  episodeUUID: string,
  fileId: string
) {
  let uri = `${getMediaUrl()}content/orgs/${orgUUID}/podcasts/${podcastUUID}/episodes/${episodeUUID}/audio/${fileId}`
  return uri
}

/**
 * Get the streaming URL for a podcast episode audio file.
 * Uses the optimized streaming endpoint with proper Range request support.
 */
export function getPodcastAudioStreamUrl(
  orgUUID: string,
  podcastUUID: string,
  episodeUUID: string,
  filename: string
) {
  return `${getApiUrl()}api/v1/stream/audio/${orgUUID}/${podcastUUID}/${episodeUUID}/${filename}`
}

/* --- SYSU-SAM --- */
/**
 * 「重媒体域名」支持（设计文档方案 B）。
 *
 * 视频 / PDF / 音频这类重媒体分流到只在校园网可解析的媒体域名，图片、缩略图、
 * 头像等留在主域名 —— 校外用户页面完整，只有视频和讲义打不开。
 *
 * 这里只提供两个纯函数，上面所有 helper 一律不动（它们照旧生成主域名地址）。
 * 换域与签名由 useSignedMediaUrls hook 完成，见
 * services/media/useSignedMediaUrls.ts。**没配 HEAVY_MEDIA_URL 时这两个函数
 * 不改变任何行为，hook 也不会发出任何请求。**
 *
 * ⚠️ 不要和上游的 NEXT_PUBLIC_LEARNHOUSE_MEDIA_URL 混淆：那是「所有 /content/
 * 一刀切」的开关，设了以后课程封面、头像、机构 logo 会一起搬走，校外满页裂图。
 */
export function getHeavyMediaBase(): string | null {
  const raw = getConfig('NEXT_PUBLIC_LEARNHOUSE_HEAVY_MEDIA_URL')
  if (!raw || !String(raw).trim()) return null
  const trimmed = String(raw).trim()
  return trimmed.endsWith('/') ? trimmed.slice(0, -1) : trimmed
}

/**
 * 这个 URL 路径算不算「重媒体」。
 *
 * ⚠️ 这份规则有三份拷贝，改一处必须改另外两处：
 *   - apps/api/src/services/ext/media_sign/signer.py 的 _SIGNABLE_PATTERNS
 *   - deploy/extra/nginx.prod.conf 顶部的 $media_path_hit
 *   - 这里
 * 后端是权威：它拒签的路径，前端换了域名也取不到。
 *
 * 刻意不含 imageBlock、缩略图、头像、学生提交文件、字幕 VTT、HLS、播客，
 * 逐条理由见 signer.py。
 */
const HEAVY_MEDIA_PATTERNS: RegExp[] = [
  /^\/api\/v1\/stream\/video\/[^/]+\/[^/]+\/[^/]+\/.+$/,
  // /block/ 与 /block/audio/ 都落在这一条里
  /^\/api\/v1\/stream\/block\/.+$/,
  /^\/content\/orgs\/[^/]+\/courses\/[^/]+\/activities\/[^/]+\/(?:video|documentpdf)\/.+$/,
  /^\/content\/orgs\/[^/]+\/courses\/[^/]+\/activities\/[^/]+\/dynamic\/blocks\/(?:pdfBlock|videoBlock|audioBlock)\/[^/]+\/.+$/,
]

export function isHeavyMediaPath(path: string): boolean {
  if (!path || !path.startsWith('/')) return false
  if (path.includes('..')) return false
  return HEAVY_MEDIA_PATTERNS.some((p) => p.test(path))
}
/* --- SYSU-SAM END --- */
