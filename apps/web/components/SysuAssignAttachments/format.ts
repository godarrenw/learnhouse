/**
 * 作业题目附件共用的展示小工具。
 */

/** 把字节数格式化成列表里显示的大小：不到 1MB 用 KB，否则用 MB。 */
export function formatAttachmentSize(size: number): string {
  const bytes = Number(size) || 0
  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
