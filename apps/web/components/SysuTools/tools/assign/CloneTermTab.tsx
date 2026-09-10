'use client'
/**
 * 学期复用：三步向导（新名字 → 顺延规则 → 确认摘要），外加一个单独的批量顺延。
 *
 * 第三步的摘要不是前端算的，是后端 `confirm=false` 真跑一遍算出来的 —— 摘要里
 * 写的就是 `confirm=true` 会做的事，两次调用走同一段代码。
 */
import React, { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { CalendarClock, Copy } from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'

import ConfirmationModal from '@components/Objects/StyledElements/ConfirmationModal/ConfirmationModal'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { cloneTerm, shiftDue } from '@services/ext/assign'
import { asArray } from '@services/utils/ts/requests'

import { assignKeys } from './keys'
import { Card, Field, GhostButton, Input, NeedCourse, PrimaryButton, Select } from './ui'

type Step = 1 | 2 | 3

export default function CloneTermTab({ courseUuid }: { courseUuid?: string }) {
  const { t } = useTranslation()
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token
  const queryClient = useQueryClient()

  const [step, setStep] = useState<Step>(1)
  const [name, setName] = useState('')
  const [mode, setMode] = useState<'shift' | 'fixed' | 'keep'>('shift')
  const [shiftDays, setShiftDays] = useState(182)
  const [dueDate, setDueDate] = useState('')
  const [unpublish, setUnpublish] = useState(true)
  const [summary, setSummary] = useState<any>(null)
  const [busy, setBusy] = useState(false)

  // 批量顺延（和向导独立，改的是当前这门课）
  const [bulkDays, setBulkDays] = useState(7)
  const [onlyFuture, setOnlyFuture] = useState(true)
  const [bulkPreview, setBulkPreview] = useState<any>(null)

  function cloneBody(confirm: boolean) {
    return {
      name: name.trim() || undefined,
      shift_days: mode === 'shift' ? shiftDays : null,
      due_date: mode === 'fixed' ? dueDate : null,
      unpublish,
      confirm,
    }
  }

  async function handlePreview() {
    if (!courseUuid) return
    setBusy(true)
    const res = await cloneTerm(courseUuid, cloneBody(false), access_token)
    setBusy(false)
    if (!res.success) {
      toast.error(res.data?.detail || t('ext.common.error', { defaultValue: '加载失败' }))
      return
    }
    setSummary(res.data)
    setStep(3)
  }

  async function handleClone() {
    if (!courseUuid) return
    const toastId = toast.loading(
      t('ext.tools.assign.clone.cloning', { defaultValue: '正在复制课程，可能要一会儿…' })
    )
    const res = await cloneTerm(courseUuid, cloneBody(true), access_token)
    if (!res.success) {
      toast.error(
        res.data?.detail || t('ext.tools.assign.clone.error', { defaultValue: '复制失败' }),
        { id: toastId }
      )
      return
    }
    queryClient.invalidateQueries({ queryKey: assignKeys.all })
    toast.success(
      t('ext.tools.assign.clone.done', {
        defaultValue: '已复制成《{{name}}》，带过去 {{count}} 份作业',
        name: res.data.new_course_name,
        count: res.data.copied_count,
      }),
      { id: toastId }
    )
    setSummary(res.data)
  }

  async function handleBulkPreview() {
    if (!courseUuid) return
    setBusy(true)
    const res = await shiftDue(
      courseUuid,
      { days: bulkDays, only_future: onlyFuture, confirm: false },
      access_token
    )
    setBusy(false)
    if (!res.success) {
      toast.error(res.data?.detail || t('ext.common.error', { defaultValue: '加载失败' }))
      return
    }
    setBulkPreview(res.data)
  }

  async function handleBulkApply() {
    if (!courseUuid) return
    const toastId = toast.loading(
      t('ext.tools.assign.shift.applying', { defaultValue: '正在顺延…' })
    )
    const res = await shiftDue(
      courseUuid,
      { days: bulkDays, only_future: onlyFuture, confirm: true },
      access_token
    )
    if (!res.success) {
      toast.error(
        res.data?.detail || t('ext.tools.assign.shift.error', { defaultValue: '顺延失败' }),
        { id: toastId }
      )
      return
    }
    queryClient.invalidateQueries({ queryKey: assignKeys.all })
    toast.success(
      t('ext.tools.assign.shift.done', {
        defaultValue: '已顺延 {{count}} 份作业',
        count: res.data.changed_count,
      }),
      { id: toastId }
    )
    setBulkPreview(res.data)
  }

  if (!courseUuid) return <NeedCourse />

  return (
    <div className="space-y-6" data-testid="assign-tab-clone">
      <Card
        title={t('ext.tools.assign.clone.title', { defaultValue: '复制到新学期' })}
        description={t('ext.tools.assign.clone.desc', {
          defaultValue: '复制章节、内容页、文件和作业题目，不会复制学生的提交与成绩。',
        })}
      >
        <ol className="flex flex-wrap gap-4 pb-5" data-testid="assign-clone-steps">
          {[1, 2, 3].map((s) => (
            <li
              key={s}
              className={
                step === s
                  ? 'flex items-center gap-2 text-sm font-semibold text-gray-900'
                  : 'flex items-center gap-2 text-sm text-gray-400'
              }
            >
              <span
                className={
                  step === s
                    ? 'w-6 h-6 rounded-full bg-gray-900 text-white text-xs flex items-center justify-center'
                    : 'w-6 h-6 rounded-full bg-gray-100 text-gray-400 text-xs flex items-center justify-center'
                }
              >
                {s}
              </span>
              {t(`ext.tools.assign.clone.step${s}`)}
            </li>
          ))}
        </ol>

        {step === 1 ? (
          <div className="space-y-4">
            <Field
              label={t('ext.tools.assign.clone.name', { defaultValue: '新课程名' })}
              hint={t('ext.tools.assign.clone.name_hint', {
                defaultValue: '留空就用「原名 (Copy)」',
              })}
            >
              <Input
                data-testid="assign-clone-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t('ext.tools.assign.clone.name_ph', {
                  defaultValue: '例如：2026 春 · 智能制造导论',
                })}
              />
            </Field>
            <div className="flex justify-end">
              <PrimaryButton data-testid="assign-clone-next1" onClick={() => setStep(2)}>
                {t('ext.tools.assign.next', { defaultValue: '下一步' })}
              </PrimaryButton>
            </div>
          </div>
        ) : null}

        {step === 2 ? (
          <div className="space-y-4">
            <Field label={t('ext.tools.assign.clone.rule', { defaultValue: '截止日期怎么办' })}>
              <Select
                data-testid="assign-clone-mode"
                value={mode}
                onChange={(e) => setMode(e.target.value as any)}
              >
                <option value="shift">
                  {t('ext.tools.assign.clone.mode_shift', { defaultValue: '整体顺延若干天' })}
                </option>
                <option value="fixed">
                  {t('ext.tools.assign.clone.mode_fixed', { defaultValue: '统一设成同一天' })}
                </option>
                <option value="keep">
                  {t('ext.tools.assign.clone.mode_keep', { defaultValue: '保持原样' })}
                </option>
              </Select>
            </Field>
            {mode === 'shift' ? (
              <Field
                label={t('ext.tools.assign.clone.days', { defaultValue: '顺延天数' })}
                hint={t('ext.tools.assign.clone.days_hint', {
                  defaultValue: '一个学期大约 182 天',
                })}
              >
                <Input
                  data-testid="assign-clone-days"
                  type="number"
                  value={shiftDays}
                  onChange={(e) => setShiftDays(Number(e.target.value))}
                />
              </Field>
            ) : null}
            {mode === 'fixed' ? (
              <Field label={t('ext.tools.assign.clone.due', { defaultValue: '统一截止日期' })}>
                <Input
                  data-testid="assign-clone-due"
                  type="date"
                  value={dueDate}
                  onChange={(e) => setDueDate(e.target.value)}
                />
              </Field>
            ) : null}
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                data-testid="assign-clone-unpublish"
                checked={unpublish}
                onChange={(e) => setUnpublish(e.target.checked)}
                className="cursor-pointer"
              />
              <span className="text-sm text-gray-700">
                {t('ext.tools.assign.clone.unpublish', {
                  defaultValue: '新课程先不发布，免得学生提前看到',
                })}
              </span>
            </label>
            <div className="flex justify-end gap-2">
              <GhostButton onClick={() => setStep(1)}>
                {t('ext.tools.assign.back', { defaultValue: '上一步' })}
              </GhostButton>
              <PrimaryButton
                data-testid="assign-clone-preview"
                onClick={handlePreview}
                disabled={busy || (mode === 'fixed' && !dueDate)}
              >
                {t('ext.tools.assign.clone.preview', { defaultValue: '看看会发生什么' })}
              </PrimaryButton>
            </div>
          </div>
        ) : null}

        {step === 3 && summary ? (
          <div className="space-y-4" data-testid="assign-clone-summary">
            <div className="rounded-lg bg-gray-50 px-4 py-3 space-y-1.5">
              <p className="text-sm text-gray-800">
                {t('ext.tools.assign.clone.sum_name', {
                  defaultValue: '新课程名：{{name}}',
                  name: summary.new_course_name,
                })}
              </p>
              <p className="text-sm text-gray-800">
                {t('ext.tools.assign.clone.sum_count', {
                  defaultValue: '会带过去 {{count}} 份作业（含题目）',
                  count: summary.assignment_count,
                })}
              </p>
              <p className="text-xs text-gray-500 leading-relaxed">{summary.note}</p>
            </div>

            {asArray<any>(summary.assignments).length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                        {t('ext.tools.assign.clone.assignment', { defaultValue: '作业' })}
                      </th>
                      <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                        {t('ext.tools.assign.clone.old_due', { defaultValue: '原截止' })}
                      </th>
                      <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                        {t('ext.tools.assign.clone.new_due', { defaultValue: '新截止' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {asArray<any>(summary.assignments).map((a: any, i: number) => (
                      <tr key={i} className="hover:bg-gray-50 transition-colors">
                        <td className="px-6 py-4 text-sm text-gray-800 font-medium">
                          {a.title}
                        </td>
                        <td className="px-6 py-4 text-xs text-gray-500">
                          {a.old_due_date ?? '—'}
                        </td>
                        <td className="px-6 py-4 text-xs text-gray-700 font-medium">
                          {a.new_due_date ?? '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}

            {summary.confirmed ? (
              <p className="text-sm text-emerald-600 font-medium" data-testid="assign-clone-done">
                {t('ext.tools.assign.clone.done_inline', {
                  defaultValue: '已复制完成，新课程在课程列表里（未发布）。',
                })}
              </p>
            ) : (
              <div className="flex justify-end gap-2">
                <GhostButton onClick={() => setStep(2)}>
                  {t('ext.tools.assign.back', { defaultValue: '上一步' })}
                </GhostButton>
                <ConfirmationModal
                  confirmationMessage={t('ext.tools.assign.clone.confirm_msg', {
                    defaultValue:
                      '将会在本组织下新建一门课程并复制全部内容与作业题目。这一步不可撤销，多复制出来的课程需要手动删除。',
                  })}
                  confirmationButtonText={t('ext.tools.assign.clone.confirm_btn', {
                    defaultValue: '确认复制',
                  })}
                  pendingButtonText={t('ext.tools.assign.clone.cloning', {
                    defaultValue: '正在复制…',
                  })}
                  dialogTitle={t('ext.tools.assign.clone.confirm_title', {
                    defaultValue: '确认复制这门课？',
                  })}
                  functionToExecute={handleClone}
                  status="warning"
                  dialogTrigger={
                    <PrimaryButton data-testid="assign-clone-confirm">
                      <Copy className="w-4 h-4" />
                      {t('ext.tools.assign.clone.confirm_btn', { defaultValue: '确认复制' })}
                    </PrimaryButton>
                  }
                />
              </div>
            )}
          </div>
        ) : null}
      </Card>

      <Card
        testId="assign-shift-card"
        title={t('ext.tools.assign.shift.title', { defaultValue: '批量顺延当前课程的截止日期' })}
        description={t('ext.tools.assign.shift.desc', {
          defaultValue: '没设过截止日期的作业一律跳过，不会凭空给它补一个。',
        })}
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label={t('ext.tools.assign.shift.days', { defaultValue: '顺延天数' })}>
            <Input
              data-testid="assign-shift-days"
              type="number"
              value={bulkDays}
              onChange={(e) => setBulkDays(Number(e.target.value))}
            />
          </Field>
          <Field label={t('ext.tools.assign.shift.scope', { defaultValue: '范围' })}>
            <label className="flex items-center gap-2 pt-2 cursor-pointer">
              <input
                type="checkbox"
                data-testid="assign-shift-only-future"
                checked={onlyFuture}
                onChange={(e) => setOnlyFuture(e.target.checked)}
                className="cursor-pointer"
              />
              <span className="text-sm text-gray-700">
                {t('ext.tools.assign.shift.only_future', {
                  defaultValue: '只动还没到期的作业',
                })}
              </span>
            </label>
          </Field>
        </div>

        <div className="flex flex-wrap justify-end gap-2 pt-4">
          <GhostButton
            data-testid="assign-shift-preview"
            onClick={handleBulkPreview}
            disabled={busy}
          >
            <CalendarClock className="w-4 h-4" />
            {t('ext.tools.assign.shift.preview', { defaultValue: '先试算' })}
          </GhostButton>
          {bulkPreview && !bulkPreview.confirmed ? (
            <ConfirmationModal
              confirmationMessage={t('ext.tools.assign.shift.confirm_msg', {
                defaultValue: '会改掉这门课里 {{count}} 份作业的截止日期，改完不会自动还原。',
                count: bulkPreview.changed_count,
              })}
              confirmationButtonText={t('ext.tools.assign.shift.confirm_btn', {
                defaultValue: '确认顺延',
              })}
              pendingButtonText={t('ext.tools.assign.shift.applying', {
                defaultValue: '正在顺延…',
              })}
              dialogTitle={t('ext.tools.assign.shift.confirm_title', {
                defaultValue: '确认批量改截止日期？',
              })}
              functionToExecute={handleBulkApply}
              status="warning"
              dialogTrigger={
                <PrimaryButton data-testid="assign-shift-confirm">
                  {t('ext.tools.assign.shift.confirm_btn', { defaultValue: '确认顺延' })}
                </PrimaryButton>
              }
            />
          ) : null}
        </div>

        {bulkPreview ? (
          <div className="pt-4 space-y-1.5" data-testid="assign-shift-preview-result">
            {asArray<any>(bulkPreview.changed).map((c: any, i: number) => (
              <p key={i} className="text-xs text-gray-600">
                {c.title}：{c.old_due_date} → <strong>{c.new_due_date}</strong>
              </p>
            ))}
            {asArray<any>(bulkPreview.skipped).map((s: any, i: number) => (
              <p key={`sk${i}`} className="text-xs text-gray-400">
                {s.title}：{s.reason}
              </p>
            ))}
            {bulkPreview.changed_count === 0 && bulkPreview.skipped_count === 0 ? (
              <p className="text-xs text-gray-400">
                {t('ext.tools.assign.shift.nothing', {
                  defaultValue: '这门课里没有作业可以顺延',
                })}
              </p>
            ) : null}
          </div>
        ) : null}
      </Card>
    </div>
  )
}
