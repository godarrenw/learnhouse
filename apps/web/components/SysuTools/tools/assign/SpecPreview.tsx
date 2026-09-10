'use client'
/**
 * 生成出来的题目预览，题干、选项、答案都可以直接改。
 *
 * 改的是 spec 原文（`kind` / `questions` / `answers` 这一层，不是后端的
 * contents 结构），所以改完还能再走一次 `/spec/validate`。
 * 每次改动都会把上一次的校验结果清掉 —— 免得老师看着旧的「校验通过」下手布置。
 */
import React from 'react'
import { Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Card, Field, Input, TextArea } from './ui'

interface SpecPreviewProps {
  spec: any
  preview: any
  onChange: (_next: any) => void
}

function clone(spec: any) {
  return JSON.parse(JSON.stringify(spec))
}

export default function SpecPreview({ spec, preview, onChange }: SpecPreviewProps) {
  const { t } = useTranslation()
  const tasks: any[] = spec?.tasks ?? []

  function patchTask(index: number, patch: (_task: any) => void) {
    const next = clone(spec)
    patch(next.tasks[index])
    onChange(next)
  }

  function removeTask(index: number) {
    const next = clone(spec)
    next.tasks.splice(index, 1)
    onChange(next)
  }

  return (
    <Card
      testId="assign-spec-preview"
      title={t('ext.tools.assign.preview.title', { defaultValue: '题目预览' })}
      description={t('ext.tools.assign.preview.desc', {
        defaultValue: 'AI 出的题一定要逐题核对答案；改完记得再点一次校验。',
      })}
    >
      <div className="space-y-4">
        <Field label={t('ext.tools.assign.preview.name', { defaultValue: '作业标题' })}>
          <Input
            data-testid="assign-spec-name"
            value={spec?.name ?? ''}
            onChange={(e) => {
              const next = clone(spec)
              next.name = e.target.value
              onChange(next)
            }}
          />
        </Field>

        {tasks.map((task, ti) => (
          <div
            key={ti}
            className="rounded-lg outline outline-1 outline-neutral-200 p-4 space-y-3"
            data-testid={`assign-spec-task-${ti}`}
          >
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs font-semibold text-blue-600 bg-blue-50 rounded-md px-2 py-1">
                {t(`ext.tools.assign.kind.${task.kind}`, { defaultValue: task.kind })}
              </span>
              <button
                type="button"
                onClick={() => removeTask(ti)}
                aria-label={t('ext.common.delete', { defaultValue: '删除' })}
                data-testid={`assign-spec-remove-${ti}`}
                className="text-gray-400 hover:text-red-600 transition-colors cursor-pointer"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>

            {task.kind === 'quiz'
              ? (task.questions ?? []).map((q: any, qi: number) => (
                  <div key={qi} className="space-y-2">
                    <TextArea
                      rows={2}
                      value={q.text ?? ''}
                      data-testid={`assign-spec-q-${ti}-${qi}`}
                      onChange={(e) =>
                        patchTask(ti, (task_) => {
                          task_.questions[qi].text = e.target.value
                        })
                      }
                    />
                    <div className="space-y-1.5 ps-1">
                      {(q.options ?? []).map((o: any, oi: number) => (
                        <div key={oi} className="flex items-center gap-2 min-w-0">
                          <input
                            type="checkbox"
                            checked={!!o.correct}
                            aria-label={t('ext.tools.assign.preview.is_correct', {
                              defaultValue: '标为正确答案',
                            })}
                            data-testid={`assign-spec-correct-${ti}-${qi}-${oi}`}
                            onChange={(e) =>
                              patchTask(ti, (task_) => {
                                task_.questions[qi].options[oi].correct = e.target.checked
                              })
                            }
                            className="cursor-pointer shrink-0"
                          />
                          <Input
                            value={o.text ?? ''}
                            onChange={(e) =>
                              patchTask(ti, (task_) => {
                                task_.questions[qi].options[oi].text = e.target.value
                              })
                            }
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                ))
              : null}

            {task.kind === 'short_answer' ? (
              <div className="space-y-2">
                <TextArea
                  rows={2}
                  value={task.prompt ?? ''}
                  data-testid={`assign-spec-prompt-${ti}`}
                  onChange={(e) =>
                    patchTask(ti, (task_) => {
                      task_.prompt = e.target.value
                    })
                  }
                />
                <Field
                  label={t('ext.tools.assign.preview.answers', { defaultValue: '可接受的答案' })}
                  hint={t('ext.tools.assign.preview.answers_hint', {
                    defaultValue: '一行一个，学生答到其中任意一条就算对',
                  })}
                >
                  <TextArea
                    rows={3}
                    value={(task.answers ?? []).join('\n')}
                    data-testid={`assign-spec-answers-${ti}`}
                    onChange={(e) =>
                      patchTask(ti, (task_) => {
                        task_.answers = e.target.value.split('\n').filter((x) => x.trim())
                      })
                    }
                  />
                </Field>
              </div>
            ) : null}

            {task.kind === 'number_answer' ? (
              <div className="space-y-2">
                <TextArea
                  rows={2}
                  value={task.prompt ?? ''}
                  onChange={(e) =>
                    patchTask(ti, (task_) => {
                      task_.prompt = e.target.value
                    })
                  }
                />
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <Field label={t('ext.tools.assign.preview.value', { defaultValue: '答案' })}>
                    <Input
                      type="number"
                      value={task.value ?? ''}
                      onChange={(e) =>
                        patchTask(ti, (task_) => {
                          task_.value = Number(e.target.value)
                        })
                      }
                    />
                  </Field>
                  <Field
                    label={t('ext.tools.assign.preview.tolerance', { defaultValue: '允许误差' })}
                  >
                    <Input
                      type="number"
                      value={task.tolerance ?? 0}
                      onChange={(e) =>
                        patchTask(ti, (task_) => {
                          task_.tolerance = Number(e.target.value)
                        })
                      }
                    />
                  </Field>
                  <Field label={t('ext.tools.assign.preview.unit', { defaultValue: '单位' })}>
                    <Input
                      value={task.unit ?? ''}
                      onChange={(e) =>
                        patchTask(ti, (task_) => {
                          task_.unit = e.target.value
                        })
                      }
                    />
                  </Field>
                </div>
              </div>
            ) : null}

            {task.kind === 'form'
              ? (task.questions ?? []).map((q: any, qi: number) => (
                  <div key={qi} className="space-y-2">
                    <TextArea
                      rows={2}
                      value={q.text ?? ''}
                      onChange={(e) =>
                        patchTask(ti, (task_) => {
                          task_.questions[qi].text = e.target.value
                        })
                      }
                    />
                    {(q.blanks ?? []).map((b: any, bi: number) => (
                      <Input
                        key={bi}
                        value={typeof b === 'string' ? b : (b.answer ?? '')}
                        onChange={(e) =>
                          patchTask(ti, (task_) => {
                            const blank = task_.questions[qi].blanks[bi]
                            if (typeof blank === 'string') {
                              task_.questions[qi].blanks[bi] = e.target.value
                            } else {
                              blank.answer = e.target.value
                            }
                          })
                        }
                      />
                    ))}
                  </div>
                ))
              : null}

            {['quiz', 'short_answer', 'number_answer', 'form'].includes(task.kind) ? null : (
              <p className="text-xs text-gray-400">
                {t('ext.tools.assign.preview.not_editable', {
                  defaultValue: '这种题型暂不支持在这里改，需要的话到作业页面里编辑。',
                })}
              </p>
            )}
          </div>
        ))}

        {preview ? (
          <p className="text-xs text-emerald-600 font-medium" data-testid="assign-spec-valid">
            {t('ext.tools.assign.preview.validated', {
              defaultValue: '校验通过：{{count}} 道题，总分 {{total}}',
              count: preview.task_count,
              total: preview.total_max_grade,
            })}
          </p>
        ) : (
          <p className="text-xs text-gray-400" data-testid="assign-spec-dirty">
            {t('ext.tools.assign.preview.dirty', {
              defaultValue: '改过之后还没有校验，布置前建议先点一次校验。',
            })}
          </p>
        )}
      </div>
    </Card>
  )
}
