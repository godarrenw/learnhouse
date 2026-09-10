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
                isDark ? 'bg-zinc-900 text-zinc-100' : 'bg-zinc-50 text-zinc-700'
            } ${className}`}
        >
            <WifiOff
                size={28}
                className={isDark ? 'text-zinc-400' : 'text-zinc-400'}
                aria-hidden="true"
            />
            <p className="text-sm font-medium">
                {t('sysu_campus_media.title', '本内容仅限校园网访问')}
            </p>
            <p
                className={`max-w-sm text-xs leading-relaxed ${
                    isDark ? 'text-zinc-400' : 'text-zinc-500'
                }`}
            >
                {t(
                    'sysu_campus_media.description',
                    '请连接校园网或校园 VPN 后刷新页面。页面上的其它内容不受影响。如果浏览器询问是否允许访问本地网络，请选择「允许」。'
                )}
            </p>
        </div>
    )
}
/* --- SYSU-SAM --- */
