'use client'
/**
 * 教学工具概览：把注册表里的工具画成卡片网格。
 *
 * 不需要维护 —— 其他代理往 `registry.ts` 的 `SYSU_TOOLS` 里加条目，
 * 这页自动多出一张卡片。
 */
import React from 'react'
import Link from 'next/link'
import { ArrowRight, Wrench } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import useAdminStatus from '@components/Hooks/useAdminStatus'
import { useOrg } from '@components/Contexts/OrgContext'
import { getUriWithOrg } from '@services/config/config'

import { visibleToolCards } from '../../registry'
import RecentActivityCard from './RecentActivityCard'

export default function ToolsOverview() {
  const { t } = useTranslation()
  const org = useOrg() as any
  const { rights, canManageOrg } = useAdminStatus()

  const tools = visibleToolCards(rights, canManageOrg)

  if (tools.length === 0) {
    return (
      <div className="px-4 sm:px-10 pb-10">
        <div className="bg-white nice-shadow rounded-xl py-16 text-center max-w-[1600px] mx-auto">
          <div className="flex flex-col items-center gap-3">
            <div className="bg-gray-100 p-4 rounded-full">
              <Wrench className="w-8 h-8 text-gray-400" />
            </div>
            <p className="text-gray-400 text-sm font-medium">
              {t('ext.overview.empty', { defaultValue: '还没有可用的教学工具' })}
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="px-4 sm:px-10 pb-10 space-y-4">
      {/* 组织级的最近学习动态。数据取不到时整块不渲染，不影响下面的工具网格。 */}
      <RecentActivityCard />
      <div
        className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 max-w-[1600px] mx-auto"
        data-testid="sysu-tools-grid"
      >
        {tools.map((tool) => {
          const Icon = tool.icon
          return (
            <Link
              key={tool.key}
              href={getUriWithOrg(org?.slug ?? '', '') + `/dash/tools/${tool.key}`}
              data-testid={`sysu-tool-card-${tool.key}`}
              className="group bg-white nice-shadow rounded-xl p-5 flex flex-col gap-3 min-w-0 hover:bg-gray-50 transition-colors"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="bg-gray-100 p-2.5 rounded-lg shrink-0">
                  <Icon className="w-5 h-5 text-gray-700" />
                </div>
                <span className="font-semibold text-gray-800 text-sm truncate">
                  {t(tool.titleKey)}
                </span>
              </div>
              <p className="text-gray-400 text-xs font-medium leading-relaxed line-clamp-3">
                {t(tool.descKey)}
              </p>
              <span className="mt-auto pt-2 flex items-center gap-1 text-xs font-medium text-indigo-600 group-hover:text-indigo-800">
                {t('ext.overview.enter', { defaultValue: '进入' })}
                <ArrowRight className="w-3.5 h-3.5" />
              </span>
            </Link>
          )
        })}
      </div>
    </div>
  )
}
