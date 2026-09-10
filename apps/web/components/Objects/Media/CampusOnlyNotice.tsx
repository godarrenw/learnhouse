/* --- SYSU-SAM --- */
'use client'

import React from 'react'
import { WifiOff } from 'lucide-react'
import { useTranslation } from 'react-i18next'

/**
 * 校外用户看到的占位卡片：课程视频 / PDF 讲义只在校园网内提供，
 * 校外用户连不到内部媒体域名，与其让 <video> 转圈或 iframe 空白，
 * 不如直接说清楚。
 *
 * variant='dark' 给视频用（播放器底色是黑的），'light' 给 PDF 用。
 *
 * 文案在 locales/ext/{zh,en}.json 的 campus_media 段。ext 命名空间的加载器
 * 由骨架代理提供，尚未合入时 t() 会回落到这里的 defaultValue，显示中文。
 */
export default function CampusOnlyNotice({
  variant = 'light',
  className = '',
}: {
  variant?: 'dark' | 'light'
  className?: string
}) {
  const { t } = useTranslation()
  const isDark = variant === 'dark'

  return (
    <div
      className={`flex h-full w-full flex-col items-center justify-center gap-2 px-6 py-10 text-center ${
        isDark ? 'bg-gray-900 text-gray-100' : 'bg-gray-50 text-gray-700'
      } ${className}`}
    >
      <WifiOff size={28} className="text-gray-400" aria-hidden="true" />
      <p className="text-sm font-medium">
        {t('ext.campus_media.title', { defaultValue: '本内容仅限校园网访问' })}
      </p>
      <p
        className={`max-w-sm text-xs leading-relaxed ${
          isDark ? 'text-gray-400' : 'text-gray-500'
        }`}
      >
        {t('ext.campus_media.description', {
          defaultValue:
            '请连接校园网或校园 VPN 后刷新页面。页面上的其它内容不受影响。',
        })}
      </p>
    </div>
  )
}
/* --- SYSU-SAM END --- */
