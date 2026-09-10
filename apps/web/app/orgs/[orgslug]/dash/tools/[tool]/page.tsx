'use client'
/**
 * 教学工具的容器路由：按路径段 key 从 registry 里取出对应的工具组件渲染。
 *
 * ⚠️ 这个文件属于骨架代理。feat/checkin 先落地时它还不存在，为了让签到功能
 * 真的能打开、也让 tests/ext/checkin.spec.ts 跑得起来，这里放了一份**占位实现**。
 * rebase 到骨架之后，如果骨架自己有这个文件，**删掉本文件用骨架的**，
 * 签到侧不需要任何改动（URL 仍是 /dash/tools/checkin）。
 *
 * 版式按 UI_GUIDE 3.9 的标准后台页面：外层 bg-[#f8f8f8]，页头盒子
 * bg-[#fcfbfc] + nice-shadow + 面包屑 + 大标题 + 副标题，内容区 motion 淡入。
 */
import React, { use } from 'react'
import { notFound } from 'next/navigation'
import { motion } from 'motion/react'
import { Wrench } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Breadcrumbs } from '@components/Objects/Breadcrumbs/Breadcrumbs'
import { getSysuTool } from '@components/SysuTools/registry'

type ToolParams = {
  orgslug: string
  tool: string
}

function SysuToolPage(props: { params: Promise<ToolParams> }) {
  const { t } = useTranslation()
  const params = use(props.params)
  const tool = getSysuTool(params.tool)

  if (!tool) {
    notFound()
  }

  const ToolBody = tool.component

  return (
    <div className="h-screen w-full bg-[#f8f8f8] grid grid-rows-[auto_1fr] grid-cols-1 overflow-hidden">
      <div className="ps-4 pe-4 sm:ps-10 sm:pe-10 tracking-tight bg-[#fcfbfc] z-10 nice-shadow flex-shrink-0 relative">
        <div className="pt-6 pb-4">
          <Breadcrumbs
            items={[
              {
                label: t(tool.titleKey, { defaultValue: tool.key }),
                href: tool.href,
                icon: <Wrench size={14} />,
              },
            ]}
          />
        </div>
        <div className="my-2 py-3">
          <div className="w-full flex flex-col space-y-1 min-w-0">
            <div className="pt-3 flex font-bold text-3xl sm:text-4xl tracking-tighter truncate">
              {t(tool.titleKey, { defaultValue: tool.key })}
            </div>
            <div className="flex font-medium text-gray-400 text-md truncate">
              {t(tool.subtitleKey, { defaultValue: '' })}
            </div>
          </div>
        </div>
      </div>

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.1, type: 'spring', stiffness: 80 }}
        className="min-w-0 overflow-y-auto overflow-x-hidden"
      >
        <div className="h-6" />
        <ToolBody />
      </motion.div>
    </div>
  )
}

export default SysuToolPage
