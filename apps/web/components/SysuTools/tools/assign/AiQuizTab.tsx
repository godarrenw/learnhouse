'use client'
/**
 * AI 出题：选内容页 → 设题量题型 → 生成 → 可编辑预览 → 校验 → 选章节一键布置。
 *
 * 生成出来的 spec 永远是草稿（后端强制 `publish=false`），布置时由「同时发布」
 * 这个开关单独决定要不要立刻对学生可见。
 */
import React, { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, FileQuestion, Sparkles, Wand2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'

import { useLHSession } from '@components/Contexts/LHSessionContext'
import {
  createFromSpec,
  draftFromActivity,
  getLlmModels,
  validateSpec,
} from '@services/ext/assign'
import { asArray } from '@services/utils/ts/requests'

import { assignKeys } from './keys'
import SpecPreview from './SpecPreview'
import {
  Card,
  EmptyState,
  Field,
  GhostButton,
  Input,
  NeedCourse,
  PrimaryButton,
  Select,
  Skeleton,
  WarningList,
} from './ui'
import { useCourseTree } from './useCourseTree'

const KINDS = ['quiz', 'short_answer', 'number_answer', 'form'] as const

export default function AiQuizTab({ courseUuid }: { courseUuid?: string }) {
  const { t } = useTranslation()
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token

  const { chapters, pages, isFetching: treeLoading, data: treeData } = useCourseTree(courseUuid)

  const [activityUuid, setActivityUuid] = useState('')
  const [n, setN] = useState(5)
  const [kinds, setKinds] = useState<string[]>(['quiz', 'short_answer'])
  const [model, setModel] = useState('')
  const [chapterId, setChapterId] = useState('')
  const [publish, setPublish] = useState(false)

  const [spec, setSpec] = useState<any>(null)
  const [preview, setPreview] = useState<any>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [drafting, setDrafting] = useState(false)
  const [busy, setBusy] = useState(false)

  const modelsQuery = useQuery({
    queryKey: assignKeys.models(),
    queryFn: () => getLlmModels(access_token),
    enabled: !!access_token,
    staleTime: 5 * 60_000,
    retry: false,
  })
  const models: string[] = useMemo(
    () => asArray<string>((modelsQuery.data as any)?.models),
    [modelsQuery.data]
  )
  const llmUnavailable = modelsQuery.isError

  function toggleKind(kind: string) {
    setKinds((prev) =>
      prev.includes(kind) ? prev.filter((k) => k !== kind) : [...prev, kind]
    )
  }

  async function handleDraft() {
    if (!courseUuid || !activityUuid) return
    setDrafting(true)
    const toastId = toast.loading(
      t('ext.tools.assign.ai.drafting', { defaultValue: '大模型正在出题，可能要十几秒…' })
    )
    const res = await draftFromActivity(
      courseUuid,
      activityUuid,
      { n, types: kinds, model: model || undefined },
      access_token
    )
    setDrafting(false)
    if (!res.success) {
      toast.error(
        res.data?.detail || t('ext.tools.assign.ai.draft_error', { defaultValue: '出题失败' }),
        { id: toastId }
      )
      return
    }
    setSpec(res.data.spec)
    setPreview(res.data.validation)
    setWarnings(res.data.validation?.warnings ?? [])
    toast.success(
      t('ext.tools.assign.ai.draft_ok', {
        defaultValue: '已生成 {{count}} 道题，请核对后再布置',
        count: res.data.validation?.task_count ?? 0,
      }),
      { id: toastId }
    )
  }

  async function handleValidate() {
    if (!spec) return
    setBusy(true)
    const res = await validateSpec(spec, access_token)
    setBusy(false)
    if (!res.success) {
      setPreview(null)
      toast.error(res.data?.detail || t('ext.common.error', { defaultValue: '加载失败' }))
      return
    }
    setPreview(res.data)
    setWarnings(res.data.warnings ?? [])
    toast.success(t('ext.tools.assign.ai.valid', { defaultValue: '校验通过' }))
  }

  async function handleCreate() {
    if (!courseUuid || !spec || !chapterId) return
    setBusy(true)
    const toastId = toast.loading(
      t('ext.tools.assign.ai.creating', { defaultValue: '正在布置…' })
    )
    const res = await createFromSpec(courseUuid, Number(chapterId), spec, publish, access_token)
    setBusy(false)
    if (!res.success) {
      toast.error(
        res.data?.detail || t('ext.tools.assign.ai.create_error', { defaultValue: '布置失败' }),
        { id: toastId }
      )
      return
    }
    toast.success(
      t('ext.tools.assign.ai.created', {
        defaultValue: '已布置《{{title}}》，共 {{count}} 道题',
        title: res.data.title,
        count: res.data.task_count,
      }),
      { id: toastId }
    )
  }

  if (!courseUuid) return <NeedCourse />

  const treeInitialLoading = !treeData && treeLoading

  return (
    <div className="space-y-6" data-testid="assign-tab-ai">
      <Card
        title={t('ext.tools.assign.ai.setup', { defaultValue: '出题设置' })}
        description={t('ext.tools.assign.ai.setup_desc', {
          defaultValue: '大模型只能读到这一页的正文，出的题也只会考正文讲过的内容。',
        })}
      >
        {treeInitialLoading ? (
          <Skeleton rows={3} />
        ) : pages.length === 0 ? (
          <EmptyState
            icon={FileQuestion}
            message={t('ext.tools.assign.ai.no_pages', {
              defaultValue: '这门课里没有富文本内容页，无法自动出题',
            })}
          />
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Field label={t('ext.tools.assign.ai.page', { defaultValue: '内容页' })}>
                <Select
                  data-testid="assign-ai-page"
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
              <Field
                label={t('ext.tools.assign.ai.count', { defaultValue: '题量' })}
                hint={t('ext.tools.assign.ai.count_hint', { defaultValue: '1 到 20 道' })}
              >
                <Input
                  data-testid="assign-ai-count"
                  type="number"
                  min={1}
                  max={20}
                  value={n}
                  onChange={(e) => setN(Number(e.target.value))}
                />
              </Field>
            </div>

            <Field label={t('ext.tools.assign.ai.kinds', { defaultValue: '题型' })}>
              <div className="flex flex-wrap gap-2 pt-1">
                {KINDS.map((kind) => {
                  const on = kinds.includes(kind)
                  return (
                    <button
                      key={kind}
                      type="button"
                      onClick={() => toggleKind(kind)}
                      data-testid={`assign-ai-kind-${kind}`}
                      className={
                        on
                          ? 'rounded-lg px-3 py-1.5 text-xs font-medium bg-gray-900 text-white cursor-pointer'
                          : 'rounded-lg px-3 py-1.5 text-xs font-medium bg-white nice-shadow text-gray-600 hover:bg-gray-50 cursor-pointer'
                      }
                    >
                      {t(`ext.tools.assign.kind.${kind}`)}
                    </button>
                  )
                })}
              </div>
            </Field>

            <Field
              label={t('ext.tools.assign.ai.model', { defaultValue: '模型' })}
              hint={
                llmUnavailable
                  ? t('ext.tools.assign.ai.llm_down', {
                      defaultValue: '后端还没有配置大模型端点，AI 出题不可用',
                    })
                  : t('ext.tools.assign.ai.model_hint', {
                      defaultValue: '留空就用后端配置的默认模型',
                    })
              }
            >
              <Select
                data-testid="assign-ai-model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                disabled={llmUnavailable}
              >
                <option value="">
                  {t('ext.tools.assign.ai.default_model', { defaultValue: '默认模型' })}
                </option>
                {models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </Select>
            </Field>

            <div className="flex justify-end pt-1">
              <PrimaryButton
                data-testid="assign-ai-draft"
                onClick={handleDraft}
                disabled={!activityUuid || kinds.length === 0 || drafting || llmUnavailable}
              >
                <Sparkles className="w-4 h-4" />
                {drafting
                  ? t('ext.tools.assign.ai.drafting_short', { defaultValue: '正在出题…' })
                  : t('ext.tools.assign.ai.draft', { defaultValue: '生成题目' })}
              </PrimaryButton>
            </div>
          </div>
        )}
      </Card>

      {spec ? (
        <>
          <WarningList items={warnings} />
          <SpecPreview
            spec={spec}
            preview={preview}
            onChange={(next) => {
              setSpec(next)
              setPreview(null)
            }}
          />
          <Card title={t('ext.tools.assign.ai.deploy', { defaultValue: '布置到课程' })}>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Field label={t('ext.tools.assign.chapter', { defaultValue: '章节' })}>
                <Select
                  data-testid="assign-ai-chapter"
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
              <Field
                label={t('ext.tools.assign.publish', { defaultValue: '发布' })}
                hint={t('ext.tools.assign.publish_hint', {
                  defaultValue: '不勾就先存成草稿，学生看不到',
                })}
              >
                <label className="flex items-center gap-2 pt-2 cursor-pointer">
                  <input
                    type="checkbox"
                    data-testid="assign-ai-publish"
                    checked={publish}
                    onChange={(e) => setPublish(e.target.checked)}
                    className="cursor-pointer"
                  />
                  <span className="text-sm text-gray-700">
                    {t('ext.tools.assign.publish_now', { defaultValue: '布置后立刻对学生可见' })}
                  </span>
                </label>
              </Field>
            </div>
            <div className="flex flex-wrap justify-end gap-2 pt-5">
              <GhostButton
                data-testid="assign-ai-validate"
                onClick={handleValidate}
                disabled={busy}
              >
                <CheckCircle2 className="w-4 h-4" />
                {t('ext.tools.assign.validate', { defaultValue: '校验' })}
              </GhostButton>
              <PrimaryButton
                data-testid="assign-ai-create"
                onClick={handleCreate}
                disabled={busy || !chapterId}
              >
                <Wand2 className="w-4 h-4" />
                {t('ext.tools.assign.ai.create', { defaultValue: '一键布置' })}
              </PrimaryButton>
            </div>
          </Card>
        </>
      ) : null}
    </div>
  )
}
