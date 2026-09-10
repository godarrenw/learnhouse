'use client'
/**
 * 内容页版本回滚：版本列表 → 两栏 diff → 危险确认回滚。
 *
 * diff 是后端在 Markdown 文本行上做的 unified diff（不是 tiptap JSON 的 diff，
 * 那全是结构噪音）。回滚前后端会先把当前内容存成新版本，所以现在这一稿不会丢。
 */
import React, { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { History, RotateCcw } from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'

import ConfirmationModal from '@components/Objects/StyledElements/ConfirmationModal/ConfirmationModal'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { useOrg } from '@components/Contexts/OrgContext'
import { getVersionDiff, getVersions, restoreVersion } from '@services/ext/assign'
import { asArray } from '@services/utils/ts/requests'
import { cn } from '@/lib/utils'

import { assignKeys } from './keys'
import { Card, EmptyState, Field, NeedCourse, PrimaryButton, Select, Skeleton } from './ui'
import { useCourseTree } from './useCourseTree'

export default function VersionsTab({ courseUuid }: { courseUuid?: string }) {
  const { t } = useTranslation()
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token
  const org = useOrg() as any
  const orgId: number = org?.id ?? 0
  const queryClient = useQueryClient()
  const { pages } = useCourseTree(courseUuid)

  const [activityUuid, setActivityUuid] = useState('')
  // 选中的版本连着它属于哪一页一起存。换页时旧的选择自然失效，
  // 不用 useEffect 去清 state（那会多触发一轮渲染，lint 也不让）。
  const [picked, setPicked] = useState<{ page: string; version: number } | null>(null)
  const [view, setView] = useState<'split' | 'unified'>('split')

  const selected = picked && picked.page === activityUuid ? picked.version : null
  const setSelected = (version: number | null) =>
    setPicked(version === null ? null : { page: activityUuid, version })

  const versionsQuery = useQuery({
    queryKey: assignKeys.versions(activityUuid),
    queryFn: () => getVersions(orgId, activityUuid, access_token),
    enabled: !!orgId && !!activityUuid && !!access_token,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  })
  const versionsData = versionsQuery.data as any
  const versions = asArray<any>(versionsData?.versions)

  const diffQuery = useQuery({
    queryKey: assignKeys.diff(activityUuid, selected, null),
    queryFn: () => getVersionDiff(orgId, activityUuid, selected, null, access_token),
    enabled: !!orgId && !!activityUuid && selected !== null && !!access_token,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  })
  const diff = diffQuery.data as any

  async function handleRestore() {
    if (!activityUuid || selected === null) return
    const toastId = toast.loading(
      t('ext.tools.assign.ver.restoring', { defaultValue: '正在回滚…' })
    )
    const res = await restoreVersion(orgId, activityUuid, selected, true, access_token)
    if (!res.success) {
      toast.error(
        res.data?.detail || t('ext.tools.assign.ver.error', { defaultValue: '回滚失败' }),
        { id: toastId }
      )
      return
    }
    queryClient.invalidateQueries({ queryKey: assignKeys.all })
    toast.success(
      t('ext.tools.assign.ver.restored', {
        defaultValue: '已回滚到 v{{n}}，当前版本是 v{{cur}}',
        n: selected,
        cur: res.data.current_version,
      }),
      { id: toastId }
    )
    setSelected(null)
  }

  if (!courseUuid) return <NeedCourse />

  const versionsInitialLoading = !versionsData && versionsQuery.isFetching

  return (
    <div className="space-y-6" data-testid="assign-tab-versions">
      <Card title={t('ext.tools.assign.ver.pick', { defaultValue: '选一个内容页' })}>
        <Field label={t('ext.tools.assign.ai.page', { defaultValue: '内容页' })}>
          <Select
            data-testid="assign-ver-page"
            value={activityUuid}
            onChange={(e) => setActivityUuid(e.target.value)}
          >
            <option value="">
              {t('ext.tools.assign.ai.pick_page', { defaultValue: '选择一个内容页' })}
            </option>
            {pages.map((p) => (
              <option key={p.activity_uuid} value={p.activity_uuid}>
                {p.chapterName} / {p.name}
              </option>
            ))}
          </Select>
        </Field>
      </Card>

      {!activityUuid ? null : versionsInitialLoading ? (
        <Card>
          <Skeleton rows={4} />
        </Card>
      ) : versions.length === 0 ? (
        <Card>
          <EmptyState
            icon={History}
            message={t('ext.tools.assign.ver.none', {
              defaultValue: '这一页还没有历史版本。编辑器每保存一次会存一版。',
            })}
          />
        </Card>
      ) : (
        <>
          <Card
            testId="assign-ver-list"
            title={t('ext.tools.assign.ver.list', {
              defaultValue: '历史版本（当前是 v{{cur}}）',
              cur: versionsData?.current_version,
            })}
          >
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                      {t('ext.tools.assign.ver.version', { defaultValue: '版本' })}
                    </th>
                    <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                      {t('ext.tools.assign.ver.time', { defaultValue: '时间' })}
                    </th>
                    <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                      {t('ext.tools.assign.ver.author', { defaultValue: '保存人' })}
                    </th>
                    <th className="text-end text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                      {t('ext.common.actions', { defaultValue: '操作' })}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {versions.map((v: any) => (
                    <tr
                      key={v.version_number}
                      className={cn(
                        'hover:bg-gray-50 transition-colors',
                        selected === v.version_number ? 'bg-indigo-50/40' : ''
                      )}
                    >
                      <td className="px-6 py-4 text-sm font-semibold text-gray-800">
                        v{v.version_number}
                      </td>
                      <td className="px-6 py-4 text-xs text-gray-500">
                        {v.created_at?.replace('T', ' ').slice(0, 19)}
                      </td>
                      <td className="px-6 py-4 text-xs text-gray-500">
                        {v.created_by_username ?? '—'}
                      </td>
                      <td className="px-6 py-4 text-end">
                        <button
                          type="button"
                          data-testid={`assign-ver-compare-${v.version_number}`}
                          onClick={() => setSelected(v.version_number)}
                          className="text-xs text-indigo-600 hover:text-indigo-800 font-medium cursor-pointer"
                        >
                          {t('ext.tools.assign.ver.compare', { defaultValue: '和当前比较' })}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {selected !== null ? (
            <Card
              testId="assign-ver-diff"
              title={t('ext.tools.assign.ver.diff_title', {
                defaultValue: 'v{{n}} 与当前内容的差异',
                n: selected,
              })}
            >
              {!diff ? (
                <Skeleton rows={6} />
              ) : (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-xs text-gray-500">
                      {t('ext.tools.assign.ver.stat', {
                        defaultValue: '新增 {{added}} 行，删除 {{removed}} 行',
                        added: diff.added_lines,
                        removed: diff.removed_lines,
                      })}
                    </p>
                    <div className="flex gap-1.5">
                      {(['split', 'unified'] as const).map((v) => (
                        <button
                          key={v}
                          type="button"
                          onClick={() => setView(v)}
                          data-testid={`assign-ver-view-${v}`}
                          className={
                            view === v
                              ? 'rounded-lg px-3 py-1.5 text-xs font-medium bg-gray-900 text-white cursor-pointer'
                              : 'rounded-lg px-3 py-1.5 text-xs font-medium bg-white nice-shadow text-gray-600 hover:bg-gray-50 cursor-pointer'
                          }
                        >
                          {t(`ext.tools.assign.ver.view_${v}`)}
                        </button>
                      ))}
                    </div>
                  </div>

                  {diff.identical ? (
                    <p className="text-sm text-gray-500">
                      {t('ext.tools.assign.ver.identical', {
                        defaultValue: '这个版本和当前内容完全一样。',
                      })}
                    </p>
                  ) : view === 'split' ? (
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                      {[
                        { label: diff.label_a, text: diff.markdown_a },
                        { label: diff.label_b, text: diff.markdown_b },
                      ].map((side, i) => (
                        <div key={i} className="min-w-0">
                          <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider pb-2">
                            {side.label}
                          </div>
                          <pre className="bg-gray-50 rounded-lg p-3 text-xs text-gray-700 leading-relaxed overflow-x-auto whitespace-pre-wrap break-words max-h-[420px]">
                            {side.text}
                          </pre>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <pre
                      data-testid="assign-ver-unified"
                      className="bg-gray-50 rounded-lg p-3 text-xs leading-relaxed overflow-x-auto max-h-[420px]"
                    >
                      {String(diff.diff)
                        .split('\n')
                        .map((line: string, i: number) => (
                          <div
                            key={i}
                            className={cn(
                              'whitespace-pre-wrap break-words',
                              line.startsWith('+') && !line.startsWith('+++')
                                ? 'text-emerald-700 bg-emerald-50'
                                : line.startsWith('-') && !line.startsWith('---')
                                  ? 'text-red-700 bg-red-50'
                                  : 'text-gray-600'
                            )}
                          >
                            {line}
                          </div>
                        ))}
                    </pre>
                  )}

                  <div className="flex justify-end">
                    <ConfirmationModal
                      confirmationMessage={t('ext.tools.assign.ver.confirm_msg', {
                        defaultValue:
                          '会把这一页的正文换成 v{{n}} 的内容。当前这一稿会先被存成一个新版本，所以还能再回滚回来。',
                        n: selected,
                      })}
                      confirmationButtonText={t('ext.tools.assign.ver.restore', {
                        defaultValue: '回滚到这一版',
                      })}
                      pendingButtonText={t('ext.tools.assign.ver.restoring', {
                        defaultValue: '正在回滚…',
                      })}
                      dialogTitle={t('ext.tools.assign.ver.confirm_title', {
                        defaultValue: '确认回滚这一页？',
                      })}
                      functionToExecute={handleRestore}
                      status="warning"
                      dialogTrigger={
                        <PrimaryButton data-testid="assign-ver-restore">
                          <RotateCcw className="w-4 h-4" />
                          {t('ext.tools.assign.ver.restore', { defaultValue: '回滚到这一版' })}
                        </PrimaryButton>
                      }
                    />
                  </div>
                </div>
              )}
            </Card>
          ) : null}
        </>
      )}
    </div>
  )
}
