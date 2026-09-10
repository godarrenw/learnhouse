'use client'
/**
 * 随堂测：快速表单建一份小测，加一个结果面板（每题答对率条形 + 学生名单）。
 *
 * 默认是形成性的：不计成绩、交卷即公布答案、允许重做。这正是课堂上「当堂知道
 * 对错」的用法。
 */
import React, { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart3, ListChecks, Plus, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'

import { useLHSession } from '@components/Contexts/LHSessionContext'
import { useOrg } from '@components/Contexts/OrgContext'
import ExportCsvButton, { CsvColumn } from '@components/SysuTools/shared/ExportCsvButton'
import { getAssignmentsFromACourse } from '@services/courses/assignments'
import { createQuickQuiz, getQuizResults } from '@services/ext/assign'
import { asArray } from '@services/utils/ts/requests'

import { assignKeys } from './keys'
import {
  Card,
  EmptyState,
  Field,
  Input,
  NeedCourse,
  PrimaryButton,
  RateBar,
  Select,
  Skeleton,
} from './ui'
import { useCourseTree } from './useCourseTree'

interface DraftOption {
  text: string
  correct: boolean
}

interface DraftQuestion {
  text: string
  options: DraftOption[]
}

function emptyQuestion(): DraftQuestion {
  return {
    text: '',
    options: [
      { text: '', correct: true },
      { text: '', correct: false },
      { text: '', correct: false },
      { text: '', correct: false },
    ],
  }
}

export default function QuickQuizTab({ courseUuid }: { courseUuid?: string }) {
  const { t } = useTranslation()
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token
  const org = useOrg() as any
  const orgId: number = org?.id ?? 0
  const { chapters } = useCourseTree(courseUuid)

  const [title, setTitle] = useState('')
  const [chapterId, setChapterId] = useState('')
  const [formative, setFormative] = useState(true)
  const [publish, setPublish] = useState(true)
  const [questions, setQuestions] = useState<DraftQuestion[]>([emptyQuestion()])
  const [busy, setBusy] = useState(false)
  const [assignmentUuid, setAssignmentUuid] = useState('')

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

  const resultsQuery = useQuery({
    queryKey: assignKeys.results(assignmentUuid),
    queryFn: () => getQuizResults(orgId, assignmentUuid, access_token),
    enabled: !!orgId && !!assignmentUuid && !!access_token,
    staleTime: 15_000,
    placeholderData: (prev) => prev,
  })
  const results = resultsQuery.data as any

  // 导出的是「一个学生一行 + 每题一列」的宽表 —— 教务拿去做统计时最省事的形状。
  // 惰性求值：点了导出才拼，免得每次渲染都过一遍全班。
  const csvColumns: CsvColumn<any>[] = useMemo(() => {
    const questions = asArray<any>(results?.per_question)
    return [
      {
        header: t('ext.tools.assign.quiz.student', { defaultValue: '学生' }),
        value: (row) => row.name,
      },
      { header: t('ext.tools.assign.quiz.email', { defaultValue: '邮箱' }), value: (row) => row.email },
      {
        header: t('ext.tools.assign.quiz.status', { defaultValue: '状态' }),
        value: (row) => row.status,
      },
      {
        header: t('ext.tools.assign.quiz.score', { defaultValue: '得分率' }),
        value: (row) => (row.score_percent === null ? '' : `${row.score_percent}%`),
      },
      ...questions.map((q: any, i: number) => ({
        header: q.question,
        value: (row: any) => {
          const answer = asArray<any>(row.answers)[i]
          if (!answer || answer.correct === null) {
            return t('ext.tools.assign.quiz.csv_blank', { defaultValue: '未答/需人工' })
          }
          return answer.correct
            ? t('ext.tools.assign.quiz.csv_right', { defaultValue: '对' })
            : t('ext.tools.assign.quiz.csv_wrong', { defaultValue: '错' })
        },
      })),
    ]
  }, [results, t])

  function patchQuestion(qi: number, patch: (_q: DraftQuestion) => void) {
    setQuestions((prev) => {
      const next = JSON.parse(JSON.stringify(prev))
      patch(next[qi])
      return next
    })
  }

  async function handleCreate() {
    if (!courseUuid || !chapterId) return
    const clean = questions
      .filter((q) => q.text.trim() && q.options.some((o) => o.text.trim() && o.correct))
      .map((q) => ({
        kind: 'quiz',
        questions: [
          {
            text: q.text.trim(),
            options: q.options
              .filter((o) => o.text.trim())
              .map((o) => ({ text: o.text.trim(), correct: o.correct })),
          },
        ],
      }))
    if (clean.length === 0) {
      toast.error(
        t('ext.tools.assign.quiz.need_question', {
          defaultValue: '至少要有一道写完整的题：题干不能空，且要标出正确答案',
        })
      )
      return
    }
    setBusy(true)
    const toastId = toast.loading(
      t('ext.tools.assign.quiz.creating', { defaultValue: '正在建随堂测…' })
    )
    const res = await createQuickQuiz(
      orgId,
      courseUuid,
      Number(chapterId),
      { title: title.trim(), questions: clean, formative, publish },
      access_token
    )
    setBusy(false)
    if (!res.success) {
      toast.error(
        res.data?.detail || t('ext.tools.assign.quiz.error', { defaultValue: '建随堂测失败' }),
        { id: toastId }
      )
      return
    }
    toast.success(
      t('ext.tools.assign.quiz.created', {
        defaultValue: '已建好《{{title}}》',
        title: res.data.title,
      }),
      { id: toastId }
    )
    setAssignmentUuid(res.data.assignment_uuid)
    assignmentsQuery.refetch()
  }

  if (!courseUuid) return <NeedCourse />

  const resultsInitialLoading = !results && resultsQuery.isFetching

  return (
    <div className="space-y-6" data-testid="assign-tab-quiz">
      <Card
        title={t('ext.tools.assign.quiz.new', { defaultValue: '新建随堂测' })}
        description={t('ext.tools.assign.quiz.new_desc', {
          defaultValue: '形成性随堂测不计入成绩，学生交卷后立刻能看到正确答案，还可以重做。',
        })}
      >
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field label={t('ext.tools.assign.quiz.title', { defaultValue: '标题' })}>
              <Input
                data-testid="assign-quiz-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={t('ext.tools.assign.quiz.title_ph', {
                  defaultValue: '例如：第 3 周随堂测',
                })}
              />
            </Field>
            <Field label={t('ext.tools.assign.chapter', { defaultValue: '章节' })}>
              <Select
                data-testid="assign-quiz-chapter"
                value={chapterId}
                onChange={(e) => setChapterId(e.target.value)}
              >
                <option value="">
                  {t('ext.tools.assign.pick_chapter', { defaultValue: '选择一个章节' })}
                </option>
                {chapters.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <div className="flex flex-wrap gap-6">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                data-testid="assign-quiz-formative"
                checked={formative}
                onChange={(e) => setFormative(e.target.checked)}
                className="cursor-pointer"
              />
              <span className="text-sm text-gray-700">
                {t('ext.tools.assign.quiz.formative', { defaultValue: '形成性（不计入成绩）' })}
              </span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                data-testid="assign-quiz-publish"
                checked={publish}
                onChange={(e) => setPublish(e.target.checked)}
                className="cursor-pointer"
              />
              <span className="text-sm text-gray-700">
                {t('ext.tools.assign.publish_now', { defaultValue: '布置后立刻对学生可见' })}
              </span>
            </label>
          </div>

          <div className="space-y-3">
            {questions.map((q, qi) => (
              <div
                key={qi}
                className="rounded-lg outline outline-1 outline-neutral-200 p-4 space-y-2"
                data-testid={`assign-quiz-q-${qi}`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <Input
                    value={q.text}
                    data-testid={`assign-quiz-qtext-${qi}`}
                    onChange={(e) =>
                      patchQuestion(qi, (question) => {
                        question.text = e.target.value
                      })
                    }
                    placeholder={t('ext.tools.assign.quiz.q_ph', { defaultValue: '题干' })}
                  />
                  {questions.length > 1 ? (
                    <button
                      type="button"
                      aria-label={t('ext.common.delete', { defaultValue: '删除' })}
                      onClick={() =>
                        setQuestions((prev) => prev.filter((_, i) => i !== qi))
                      }
                      className="text-gray-400 hover:text-red-600 transition-colors cursor-pointer shrink-0"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  ) : null}
                </div>
                {q.options.map((o, oi) => (
                  <div key={oi} className="flex items-center gap-2 ps-1 min-w-0">
                    <input
                      type="checkbox"
                      checked={o.correct}
                      data-testid={`assign-quiz-correct-${qi}-${oi}`}
                      aria-label={t('ext.tools.assign.preview.is_correct', {
                        defaultValue: '标为正确答案',
                      })}
                      onChange={(e) =>
                        patchQuestion(qi, (question) => {
                          question.options[oi].correct = e.target.checked
                        })
                      }
                      className="cursor-pointer shrink-0"
                    />
                    <Input
                      value={o.text}
                      data-testid={`assign-quiz-opt-${qi}-${oi}`}
                      onChange={(e) =>
                        patchQuestion(qi, (question) => {
                          question.options[oi].text = e.target.value
                        })
                      }
                      placeholder={t('ext.tools.assign.quiz.opt_ph', {
                        defaultValue: '选项（留空的不会建出来）',
                      })}
                    />
                  </div>
                ))}
              </div>
            ))}
            <button
              type="button"
              onClick={() => setQuestions((prev) => [...prev, emptyQuestion()])}
              data-testid="assign-quiz-add"
              className="flex items-center gap-1.5 text-xs text-indigo-600 hover:text-indigo-800 font-medium cursor-pointer"
            >
              <Plus className="w-3.5 h-3.5" />
              {t('ext.tools.assign.quiz.add', { defaultValue: '再加一道' })}
            </button>
          </div>

          <div className="flex justify-end">
            <PrimaryButton
              data-testid="assign-quiz-create"
              onClick={handleCreate}
              disabled={busy || !chapterId || !title.trim()}
            >
              <ListChecks className="w-4 h-4" />
              {t('ext.tools.assign.quiz.create', { defaultValue: '建随堂测' })}
            </PrimaryButton>
          </div>
        </div>
      </Card>

      <Card
        testId="assign-quiz-results"
        title={t('ext.tools.assign.quiz.results', { defaultValue: '结果' })}
        description={t('ext.tools.assign.quiz.results_desc', {
          defaultValue: '答对率按题目答案现算，文件题和编程题只能人工看，不算进答对率。',
        })}
      >
        <Field label={t('ext.tools.assign.quiz.pick', { defaultValue: '选一份作业' })}>
          <Select
            data-testid="assign-quiz-pick"
            value={assignmentUuid}
            onChange={(e) => setAssignmentUuid(e.target.value)}
          >
            <option value="">
              {t('ext.tools.assign.quiz.pick_ph', { defaultValue: '选择要查看结果的作业' })}
            </option>
            {assignments.map((a: any) => (
              <option key={a.assignment_uuid} value={a.assignment_uuid}>
                {a.title}
              </option>
            ))}
          </Select>
        </Field>

        <div className="pt-4">
          {!assignmentUuid ? (
            <EmptyState
              icon={BarChart3}
              message={t('ext.tools.assign.quiz.pick_first', {
                defaultValue: '选一份作业查看每题答对率',
              })}
            />
          ) : resultsInitialLoading ? (
            <Skeleton rows={5} />
          ) : !results ? (
            <EmptyState
              icon={BarChart3}
              message={t('ext.common.error', { defaultValue: '加载失败' })}
            />
          ) : (
            <div className="space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs text-gray-400">
                  {t('ext.tools.assign.quiz.submitted', {
                    defaultValue: '{{submitted}} / {{roster}} 人已交',
                    submitted: results.submitted_count,
                    roster: results.roster_count,
                  })}
                </p>
                <span data-testid="assign-quiz-export">
                  <ExportCsvButton
                    filename={`${results.title || 'quiz'}-results`}
                    columns={csvColumns}
                    rows={() => asArray<any>(results.students)}
                    disabled={asArray<any>(results.students).length === 0}
                  />
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                        {t('ext.tools.assign.quiz.question', { defaultValue: '题目' })}
                      </th>
                      <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3 w-[220px]">
                        {t('ext.tools.assign.quiz.rate', { defaultValue: '答对率' })}
                      </th>
                      <th className="text-end text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                        {t('ext.tools.assign.quiz.counts', { defaultValue: '对 / 错 / 未答' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {asArray<any>(results.per_question).map((q: any, i: number) => (
                      <tr key={i} className="hover:bg-gray-50 transition-colors">
                        <td className="px-6 py-4">
                          <div className="text-sm text-gray-800 font-medium truncate max-w-[420px]">
                            {q.question}
                          </div>
                          <div className="text-xs text-gray-400">{q.task_title}</div>
                        </td>
                        <td className="px-6 py-4">
                          {q.manual_only ? (
                            <span className="text-xs text-gray-400">
                              {t('ext.tools.assign.quiz.manual', { defaultValue: '需人工批改' })}
                            </span>
                          ) : (
                            <RateBar value={q.correct_rate} />
                          )}
                        </td>
                        <td className="px-6 py-4 text-end text-xs text-gray-600 tabular-nums">
                          {q.right} / {q.wrong} / {q.no_answer}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                        {t('ext.tools.assign.quiz.student', { defaultValue: '学生' })}
                      </th>
                      <th className="text-start text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                        {t('ext.tools.assign.quiz.status', { defaultValue: '状态' })}
                      </th>
                      <th className="text-end text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">
                        {t('ext.tools.assign.quiz.score', { defaultValue: '得分率' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {asArray<any>(results.students).map((s: any) => (
                      <tr key={s.user_id} className="hover:bg-gray-50 transition-colors">
                        <td className="px-6 py-4">
                          <div className="text-sm text-gray-800 font-semibold">{s.name}</div>
                          <div className="text-xs text-gray-400">{s.email ?? ''}</div>
                        </td>
                        <td className="px-6 py-4 text-xs text-gray-600">{s.status}</td>
                        <td className="px-6 py-4 text-end text-sm font-semibold text-gray-800 tabular-nums">
                          {s.score_percent === null ? (
                            <span className="text-xs text-gray-400">—</span>
                          ) : (
                            `${s.score_percent}%`
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  )
}
