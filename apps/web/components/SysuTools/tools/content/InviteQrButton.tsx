/* --- SYSU-SAM: 内容工具 · 邀请码二维码 --- */
'use client'
import React from 'react'
import { QrCode, Download } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'

import Modal from '@components/Objects/StyledElements/Modal/Modal'
import LearnHouseSpinner from '@components/Objects/Loaders/LearnHouseSpinner'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { getAPIUrl } from '@services/config/config'
import { RequestBodyWithAuthHeader } from '@services/utils/ts/requests'

/**
 * 邀请码那一行的二维码按钮：点开显示注册链接的二维码，可以下载 SVG 去印刷。
 *
 * 二维码由后端 `GET /ext/content/qr.svg` 生成。之所以不直接把地址塞进
 * `<img src>`：那个接口要 Bearer token，`<img>` 带不了，会 401 出一个碎图。
 * 所以这里用 fetch 拿到 SVG 文本再内联渲染。
 */
function InviteQrButton({ code, signupLink }: { code: string; signupLink: string }) {
  const { t } = useTranslation()
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token

  const [open, setOpen] = React.useState(false)
  const [svg, setSvg] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(false)

  React.useEffect(() => {
    if (!open || svg || !access_token) return
    let cancelled = false
    setLoading(true)
    const url = `${getAPIUrl()}ext/content/qr.svg?text=${encodeURIComponent(signupLink)}&scale=8`
    fetch(url, RequestBodyWithAuthHeader('GET', null, null, access_token))
      .then((res) => {
        if (!res.ok) throw new Error(String(res.status))
        return res.text()
      })
      .then((text) => {
        if (!cancelled) setSvg(text)
      })
      .catch(() => {
        if (!cancelled) {
          toast.error(
            t('content.invite_qr.error', { defaultValue: '二维码生成失败，请重试' })
          )
          setOpen(false)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, svg, access_token, signupLink, t])

  const handleDownload = () => {
    if (!svg) return
    const blob = new Blob([svg], { type: 'image/svg+xml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `invite-${code}.svg`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  return (
    <Modal
      isDialogOpen={open}
      onOpenChange={setOpen}
      minWidth="sm"
      dialogTitle={t('content.invite_qr.title', { defaultValue: '注册二维码' })}
      dialogDescription={t('content.invite_qr.description', {
        defaultValue: '把这张码贴在教室或发到群里，学生扫码就能带着邀请码注册。',
      })}
      dialogTrigger={
        <button
          type="button"
          title={t('content.invite_qr.title', { defaultValue: '注册二维码' })}
          className="flex items-center gap-1.5 h-8 px-3 bg-gray-50 text-gray-600 hover:bg-gray-100 rounded-md text-xs font-semibold transition-all cursor-pointer"
        >
          <QrCode className="w-3.5 h-3.5" />
          <span>{t('content.invite_qr.button', { defaultValue: '二维码' })}</span>
        </button>
      }
      dialogContent={
        <div className="flex flex-col items-center gap-4 py-2">
          {loading || !svg ? (
            <div className="h-[280px] flex items-center justify-center">
              <LearnHouseSpinner size={28} />
            </div>
          ) : (
            <div
              className="w-[280px] h-[280px] bg-white rounded-xl nice-shadow p-3 flex items-center justify-center [&>svg]:w-full [&>svg]:h-full"
              // 内容是本站后端生成的纯矩形 SVG，没有脚本也没有外链
              dangerouslySetInnerHTML={{ __html: svg }}
            />
          )}
          <div className="w-full max-w-[380px] text-center space-y-1">
            <div className="text-xs text-gray-400 font-medium">
              {t('content.invite_qr.link_label', { defaultValue: '注册链接' })}
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
            <span>{t('content.invite_qr.download', { defaultValue: '下载 SVG' })}</span>
          </button>
        </div>
      }
    />
  )
}

export default InviteQrButton
/* --- /SYSU-SAM --- */
