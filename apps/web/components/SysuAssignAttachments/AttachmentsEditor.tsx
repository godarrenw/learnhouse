'use client'
/**
 * 老师端「题目附件」编辑区，放在「编辑作业」弹窗里参考答案区块的上方。
 *
 * 所有操作立即生效，不跟随弹窗的「保存」：上传 / 删除 / 调整顺序各自调用
 * 后端接口，成功后 invalidate 列表缓存。学生端能不能看到与参考答案揭晓
 * 规则无关。
 */
import React from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import {
  ArrowDown,
  ArrowUp,
  FileText,
  Loader2,
  Paperclip,
  Trash2,
  Upload,
} from 'lucide-react'

import ConfirmDanger from '@components/SysuTools/shared/ConfirmDanger'
import { queryKeys } from '@/lib/query/keys'
import {
  AssignmentAttachment,
  MAX_ASSIGNMENT_ATTACHMENTS,
  MAX_ASSIGNMENT_ATTACHMENT_BYTES,
  deleteAssignmentAttachment,
  listAssignmentAttachments,
  readAssignmentAttachmentError,
  reorderAssignmentAttachments,
  uploadAssignmentAttachment,
} from '@services/ext/assignAttachments'

import { formatAttachmentSize } from './format'

/** 和后端 validate_upload 接受的后缀保持一致。 */
const ACCEPT =
  '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.jpg,.jpeg,.png,.gif,.webp'

type Props = {
  assignmentUuid: string
  accessToken: string
}

export default function AttachmentsEditor({ assignmentUuid, accessToken }: Props) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const fileInputRef = React.useRef<HTMLInputElement | null>(null)

  // 上传是逐个进行的，这里记「第几个 / 共几个」，用于按钮上的进度文案。
  const [uploadProgress, setUploadProgress] = React.useState<{
    done: number
    total: number
  } | null>(null)
  // 重排 / 删除期间禁用操作，避免连点把顺序或列表搞乱。
  const [busy, setBusy] = React.useState(false)
  const operationPending = React.useRef(false)

  const listKey = queryKeys.ext.assignAttachments.list(assignmentUuid)
  const { data: attachments = [], isLoading, isError, error } = useQuery({
    queryKey: listKey,
    queryFn: () => listAssignmentAttachments(assignmentUuid, accessToken),
    enabled: !!assignmentUuid && !!accessToken,
    retry: false,
    staleTime: 10_000,
  })

  const refresh = () => queryClient.invalidateQueries({ queryKey: listKey })

  const uploading = uploadProgress !== null
  const disabled = busy || uploading || isLoading || isError

  React.useEffect(() => {
    if (error) toast.error(error.message)
  }, [error])

  async function handlePicked(picked: File[]) {
    if (picked.length === 0 || operationPending.current || isLoading || isError) return

    // 前端先做两道闸：总数超限、单个超大，直接提示，不发请求。
    if (attachments.length + picked.length > MAX_ASSIGNMENT_ATTACHMENTS) {
      toast.error(
        t('ext.assign_attachments.too_many', {
          max: MAX_ASSIGNMENT_ATTACHMENTS,
          defaultValue: '一份作业最多挂 {{max}} 个附件',
        })
      )
      return
    }
    for (const file of picked) {
      if (file.size > MAX_ASSIGNMENT_ATTACHMENT_BYTES) {
        toast.error(
          t('ext.assign_attachments.too_large', {
            name: file.name,
            mb: Math.round(MAX_ASSIGNMENT_ATTACHMENT_BYTES / 1024 / 1024),
            defaultValue: '「{{name}}」超过 {{mb}} MB，无法上传',
          })
        )
        return
      }
    }

    operationPending.current = true
    let uploaded = 0
    try {
      for (let i = 0; i < picked.length; i++) {
        setUploadProgress({ done: i, total: picked.length })
        const res = await uploadAssignmentAttachment(assignmentUuid, picked[i], accessToken)
        if (!res.success) {
          throw new Error(readAssignmentAttachmentError(res.data) ||
            t('ext.assign_attachments.upload_error', { defaultValue: '上传失败，请重试' }))
        }
        uploaded += 1
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message :
        t('ext.assign_attachments.upload_error', { defaultValue: '上传失败，请重试' }))
    } finally {
      if (uploaded > 0) {
        await refresh()
        toast.success(t('ext.assign_attachments.upload_success', {
          count: uploaded,
          defaultValue: '已上传 {{count}} 个附件',
        }))
      }
      setUploadProgress(null)
      operationPending.current = false
    }
  }

  async function move(index: number, delta: number) {
    const target = index + delta
    if (target < 0 || target >= attachments.length || operationPending.current) return
    const next = [...attachments]
    const [moved] = next.splice(index, 1)
    next.splice(target, 0, moved)
    operationPending.current = true
    setBusy(true)
    try {
      const res = await reorderAssignmentAttachments(
        assignmentUuid, next.map((a) => a.attachment_uuid), accessToken
      )
      if (!res.success) throw new Error(readAssignmentAttachmentError(res.data) ||
        t('ext.assign_attachments.order_error', { defaultValue: '调整顺序失败，请重试' }))
      await refresh()
    } catch (error) {
      toast.error(error instanceof Error ? error.message :
        t('ext.assign_attachments.order_error', { defaultValue: '调整顺序失败，请重试' }))
    } finally {
      setBusy(false)
      operationPending.current = false
    }
  }

  async function remove(att: AssignmentAttachment) {
    if (operationPending.current) return
    operationPending.current = true
    setBusy(true)
    try {
      const res = await deleteAssignmentAttachment(att.attachment_uuid, accessToken)
      if (!res.success) throw new Error(readAssignmentAttachmentError(res.data) ||
        t('ext.assign_attachments.delete_error', { defaultValue: '删除失败，请重试' }))
      await refresh()
      toast.success(t('ext.assign_attachments.delete_success', { defaultValue: '附件已删除' }))
    } catch (error) {
      toast.error(error instanceof Error ? error.message :
        t('ext.assign_attachments.delete_error', { defaultValue: '删除失败，请重试' }))
    } finally {
      setBusy(false)
      operationPending.current = false
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-gray-700">
          {t('ext.assign_attachments.title', { defaultValue: '题目附件' })}
        </p>
        <p className="text-[10px] text-gray-400 text-end">
          {t('ext.assign_attachments.hint', {
            defaultValue: '学生打开作业即可下载，不受参考答案揭晓规则限制',
          })}
        </p>
      </div>

      <div className="rounded-xl border border-gray-100 bg-white nice-shadow overflow-hidden">
        {isLoading ? (
          <div className="flex items-center gap-2 px-3 py-4 text-[11px] text-gray-400">
            <Loader2 size={13} className="animate-spin" />
            {t('ext.common.loading', { defaultValue: '正在加载…' })}
          </div>
        ) : attachments.length === 0 ? (
          <div className="flex items-center gap-2 px-3 py-4 text-[11px] text-gray-400">
            <Paperclip size={13} className="flex-none" />
            {t('ext.assign_attachments.empty', {
              defaultValue: '还没有题目附件，学生打开作业时看不到这一块',
            })}
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {attachments.map((att, index) => (
              <li key={att.attachment_uuid} className="flex items-center gap-2 px-3 py-2">
                <FileText size={14} className="flex-none text-sky-500" />
                <div className="flex flex-col min-w-0 flex-1">
                  <p
                    className="text-[11px] font-semibold text-gray-700 truncate"
                    title={att.original_name}
                  >
                    {att.original_name}
                  </p>
                  <p className="text-[10px] text-gray-400">
                    {formatAttachmentSize(att.size)}
                  </p>
                </div>

                <div className="flex flex-none items-center gap-1">
                  <button
                    type="button"
                    onClick={() => move(index, -1)}
                    disabled={index === 0 || disabled}
                    aria-label={t('ext.assign_attachments.move_up', {
                      defaultValue: '上移',
                    })}
                    className="inline-flex h-7 w-7 items-center justify-center rounded-md text-gray-500 bg-gray-100 hover:bg-gray-200 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <ArrowUp size={12} />
                  </button>
                  <button
                    type="button"
                    onClick={() => move(index, 1)}
                    disabled={index === attachments.length - 1 || disabled}
                    aria-label={t('ext.assign_attachments.move_down', {
                      defaultValue: '下移',
                    })}
                    className="inline-flex h-7 w-7 items-center justify-center rounded-md text-gray-500 bg-gray-100 hover:bg-gray-200 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <ArrowDown size={12} />
                  </button>
                  <ConfirmDanger
                    title={t('ext.assign_attachments.delete_title', {
                      defaultValue: '删除这个附件？',
                    })}
                    message={t('ext.assign_attachments.delete_confirm', {
                      name: att.original_name,
                      defaultValue:
                        '「{{name}}」会从这份作业里删除，学生将无法再下载。这一步不能撤销。',
                    })}
                    confirmText={t('ext.common.delete', { defaultValue: '删除' })}
                    onConfirm={() => remove(att)}
                    trigger={
                      <button
                        type="button"
                        disabled={disabled}
                        aria-label={t('ext.common.delete', { defaultValue: '删除' })}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-md text-rose-700 bg-rose-50 hover:bg-rose-100 transition-colors"
                      >
                        <Trash2 size={12} />
                      </button>
                    }
                  />
                </div>
              </li>
            ))}
          </ul>
        )}

        <div className="border-t border-gray-100 px-3 py-2 bg-gray-50/50">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled || attachments.length >= MAX_ASSIGNMENT_ATTACHMENTS}
            className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[10px] font-bold uppercase tracking-wider text-gray-700 bg-white border border-gray-200 nice-shadow hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {uploading ? (
              <>
                <Loader2 size={12} className="animate-spin" />
                {t('ext.assign_attachments.uploading', {
                  done: (uploadProgress?.done ?? 0) + 1,
                  total: uploadProgress?.total ?? 0,
                  defaultValue: '正在上传 {{done}}/{{total}}',
                })}
              </>
            ) : (
              <>
                <Upload size={12} />
                {t('ext.assign_attachments.upload', { defaultValue: '上传附件' })}
              </>
            )}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => {
              const files = e.target.files
              // 先取出再清空：清空后 FileList 会失效，而且重选同一个文件也要能触发。
              const picked = files ? Array.from(files) : []
              e.target.value = ''
              if (picked.length > 0) {
                void handlePicked(picked)
              }
            }}
          />
          <p className="text-[10px] text-gray-400 mt-1.5">
            {t('ext.assign_attachments.limit', {
              max: MAX_ASSIGNMENT_ATTACHMENTS,
              mb: Math.round(MAX_ASSIGNMENT_ATTACHMENT_BYTES / 1024 / 1024),
              defaultValue:
                'PDF / Word / Excel / PPT / 图片，单个不超过 {{mb}} MB，最多 {{max}} 个',
            })}
          </p>
        </div>
      </div>
    </div>
  )
}
