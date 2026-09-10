'use client'
/**
 * `/dash/tools/<tool>` —— 按注册表动态渲染一个教学工具。
 *
 * 其他代理不需要动这个文件：往 `components/SysuTools/registry.ts` 的
 * `SYSU_TOOLS` 里加条目就会自动多出一个路由。
 *
 * 三件事在这里统一做掉：
 *  - 未知 tool → 404
 *  - 权限不足 → 404（不泄露「有这么个工具但你看不到」）
 *  - `courseScoped` 的工具 → 页头下渲染 CourseSelect，把 courseUuid 传下去
 */
import React, { Suspense, use, useState } from 'react'
import { notFound } from 'next/navigation'
import { motion } from 'motion/react'
import { useTranslation } from 'react-i18next'

import useAdminStatus from '@components/Hooks/useAdminStatus'
import LearnHouseSpinner from '@components/Objects/Loaders/LearnHouseSpinner'
import CourseSelect from '@components/SysuTools/shared/CourseSelect'
import ToolPageHeader from '@components/SysuTools/shared/ToolPageHeader'
import useToolTabs from '@components/SysuTools/shared/useToolTabs'
import { OVERVIEW_KEY, filterToolsByRights, getTool } from '@components/SysuTools/registry'

type ToolParams = {
  orgslug: string
  tool: string
}

function ToolPage(props: { params: Promise<ToolParams> }) {
  const { t } = useTranslation()
  const params = use(props.params)
  const { rights, canManageOrg, loading } = useAdminStatus()
  const [courseUuid, setCourseUuid] = useState<string | undefined>(undefined)
  const tabs = useToolTabs(params.orgslug, params.tool)

  const tool = getTool(params.tool)
  // 权限判断放在 hooks 之后，避免提前 return 打乱 hooks 顺序。
  // 还在解析角色时先不下结论，否则首屏会把管理员误判成没权限。
  const allowed =
    !!tool && filterToolsByRights([tool], rights, canManageOrg).length > 0

  if (loading) {
    return (
      <div className="flex justify-center items-center h-screen bg-[#f8f8f8]">
        <LearnHouseSpinner size={28} />
      </div>
    )
  }

  if (!tool || !allowed) {
    notFound()
  }

  const ToolComponent = tool.component
  const isOverview = tool.key === OVERVIEW_KEY

  return (
    <div className="h-screen w-full bg-[#f8f8f8] grid grid-rows-[auto_1fr] grid-cols-1 overflow-hidden">
      <ToolPageHeader
        title={t(tool.titleKey)}
        subtitle={t(tool.descKey)}
        currentLabel={isOverview ? undefined : t(tool.titleKey)}
        tabs={tabs}
      >
        {tool.courseScoped ? (
          <CourseSelect value={courseUuid} onChange={setCourseUuid} />
        ) : null}
      </ToolPageHeader>

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.1, type: 'spring', stiffness: 80 }}
        className="min-w-0 overflow-y-auto overflow-x-hidden"
      >
        <div className="h-6" />
        <Suspense
          fallback={
            <div className="flex justify-center py-16">
              <LearnHouseSpinner size={28} />
            </div>
          }
        >
          <ToolComponent courseUuid={tool.courseScoped ? courseUuid : undefined} />
        </Suspense>
      </motion.div>
    </div>
  )
}

export default ToolPage
