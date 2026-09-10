'use client'
/**
 * 示例工具：调后端 `GET /ext/health` 并把结果画出来。
 *
 * 它存在的意义有两个：
 *  1. 证明前后端扩展点是通的（菜单 → 路由 → 注册表 → 接口 → 鉴权 → 数据）。
 *  2. 给其他工具当模板 —— 三态（加载 / 空 / 错误）、toast、react-query、
 *     共用 DataTable 的用法都在这一个文件里。
 */
import React from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'

import { useLHSession } from '@components/Contexts/LHSessionContext'
import { useOrg } from '@components/Contexts/OrgContext'
import { getExtHealth } from '@services/ext/ext'
import { queryKeys } from '@/lib/query/keys'

import DataTable, { DataTableColumn } from '../../shared/DataTable'

interface HealthRow {
  key: string
  label: string
  value: string
}

export default function ExampleTool() {
  const { t } = useTranslation()
  const org = useOrg() as any
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token
  const queryClient = useQueryClient()
  const orgId: number = org?.id ?? 0

  const { data, isFetching, isError, error } = useQuery({
    queryKey: queryKeys.ext.health(orgId),
    queryFn: () => getExtHealth(orgId, access_token),
    enabled: !!orgId && !!access_token,
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  })

  const isInitialLoading = !data && isFetching
  const isRefreshing = !!data && isFetching

  const rows: HealthRow[] = data
    ? [
        { key: 'status', label: t('ext.tools.example.status'), value: data.status },
        {
          key: 'ext_version',
          label: t('ext.tools.example.ext_version'),
          value: data.ext_version,
        },
        { key: 'org_id', label: t('ext.tools.example.org_id'), value: String(data.org_id) },
        {
          key: 'user_id',
          label: t('ext.tools.example.user_id'),
          value: String(data.user_id),
        },
        { key: 'username', label: t('ext.tools.example.username'), value: data.username },
        {
          key: 'role',
          label: t('ext.tools.example.role'),
          value: data.role ?? t('ext.tools.example.role_unknown'),
        },
        {
          key: 'tools',
          label: t('ext.tools.example.tools'),
          value: data.tools.join(', '),
        },
      ]
    : []

  const columns: DataTableColumn<HealthRow>[] = [
    {
      key: 'field',
      header: t('ext.tools.example.field', { defaultValue: '字段' }),
      cell: (row) => <span className="font-semibold text-gray-800 text-sm">{row.label}</span>,
    },
    {
      key: 'value',
      header: t('ext.tools.example.value', { defaultValue: '取值' }),
      cell: (row) => <span className="text-gray-600 text-sm font-mono">{row.value}</span>,
    },
  ]

  async function handleRefresh() {
    const toastId = toast.loading(t('ext.common.loading', { defaultValue: '正在加载…' }))
    try {
      await queryClient.invalidateQueries({ queryKey: queryKeys.ext.health(orgId) })
      toast.success(t('ext.tools.example.loaded', { defaultValue: '扩展层连通正常' }), {
        id: toastId,
      })
    } catch {
      toast.error(t('ext.tools.example.error'), { id: toastId })
    }
  }

  return (
    <div className="px-4 sm:px-10 pb-10">
      <div className="max-w-[1600px] mx-auto flex justify-end pb-4">
        <button
          onClick={handleRefresh}
          disabled={isFetching}
          data-testid="sysu-ext-refresh"
          className="flex items-center gap-1.5 bg-white nice-shadow rounded-lg px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors cursor-pointer disabled:opacity-50"
        >
          <RefreshCw className="w-4 h-4" />
          {t('ext.tools.example.fetch', { defaultValue: '重新检测' })}
        </button>
      </div>

      {isError && !data ? (
        <div
          className="bg-white nice-shadow rounded-xl py-16 text-center max-w-[1600px] mx-auto"
          data-testid="sysu-ext-error"
        >
          <div className="flex flex-col items-center gap-3">
            <div className="bg-red-100 p-4 rounded-full">
              <Activity className="w-8 h-8 text-red-600" />
            </div>
            <p className="text-gray-400 text-sm font-medium">
              {t('ext.tools.example.error')}
            </p>
            <p className="text-gray-400 text-xs font-mono max-w-md truncate">
              {(error as any)?.message ?? ''}
            </p>
            <button
              onClick={handleRefresh}
              className="text-xs text-indigo-600 hover:text-indigo-800 font-medium cursor-pointer"
            >
              {t('ext.common.retry', { defaultValue: '重试' })}
            </button>
          </div>
        </div>
      ) : (
        <div data-testid="sysu-ext-health">
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(row) => row.key}
            isInitialLoading={isInitialLoading}
            isRefreshing={isRefreshing}
            emptyIcon={Activity}
          />
        </div>
      )}
    </div>
  )
}
