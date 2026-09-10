/* --- SYSU-SAM: 内容工具 · 邀请码二维码 --- */
'use client'
import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { QrCode, Download } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'

import Modal from '@components/Objects/StyledElements/Modal/Modal'
import LearnHouseSpinner from '@components/Objects/Loaders/LearnHouseSpinner'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { useOrg } from '@components/Contexts/OrgContext'
import { downloadBlob, fetchQrSvg } from '@services/ext/content'
import { queryKeys } from '@/lib/query/keys'

/**
 * 邀请码那一行的二维码按钮：点开显示注册链接的二维码，可以下载 SVG 去印刷。
 *
 * 二维码由后端 `GET /ext/content/qr.svg` 生成，取到 SVG 文本后内联渲染 ——
 * 不能直接 `<img src="…/qr.svg">`，那个接口要 Bearer token，`<img>` 带不了，
 * 会 401 出一个碎图。
 */
function InviteQrButton({ code, signupLink }: { code: string; signupLink: string }) {
  const { t } = useTranslation()
  const org = useOrg() as any
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token
  const orgId: number | undefined = org?.id

  const [open, setOpen] = React.useState(false)

  // 弹窗打开才去取，取回来 react-query 会缓存住，同一个邀请码再打开不用重发。
  const { data: svg, isError } = useQuery({
    queryKey: queryKeys.ext.content.qr(signupLink),
    queryFn: () => fetchQrSvg(signupLink, orgId as number, access_token),
    enabled: open && !!access_token && !!orgId,
    staleTime: Infinity,
  })

  React.useEffect(() => {
    if (!isError) return
    toast.error(t('ext.tools.content.qr.error', { defaultValue: '二维码生成失败，请重试' }))
  }, [isError, t])

  const handleDownload = () => {
    if (!svg) return
    downloadBlob(new Blob([svg], { type: 'image/svg+xml' }), `invite-${code}.svg`)
  }

  return (
    <Modal
      isDialogOpen={open}
      onOpenChange={setOpen}
      minWidth="sm"
      dialogTitle={t('ext.tools.content.qr.title', { defaultValue: '注册二维码' })}
      dialogDescription={t('ext.tools.content.qr.description', {
        defaultValue: '把这张码贴在教室或发到群里，学生扫码就能带着邀请码注册。',
      })}
      dialogTrigger={
        <button
          type="button"
          data-testid="sysu-invite-qr-trigger"
          title={t('ext.tools.content.qr.title', { defaultValue: '注册二维码' })}
          className="flex items-center gap-1.5 h-8 px-3 bg-gray-50 text-gray-600 hover:bg-gray-100 rounded-md text-xs font-semibold transition-all cursor-pointer"
        >
          <QrCode className="w-3.5 h-3.5" />
          <span>{t('ext.tools.content.qr.button', { defaultValue: '二维码' })}</span>
        </button>
      }
      dialogContent={
        <div className="flex flex-col items-center gap-4 py-2" data-testid="sysu-invite-qr-modal">
          {!svg ? (
            <div className="h-[280px] flex items-center justify-center">
              <LearnHouseSpinner size={28} />
            </div>
          ) : (
            <div
              data-testid="sysu-invite-qr-image"
              className="w-[280px] h-[280px] bg-white rounded-xl nice-shadow p-3 flex items-center justify-center [&>svg]:w-full [&>svg]:h-full"
              // 本站后端生成的纯矩形 SVG，没有脚本也没有外链
              dangerouslySetInnerHTML={{ __html: svg }}
            />
          )}
          <div className="w-full max-w-[380px] text-center space-y-1">
            <div className="text-xs text-gray-400 font-medium">
              {t('ext.tools.content.qr.link_label', { defaultValue: '注册链接' })}
            </div>
            <div className="text-xs text-gray-600 break-all">{signupLink}</div>
          </div>
          <button
            type="button"
            onClick={handleDownload}
            disabled={!svg}
            className="flex items-center gap-1.5 h-9 px-4 bg-gray-900 text-white hover:bg-gray-800 disabled:opacity-40 rounded-md text-sm font-semibold transition-all cursor-pointer"
          >
            <Download className="w-4 h-4" />
            <span>{t('ext.tools.content.qr.download', { defaultValue: '下载 SVG' })}</span>
          </button>
        </div>
      }
    />
  )
}

export default InviteQrButton
/* --- /SYSU-SAM --- */
