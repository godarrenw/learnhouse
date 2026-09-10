'use client'
/**
 * `/dash/tools` —— 教学工具概览。
 *
 * 页面本体在 `components/SysuTools/tools/Overview/ToolsOverview.tsx`，
 * 这里只负责版式（页头三件套 + Tab 条 + 内容区淡入）。
 * `/dash/tools/overview` 走 `[tool]/page.tsx` 渲染同一个组件。
 */
import React, { Suspense, use } from 'react'
import { motion } from 'motion/react'
import { useTranslation } from 'react-i18next'

import LearnHouseSpinner from '@components/Objects/Loaders/LearnHouseSpinner'
import ToolPageHeader from '@components/SysuTools/shared/ToolPageHeader'
import useToolTabs from '@components/SysuTools/shared/useToolTabs'
import { OVERVIEW_KEY, getTool } from '@components/SysuTools/registry'

type ToolsParams = {
  orgslug: string
}

function ToolsOverviewPage(props: { params: Promise<ToolsParams> }) {
  const { t } = useTranslation()
  const params = use(props.params)
  const tabs = useToolTabs(params.orgslug, OVERVIEW_KEY)

  const OverviewComponent = getTool(OVERVIEW_KEY)?.component

  return (
    <div className="h-screen w-full bg-[#f8f8f8] grid grid-rows-[auto_1fr] grid-cols-1 overflow-hidden">
      <ToolPageHeader
        title={t('ext.overview.title', { defaultValue: '教学工具' })}
        subtitle={t('ext.overview.subtitle', { defaultValue: '选择一个工具开始' })}
        tabs={tabs}
      />
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.1, type: 'spring', stiffness: 80 }}
        className="min-w-0 overflow-y-auto overflow-x-hidden"
      >
        <div className="h-6" />
        {OverviewComponent ? (
          <Suspense
            fallback={
              <div className="flex justify-center py-16">
                <LearnHouseSpinner size={28} />
              </div>
            }
          >
            <OverviewComponent />
          </Suspense>
        ) : null}
      </motion.div>
    </div>
  )
}

export default ToolsOverviewPage
