'use client'
/**
 * 教学工具页面的标准页头：面包屑 + H1 + 副标题 +（可选）Tab 条。
 *
 * 版式完全照 UI_GUIDE 3.2 的「页头三件套」，各工具不要自己写，
 * 否则一眼能看出不是同一个产品。
 */
import React from 'react'
import { Wrench } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Breadcrumbs } from '@components/Objects/Breadcrumbs/Breadcrumbs'
import { DashTabBar, DashTabItem } from '@components/Dashboard/Shared/DashTabBar/DashTabBar'

interface ToolPageHeaderProps {
  /** 主标题。已经 t() 过的文案。 */
  title: string
  /** 副标题。已经 t() 过的文案。 */
  subtitle?: string
  /** 面包屑里「教学工具」之后追加的那一层，通常是当前工具名。 */
  currentLabel?: string
  /** Tab 条，不传就不渲染。 */
  tabs?: DashTabItem[]
  /** 页头底部的额外内容，例如课程选择器。 */
  children?: React.ReactNode
}

export default function ToolPageHeader({
  title,
  subtitle,
  currentLabel,
  tabs,
  children,
}: ToolPageHeaderProps) {
  const { t } = useTranslation()

  const items = [
    {
      label: t('ext.breadcrumb', { defaultValue: '教学工具' }),
      href: '/dash/tools',
      icon: <Wrench size={14} />,
    },
    ...(currentLabel ? [{ label: currentLabel }] : []),
  ]

  return (
    <div className="ps-4 pe-4 sm:ps-10 sm:pe-10 tracking-tight bg-[#fcfbfc] z-10 nice-shadow shrink-0 relative">
      <div className="pt-6 pb-4">
        <Breadcrumbs items={items} />
      </div>
      <div className="my-2 py-3">
        <div className="w-full flex flex-col space-y-1 min-w-0">
          <div className="pt-3 flex font-bold text-3xl sm:text-4xl tracking-tighter truncate">
            {title}
          </div>
          {subtitle ? (
            <div className="flex font-medium text-gray-400 text-md truncate">{subtitle}</div>
          ) : null}
        </div>
      </div>
      {children}
      {tabs && tabs.length > 0 ? <DashTabBar tabs={tabs} /> : null}
    </div>
  )
}
