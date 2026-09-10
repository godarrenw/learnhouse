'use client'
/**
 * 查重：选作业 → 拉阈值 → 看相似学生对。
 *
 * 后端返回的 `disclaimer` 必须原样显示 —— 相似度只是线索，不是抄袭的结论。
 */
import React, { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Copy, FileSearch, ShieldCheck } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { useLHSession } from '@components/Contexts/LHSessionContext'
import { useOrg } from '@components/Contexts/OrgContext'
import { getAssignmentsFromACourse } from '@services/courses/assignments'
import { getSimilarity } from '@services/ext/assign'
import { asArray } from '@services/utils/ts/requests'

import { assignKeys } from './keys'
import { Card, EmptyState, Field, NeedCourse, Select, Skeleton } from './ui'

export default function SimilarityTab({ courseUuid }: { courseUuid?: string }) {
  const { t } = useTranslation()
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token
  const org = useOrg() as any
  const orgId: number = org?.id ?? 0

  const [assignmentUuid, setAssignmentUuid] = useState('')
  const [threshold, setThreshold] = useState(0.8)

  const assignmentsQuery = useQuery({
    queryKey: assignKeys.assignments(courseUuid ?? ''),
    queryFn: () => getAssignmentsFromACourse(courseUuid as string, access_token),
    enabled: !!courseUuid && !!access_token,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  })
  const assignments = useMemo(
    () => asArray<any>((assignmentsQuery.data as any)?.data),
    [assignmentsQuery.data]
  )

  const simQuery = useQuery({
    queryKey: assignKeys.similarity(assignmentUuid, threshold),
    queryFn: () => getSimilarity(orgId, assignmentUuid, threshold, access_token),
    enabled: !!orgId && !!assignmentUuid && !!access_token,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  })
  const result = simQuery.data as any
  const isInitialLoading = !result && simQuery.isFetching
  const pairs = asArray<any>(result?.pairs)

  if (!courseUuid) return <NeedCourse />

  return (
    <div className="space-y-6" data-testid="assign-tab-similarity">
      <Card title={t('ext.tools.assign.sim.setup', { defaultValue: '查重设置' })}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label={t('ext.tools.assign.sim.assignment', { defaultValue: '作业' })}>
            <Select
              data-testid="assign-sim-assignment"
              value={assignmentUuid}
              onChange={(e) => setAssignmentUuid(e.target.value)}
            >
              <option value="">
                {t('ext.tools.assign.sim.pick', { defaultValue: '选择要查重的作业' })}
              </option>
              {assignments.map((a: any) => (
                <option key={a.assignment_uuid} value={a.assignment_uuid}>
                  {a.title}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label={t('ext.tools.assign.sim.threshold', {
              defaultValue: '相似度阈值：{{value}}',
              value: threshold.toFixed(2),
            })}
            hint={t('ext.tools.assign.sim.threshold_hint', {
              defaultValue: '越低报得越多，也越容易误报。默认 0.80。',
            })}
          >
            <input
              type="range"
              min={0.5}
              max={1}
              step={0.05}
              value={threshold}
              data-testid="assign-sim-threshold"
              aria-label={t('ext.tools.assign.sim.threshold_aria', {
                defaultValue: '相似度阈值',
              })}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className="w-full cursor-pointer"
            />
          </Field>
        </div>
      </Card>

      {!assignmentUuid ? (
        <Card>
          <EmptyState
            icon={FileSearch}
            message={t('ext.tools.assign.sim.pick_first', {
              defaultValue: '选一份作业开始查重',
            })}
          />
        </Card>
      ) : isInitialLoading ? (
        <Card>
          <Skeleton rows={5} />
        </Card>
      ) : !result ? (
        <Card>
          <EmptyState
            icon={FileSearch}
            message={t('ext.common.error', { defaultValue: '加载失败' })}
          />
        </Card>
      ) : (
        <>
          <div
            className="bg-amber-50 rounded-xl px-4 py-3 flex items-start gap-2.5"
            data-testid="assign-sim-disclaimer"
          >
            <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
            <p className="text-xs text-amber-800 leading-relaxed">{result.disclaimer}</p>
          </div>

          <Card
            testId="assign-sim-pairs"
            title={t('ext.tools.assign.sim.pairs', {
              defaultValue: '相似的学生对（{{count}}）',
              count: pairs.length,
            })}
          >
            {pairs.length === 0 ? (
              <EmptyState
                icon={ShieldCheck}
                message={t('ext.tools.assign.sim.none', {
                  defaultValue: '在当前阈值下没有发现相似度过高的答案',
                })}
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                        {t('ext.tools.assign.sim.students', { defaultValue: '学生对' })}
                      </th>
                      <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                        {t('ext.tools.assign.sim.task', { defaultValue: '题目' })}
                      </th>
                      <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                        {t('ext.tools.assign.sim.score', { defaultValue: '相似度' })}
                      </th>
                      <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                        {t('ext.tools.assign.sim.snippet', { defaultValue: '重合片段' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {pairs.map((p: any, i: number) => (
                      <tr key={i} className="hover:bg-gray-50 transition-colors">
                        <td className="px-6 py-4">
                          <div className="text-sm text-gray-800 font-semibold">
                            {p.user_a} · {p.user_b}
                          </div>
                          {p.same_file ? (
                            <span className="inline-flex items-center gap-1 text-xs text-red-600 font-medium pt-1">
                              <Copy className="w-3 h-3" />
                              {t('ext.tools.assign.sim.same_file', {
                                defaultValue: '文件完全相同',
                              })}
                            </span>
                          ) : null}
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-600 truncate max-w-[220px]">
                          {p.task_title}
                        </td>
                        <td className="px-6 py-4 text-sm font-semibold text-gray-800 tabular-nums">
                          {(p.similarity * 100).toFixed(1)}%
                        </td>
                        <td className="px-6 py-4">
                          <span className="text-xs text-gray-500 line-clamp-2 max-w-[360px] block">
                            {p.snippet}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {asArray<any>(result.notes).length > 0 || asArray<any>(result.skipped).length > 0 ? (
            <Card
              testId="assign-sim-notes"
              title={t('ext.tools.assign.sim.notes', { defaultValue: '哪些没参与比对' })}
            >
              <ul className="space-y-1.5">
                {asArray<string>(result.notes).map((note: string, i: number) => (
                  <li key={`n${i}`} className="text-xs text-gray-500 leading-relaxed">
                    {note}
                  </li>
                ))}
                {asArray<any>(result.skipped).map((s: any, i: number) => (
                  <li key={`s${i}`} className="text-xs text-gray-500 leading-relaxed">
                    {s.user_name} · {s.task_title}：{s.reason}
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </>
      )}
    </div>
  )
}
