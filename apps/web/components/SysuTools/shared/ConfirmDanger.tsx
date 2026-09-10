'use client'
/**
 * 危险操作确认。只是给上游 `ConfirmationModal` 套了一层默认值，
 * 省得每个工具都重复传 status / pendingButtonText。
 *
 * **不要**用原生 `confirm()`，也不要自己写弹窗。
 */
import React from 'react'
import { useTranslation } from 'react-i18next'

import ConfirmationModal from '@components/Objects/StyledElements/ConfirmationModal/ConfirmationModal'

interface ConfirmDangerProps {
  /** 弹窗标题，已经 t() 过。 */
  title: string
  /** 正文，说明这个操作会造成什么后果。 */
  message: string
  /** 触发元素，通常是一个删除按钮。 */
  trigger: React.ReactNode
  /**
   * 确认后执行。可以是 async —— ConfirmationModal 会 await 它并在期间禁用
   * 按钮防重复提交。错误由这个函数自己 toast，弹窗无论成败都会关闭。
   */
  onConfirm: () => void | Promise<void>
  /** 确认按钮文案，默认「删除」。 */
  confirmText?: string
  /** 'warning' 红（默认，用于删除）；'info' 蓝（用于一般的二次确认）。 */
  status?: 'warning' | 'info'
}

export default function ConfirmDanger({
  title,
  message,
  trigger,
  onConfirm,
  confirmText,
  status = 'warning',
}: ConfirmDangerProps) {
  const { t } = useTranslation()

  return (
    <ConfirmationModal
      dialogTitle={title}
      confirmationMessage={message}
      confirmationButtonText={confirmText ?? t('ext.common.delete', { defaultValue: '删除' })}
      pendingButtonText={t('ext.common.deleting', { defaultValue: '正在删除…' })}
      functionToExecute={onConfirm}
      status={status}
      dialogTrigger={trigger}
    />
  )
}
