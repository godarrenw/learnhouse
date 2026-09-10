'use client'
/**
 * 学情工具：成绩册 / 缺交 / 学习进度 / 课程体检。
 *
 * 课程选择器由路由页统一渲染（`courseScoped: true`），这里只收 `courseUuid`。
 * 四个子 Tab 用组件内 state 切换，不改 URL —— `/dash/tools/[tool]` 的动态段
 * 已经被工具 key 占了，工具内部再占一段会和它打架；命令面板的入口指向工具本身。
 */
import React from 'react'
import { motion } from 'motion/react'
import { useTranslation } from 'react-i18next'
import { ClipboardList, Stethoscope, Table2, TrendingUp } from 'lucide-react'

import { DashTabBar, DashTabItem } from '@components/Dashboard/Shared/DashTabBar/DashTabBar'
import type { SysuToolProps } from '@components/SysuTools/types'

import GradebookTab from './GradebookTab'
import MissingTab from './MissingTab'
import ProgressTab from './ProgressTab'
import LintTab from './LintTab'

type SubTab = 'gradebook' | 'missing' | 'progress' | 'lint'

const SUBTABS: { key: SubTab; icon: React.ComponentType<any> }[] = [
  { key: 'gradebook', icon: Table2 },
  { key: 'missing', icon: ClipboardList },
  { key: 'progress', icon: TrendingUp },
  { key: 'lint', icon: Stethoscope },
]

export default function LearningTool({ courseUuid }: SysuToolProps) {
  const { t } = useTranslation()
  const [subtab, setSubtab] = React.useState<SubTab>('gradebook')

  const tabs: DashTabItem[] = SUBTABS.map(({ key, icon: Icon }) => ({
    key,
    label: t(`ext.tools.learning.tabs.${key}`),
    icon: <Icon size={16} />,
    onClick: () => setSubtab(key),
    active: subtab === key,
  }))

  return (
    <div className="min-w-0" data-testid="learning-tool">
      <div className="px-4 sm:px-10 max-w-[1600px] mx-auto w-full">
        <DashTabBar tabs={tabs} />
      </div>
      <div className="h-6" />
      <motion.div
        key={subtab}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.1, type: 'spring', stiffness: 80 }}
        className="min-w-0"
      >
        {subtab === 'gradebook' ? <GradebookTab courseUuid={courseUuid} /> : null}
        {subtab === 'missing' ? <MissingTab courseUuid={courseUuid} /> : null}
        {subtab === 'progress' ? <ProgressTab courseUuid={courseUuid} /> : null}
        {subtab === 'lint' ? <LintTab courseUuid={courseUuid} /> : null}
      </motion.div>
    </div>
  )
}
