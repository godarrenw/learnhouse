'use client'
/**
 * 「作业题目」附件卡片（学生端 + 批改页只读）。
 *
 * 学生打开作业就能下载，不受参考答案揭晓规则限制。没有附件、未登录、
 * 或者请求失败时返回 null —— 附件这块不能把错误抛到作业页面上。
 */
import React from 'react'
import toast from 'react-hot-toast'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Download, FileText, Paperclip } from 'lucide-react'

import { useLHSession } from '@components/Contexts/LHSessionContext'
import { queryKeys } from '@/lib/query/keys'
import {
  AssignmentAttachment,
  downloadAssignmentAttachment,
  getAssignmentAttachmentDownloadUrl,
  listAssignmentAttachments,
} from '@services/ext/assignAttachments'

import { formatAttachmentSize } from './format'

type Props = {
  assignmentUuid?: string | null
}

export default function AttachmentsCard({ assignmentUuid }: Props) {
  const { t } = useTranslation()
  const session = useLHSession() as any
  const accessToken = session?.data?.tokens?.access_token

  const [downloading, setDownloading] = React.useState<string | null>(null)
  const { data, isError } = useQuery({
    queryKey: queryKeys.ext.assignAttachments.list(assignmentUuid ?? ''),
    queryFn: () => listAssignmentAttachments(assignmentUuid as string, accessToken),
    enabled: !!assignmentUuid && !!accessToken,
    retry: false,
    staleTime: 30_000,
  })

  const attachments = data ?? []
  if (isError || attachments.length === 0) return null

  async function download(event: React.MouseEvent, att: AssignmentAttachment) {
    event.preventDefault()
    if (downloading) return
    setDownloading(att.attachment_uuid)
    try {
      const blob = await downloadAssignmentAttachment(att, accessToken)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = att.original_name
      document.body.appendChild(link)
      link.click()
      link.remove()
      // Let the browser consume the URL before releasing the downloaded data.
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) {
      toast.error(error instanceof Error ? error.message :
        t('ext.assign_attachments.download_error', { defaultValue: '下载失败，请重试' }))
    } finally {
      setDownloading(null)
    }
  }

  return (
    <div className="flex flex-col space-y-3 p-4 md:p-6 rounded-md bg-slate-100/30 border border-slate-200/70 nice-shadow">
      <div className="flex items-center gap-2 text-slate-700">
        <Paperclip size={16} className="text-sky-600" />
        <h3 className="text-sm font-semibold">
          {t('ext.assign_attachments.student_title', { defaultValue: '作业题目' })}
        </h3>
      </div>
      <div className="ps-0 md:ps-6 flex flex-col space-y-2">
        {attachments.map((att) => (
          <a
            key={att.attachment_uuid}
            href={getAssignmentAttachmentDownloadUrl(att)}
            onClick={(event) => void download(event, att)}
            aria-busy={downloading === att.attachment_uuid}
            target="_blank"
            rel="noreferrer"
            download={att.original_name}
            className="flex items-center gap-3 px-3 py-2 rounded-lg bg-white nice-shadow text-slate-700 hover:bg-sky-50/60 transition-colors group"
          >
            <FileText size={14} className="flex-none text-sky-500" />
            <span
              className="text-xs font-semibold truncate flex-1 min-w-0"
              title={att.original_name}
            >
              {att.original_name}
            </span>
            <span className="text-[10px] text-slate-400 flex-none tabular-nums">
              {formatAttachmentSize(att.size)}
            </span>
            <Download
              size={13}
              className="flex-none text-slate-400 group-hover:text-sky-600 transition-colors"
            />
          </a>
        ))}
      </div>
    </div>
  )
}
