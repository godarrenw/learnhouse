'use client'
/**
 * 作业工具的外壳：五个内部 Tab。
 *
 * 外层那条 `DashTabBar` 是「工具之间」的切换（骨架的路由页渲染的），
 * 这里这一条是「工具内部」的分段，所以用小一号的分段控件，不要再来一条
 * DashTabBar —— 两条一模一样的 Tab 条叠在一起会让人分不清哪条是哪条。
 */
import React, { useState } from 'react'
import {
  CalendarSync,
  FileSearch,
  History,
  ListChecks,
  Sparkles,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { SysuToolProps } from '../../types'

import AiQuizTab from './AiQuizTab'
import CloneTermTab from './CloneTermTab'
import QuickQuizTab from './QuickQuizTab'
import SimilarityTab from './SimilarityTab'
import VersionsTab from './VersionsTab'

const TABS = [
  { key: 'ai', icon: Sparkles, Component: AiQuizTab },
  { key: 'quiz', icon: ListChecks, Component: QuickQuizTab },
  { key: 'similarity', icon: FileSearch, Component: SimilarityTab },
  { key: 'clone', icon: CalendarSync, Component: CloneTermTab },
  { key: 'versions', icon: History, Component: VersionsTab },
] as const

export default function AssignTools({ courseUuid }: SysuToolProps) {
  const { t } = useTranslation()
  const [active, setActive] = useState<string>('ai')
  const current = TABS.find((tab) => tab.key === active) ?? TABS[0]
  const Current = current.Component

  return (
    <div className="px-4 sm:px-10 pb-10">
      <div className="max-w-[1600px] mx-auto w-full space-y-5">
        <div
          role="tablist"
          aria-label={t('ext.tools.assign.title', { defaultValue: '作业工具' })}
          className="flex flex-wrap gap-1.5"
          data-testid="assign-subtabs"
        >
          {TABS.map((tab) => {
            const Icon = tab.icon
            const on = tab.key === active
            return (
              <button
                key={tab.key}
                role="tab"
                type="button"
                aria-selected={on}
                data-testid={`assign-subtab-${tab.key}`}
                onClick={() => setActive(tab.key)}
                className={
                  on
                    ? 'inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium bg-gray-900 text-white cursor-pointer'
                    : 'inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium bg-white nice-shadow text-gray-600 hover:bg-gray-50 transition-colors cursor-pointer'
                }
              >
                <Icon className="w-4 h-4" />
                {t(`ext.tools.assign.tabs.${tab.key}`)}
              </button>
            )
          })}
        </div>

        <Current courseUuid={courseUuid} />
      </div>
    </div>
  )
}
