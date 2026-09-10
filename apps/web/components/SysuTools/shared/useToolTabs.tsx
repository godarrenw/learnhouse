'use client'
/**
 * 教学工具的 Tab 条数据：概览 + 当前用户有权限的每个工具。
 *
 * 概览页和工具页共用，所以不放在 page.tsx 里（Next 的 page 文件只该导出
 * 默认组件和 metadata 之类的约定成员）。
 */
import React from 'react'
import { useTranslation } from 'react-i18next'

import useAdminStatus from '@components/Hooks/useAdminStatus'
import { DashTabItem } from '@components/Dashboard/Shared/DashTabBar/DashTabBar'
import { getUriWithOrg } from '@services/config/config'

import { OVERVIEW_KEY, SYSU_TOOLS, filterToolsByRights } from '../registry'

export default function useToolTabs(orgslug: string, activeKey: string): DashTabItem[] {
  const { t } = useTranslation()
  const { rights, canManageOrg } = useAdminStatus()

  return filterToolsByRights(SYSU_TOOLS, rights, canManageOrg).map((tool) => {
    const Icon = tool.icon
    return {
      key: tool.key,
      // 概览的 titleKey 就是页面 H1（「教学工具」），拿它当 Tab 标签会和标题重复，
      // 所以概览这一项单独给一个短标签。
      label: tool.key === OVERVIEW_KEY ? t('ext.overview.tab') : t(tool.titleKey),
      icon: <Icon size={16} />,
      href: getUriWithOrg(orgslug, '') + `/dash/tools/${tool.key}`,
      active: tool.key === activeKey,
    }
  })
}
