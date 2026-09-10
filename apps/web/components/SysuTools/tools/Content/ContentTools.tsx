'use client'
/**
 * 内容工具：Markdown 导入导出、虚拟助教，外加一页说明。
 *
 * 课程由路由页的 `CourseSelect` 选（注册表里写了 `courseScoped: true`），
 * 通过 `courseUuid` prop 传进来；没选课时不发任何请求。
 *
 * 工具内部的四个分段用的是本地 state，不走路由 —— 外层 Tab 条已经被
 * 「工具之间切换」占用了，再嵌一层路由段会让面包屑和命令面板都变复杂。
 */
import React from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BookOpen,
  Bot,
  Download,
  FileArchive,
  Info,
  Link2,
  QrCode,
  Upload,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'

import { useLHSession } from '@components/Contexts/LHSessionContext'
import { useOrg } from '@components/Contexts/OrgContext'
import LearnHouseSpinner from '@components/Objects/Loaders/LearnHouseSpinner'
import { getCourseMetadata } from '@services/courses/courses'
import {
  AvatarAppendResult,
  ImportSummary,
  appendAvatarToPage,
  downloadBlob,
  exportCourseMarkdown,
  getAvatarConfig,
  importCourseMarkdown,
} from '@services/ext/content'
import { getExtConfig } from '@components/SysuTools/shared'
import { queryKeys } from '@/lib/query/keys'
import { cn } from '@/lib/utils'

import type { SysuToolProps } from '../../types'

type TabKey = 'import' | 'export' | 'avatar' | 'about'

const MAX_ZIP_MB = 50

/** 课程 uuid 在库里带 `course_` 前缀，但取课程结构的那个接口自己会补，得先剥掉。 */
function bareCourseUuid(uuid: string) {
  return uuid.replace(/^course_/, '')
}

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('bg-white nice-shadow rounded-xl p-5 sm:p-6', className)}>{children}</div>
  )
}

function SectionTitle({ icon: Icon, title, hint }: any) {
  return (
    <div className="flex items-start gap-3 pb-4">
      <div className="bg-gray-100 p-2 rounded-lg shrink-0">
        <Icon className="w-4 h-4 text-gray-500" />
      </div>
      <div className="min-w-0">
        <div className="font-semibold text-gray-800 text-sm">{title}</div>
        {hint ? <div className="text-gray-400 text-xs mt-0.5">{hint}</div> : null}
      </div>
    </div>
  )
}

function NoCourse() {
  const { t } = useTranslation()
  return (
    <Card className="py-16 text-center">
      <div className="flex flex-col items-center gap-3">
        <div className="bg-gray-100 p-4 rounded-full">
          <BookOpen className="w-8 h-8 text-gray-400" />
        </div>
        <p className="text-gray-400 text-sm font-medium">
          {t('ext.common.course_required', { defaultValue: '请先选择一个课程' })}
        </p>
      </div>
    </Card>
  )
}

// ------------------------------------------------------------ 导入

function ImportPanel({ courseUuid }: { courseUuid?: string }) {
  const { t } = useTranslation()
  const org = useOrg() as any
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token
  const orgId: number | undefined = org?.id

  const [file, setFile] = React.useState<File | null>(null)
  const [dragging, setDragging] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  const [result, setResult] = React.useState<ImportSummary | null>(null)
  const inputRef = React.useRef<HTMLInputElement>(null)

  function pick(candidate: File | undefined) {
    if (!candidate) return
    if (!candidate.name.toLowerCase().endsWith('.zip')) {
      toast.error(t('ext.tools.content.import.not_zip', { defaultValue: '只接受 .zip 压缩包' }))
      return
    }
    if (candidate.size > MAX_ZIP_MB * 1024 * 1024) {
      toast.error(
        t('ext.tools.content.import.too_large', {
          defaultValue: '压缩包超过 {{mb}} MB',
          mb: MAX_ZIP_MB,
        })
      )
      return
    }
    setFile(candidate)
    setResult(null)
  }

  async function handleImport() {
    if (!file || !courseUuid || !orgId) return
    setBusy(true)
    const toastId = toast.loading(
      t('ext.tools.content.import.running', { defaultValue: '正在导入，大课可能要等一会儿…' })
    )
    try {
      const res = await importCourseMarkdown(courseUuid, orgId, file, access_token)
      if (res.success) {
        const summary = res.data as ImportSummary
        setResult(summary)
        toast.success(
          t('ext.tools.content.import.done', {
            defaultValue: '导入完成：{{chapters}} 个章节，{{activities}} 个页面',
            chapters: summary.counts.chapters,
            activities: summary.counts.activities,
          }),
          { id: toastId }
        )
      } else {
        toast.error(
          (res.data as any)?.detail ||
            t('ext.tools.content.import.failed', { defaultValue: '导入失败' }),
          { id: toastId }
        )
      }
    } catch {
      toast.error(t('ext.tools.content.import.failed', { defaultValue: '导入失败' }), {
        id: toastId,
      })
    } finally {
      setBusy(false)
    }
  }

  if (!courseUuid) return <NoCourse />

  const warnings = (result?.activities_created ?? []).flatMap((a) =>
    a.warnings.map((w) => ({ name: a.name, text: w }))
  )

  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle
          icon={Upload}
          title={t('ext.tools.content.import.title', { defaultValue: '导入 Markdown' })}
          hint={t('ext.tools.content.import.hint', {
            defaultValue:
              '上传「导出 Markdown」生成的 zip。章节和页面一律新建，不会覆盖课程里已有的内容。',
          })}
        />

        <div
          data-testid="sysu-content-dropzone"
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            pick(e.dataTransfer.files?.[0])
          }}
          onClick={() => inputRef.current?.click()}
          className={cn(
            'rounded-xl border-2 border-dashed p-8 text-center cursor-pointer transition-colors',
            dragging ? 'border-indigo-400 bg-indigo-50/40' : 'border-gray-200 hover:bg-gray-50'
          )}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".zip,application/zip"
            className="hidden"
            data-testid="sysu-content-file-input"
            onChange={(e) => pick(e.target.files?.[0])}
          />
          <div className="flex flex-col items-center gap-2">
            <FileArchive className="w-8 h-8 text-gray-400" />
            <div className="text-sm font-medium text-gray-700">
              {file
                ? file.name
                : t('ext.tools.content.import.drop', {
                    defaultValue: '把 zip 拖到这里，或者点一下选文件',
                  })}
            </div>
            <div className="text-xs text-gray-400">
              {file
                ? `${(file.size / 1024 / 1024).toFixed(1)} MB`
                : t('ext.tools.content.import.limit', {
                    defaultValue: '最大 {{mb}} MB',
                    mb: MAX_ZIP_MB,
                  })}
            </div>
          </div>
        </div>

        <div className="flex justify-end pt-4">
          <button
            type="button"
            onClick={handleImport}
            disabled={!file || busy}
            data-testid="sysu-content-import-run"
            className="flex items-center gap-1.5 h-9 px-4 bg-gray-900 text-white hover:bg-gray-800 disabled:opacity-40 rounded-md text-sm font-semibold transition-all cursor-pointer"
          >
            {busy ? <LearnHouseSpinner size={16} /> : <Upload className="w-4 h-4" />}
            <span>{t('ext.tools.content.import.run', { defaultValue: '开始导入' })}</span>
          </button>
        </div>
      </Card>

      {result ? (
        <Card>
          <div data-testid="sysu-content-import-result" className="space-y-4">
            <div className="flex flex-wrap gap-6">
              {[
                ['chapters', result.counts.chapters, t('ext.tools.content.import.chapters', { defaultValue: '新建章节' })],
                ['activities', result.counts.activities, t('ext.tools.content.import.activities', { defaultValue: '新建页面' })],
                ['skipped', result.counts.skipped, t('ext.tools.content.import.skipped', { defaultValue: '跳过' })],
              ].map(([key, value, label]: any) => (
                <div key={key}>
                  <div className="text-2xl font-bold tracking-tighter text-gray-800">{value}</div>
                  <div className="text-xs text-gray-400 font-medium">{label}</div>
                </div>
              ))}
            </div>

            {result.skipped.length > 0 ? (
              <div>
                <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider pb-2">
                  {t('ext.tools.content.import.skipped_title', { defaultValue: '没有还原的内容' })}
                </div>
                <ul className="space-y-1">
                  {result.skipped.map((s, i) => (
                    <li key={i} className="text-sm text-gray-600">
                      <span className="font-medium text-gray-800">{s.name || s.file}</span>
                      <span className="text-gray-400"> · {s.reason}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {warnings.length > 0 ? (
              <div>
                <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider pb-2">
                  {t('ext.tools.content.import.warnings_title', { defaultValue: '需要人工确认' })}
                </div>
                <ul className="space-y-1">
                  {warnings.map((w, i) => (
                    <li key={i} className="text-sm text-gray-600">
                      <span className="font-medium text-gray-800">{w.name}</span>
                      <span className="text-gray-400"> · {w.text}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </Card>
      ) : null}
    </div>
  )
}

// ------------------------------------------------------------ 导出

function ExportPanel({ courseUuid }: { courseUuid?: string }) {
  const { t } = useTranslation()
  const org = useOrg() as any
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token
  const orgId: number | undefined = org?.id

  const [busy, setBusy] = React.useState(false)
  const [stats, setStats] = React.useState<
    { chapters: number; files: number; images: number; notes: number } | null
  >(null)

  async function handleExport() {
    if (!courseUuid || !orgId) return
    setBusy(true)
    const toastId = toast.loading(
      t('ext.tools.content.export.running', { defaultValue: '正在打包…' })
    )
    try {
      const res = await exportCourseMarkdown(courseUuid, orgId, access_token)
      downloadBlob(res.blob, res.filename)
      setStats(res.stats)
      toast.success(
        t('ext.tools.content.export.done', {
          defaultValue: '已下载 {{name}}',
          name: res.filename,
        }),
        { id: toastId }
      )
    } catch (e: any) {
      toast.error(
        e?.message || t('ext.tools.content.export.failed', { defaultValue: '导出失败' }),
        { id: toastId }
      )
    } finally {
      setBusy(false)
    }
  }

  if (!courseUuid) return <NoCourse />

  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle
          icon={Download}
          title={t('ext.tools.content.export.title', { defaultValue: '导出 Markdown' })}
          hint={t('ext.tools.content.export.hint', {
            defaultValue:
              '打包成 zip：README 是课程信息和目录，每章一个目录，页内图片放 assets/。',
          })}
        />
        <div className="bg-amber-50 text-amber-800 text-xs rounded-lg px-3 py-2">
          {t('ext.tools.content.export.lossy', {
            defaultValue:
              '导出是有损的：只有内容页和整页嵌入能再导回来。托管视频、PDF、作业只导出占位说明。',
          })}
        </div>
        <div className="flex justify-end pt-4">
          <button
            type="button"
            onClick={handleExport}
            disabled={busy}
            data-testid="sysu-content-export-run"
            className="flex items-center gap-1.5 h-9 px-4 bg-gray-900 text-white hover:bg-gray-800 disabled:opacity-40 rounded-md text-sm font-semibold transition-all cursor-pointer"
          >
            {busy ? <LearnHouseSpinner size={16} /> : <Download className="w-4 h-4" />}
            <span>{t('ext.tools.content.export.run', { defaultValue: '下载压缩包' })}</span>
          </button>
        </div>
      </Card>

      {stats ? (
        <Card>
          <div className="flex flex-wrap gap-6" data-testid="sysu-content-export-result">
            {[
              ['chapters', stats.chapters, t('ext.tools.content.export.chapters', { defaultValue: '章节' })],
              ['files', stats.files, t('ext.tools.content.export.files', { defaultValue: '文件' })],
              ['images', stats.images, t('ext.tools.content.export.images', { defaultValue: '图片' })],
              ['notes', stats.notes, t('ext.tools.content.export.notes', { defaultValue: '提醒' })],
            ].map(([key, value, label]: any) => (
              <div key={key}>
                <div className="text-2xl font-bold tracking-tighter text-gray-800">{value}</div>
                <div className="text-xs text-gray-400 font-medium">{label}</div>
              </div>
            ))}
          </div>
          {stats.notes > 0 ? (
            <div className="text-xs text-gray-400 pt-3">
              {t('ext.tools.content.export.notes_hint', {
                defaultValue: '压缩包里的 README「导出时的提醒」一节逐条写了是哪些内容没能带走。',
              })}
            </div>
          ) : null}
        </Card>
      ) : null}
    </div>
  )
}

// ------------------------------------------------------------ 虚拟助教

function AvatarPanel({ courseUuid }: { courseUuid?: string }) {
  const { t } = useTranslation()
  const org = useOrg() as any
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token
  const orgId: number | undefined = org?.id

  const [activityUuid, setActivityUuid] = React.useState('')
  const [title, setTitle] = React.useState('')
  const [script, setScript] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [result, setResult] = React.useState<AvatarAppendResult | null>(null)

  // 页面地址：先看组织配置的 ext 段（前端只能读到这一层），读不到再问后端 ——
  // 后端还会往下回退到环境变量和内置默认值，那两层前端看不见。
  const configuredUrl = getExtConfig(org, 'avatar_page_url', '')
  const { data: config } = useQuery({
    queryKey: queryKeys.ext.content.avatarConfig(orgId ?? 0),
    queryFn: () => getAvatarConfig(orgId as number, access_token),
    enabled: !configuredUrl && !!orgId && !!access_token,
    staleTime: 5 * 60_000,
  })
  const avatarPageUrl = configuredUrl || config?.page_url || ''

  const { data: meta, isFetching: metaLoading } = useQuery({
    queryKey: queryKeys.ext.content.courseTree(courseUuid ?? ''),
    queryFn: () =>
      getCourseMetadata(bareCourseUuid(courseUuid as string), null, access_token, {
        withUnpublishedActivities: true,
      }),
    enabled: !!courseUuid && !!access_token,
    staleTime: 60_000,
  })

  /** 只有富文本内容页能追加，视频、PDF、作业都不行，所以这里先滤一遍。 */
  const pages = React.useMemo(() => {
    const chapters = (meta as any)?.chapters ?? []
    const out: { uuid: string; label: string }[] = []
    for (const ch of chapters) {
      for (const act of ch.activities ?? []) {
        if (
          act.activity_type === 'TYPE_DYNAMIC' &&
          act.activity_sub_type === 'SUBTYPE_DYNAMIC_PAGE'
        ) {
          out.push({ uuid: act.activity_uuid, label: `${ch.name} / ${act.name}` })
        }
      }
    }
    return out
  }, [meta])

  // 换课程时清掉上一门课的选择和结果。
  // 用 React 官方的「渲染期间根据 prop 变化调整 state」写法，不用 useEffect ——
  // 在 effect 里 setState 会多跑一轮渲染，React Compiler 的规则也会报警告。
  const [prevCourseUuid, setPrevCourseUuid] = React.useState(courseUuid)
  if (courseUuid !== prevCourseUuid) {
    setPrevCourseUuid(courseUuid)
    setActivityUuid('')
    setResult(null)
  }

  async function handleAppend() {
    if (!activityUuid || !script.trim() || !orgId) return
    setBusy(true)
    const toastId = toast.loading(
      t('ext.tools.content.avatar.running', { defaultValue: '正在生成并追加…' })
    )
    try {
      const res = await appendAvatarToPage(
        activityUuid,
        orgId,
        { script, title: title.trim() || undefined },
        access_token
      )
      if (res.success) {
        setResult(res.data as AvatarAppendResult)
        toast.success(
          t('ext.tools.content.avatar.done', { defaultValue: '已追加到页面末尾' }),
          { id: toastId }
        )
      } else {
        toast.error(
          (res.data as any)?.detail ||
            t('ext.tools.content.avatar.failed', { defaultValue: '追加失败' }),
          { id: toastId }
        )
      }
    } catch {
      toast.error(t('ext.tools.content.avatar.failed', { defaultValue: '追加失败' }), {
        id: toastId,
      })
    } finally {
      setBusy(false)
    }
  }

  if (!courseUuid) return <NoCourse />

  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle
          icon={Bot}
          title={t('ext.tools.content.avatar.title', { defaultValue: '虚拟助教' })}
          hint={t('ext.tools.content.avatar.hint', {
            defaultValue:
              '讲稿会压进链接的 # 后面，由浏览器自己朗读并驱动卡通头像。不占服务器资源，也不需要 API key。',
          })}
        />

        <div className="space-y-4">
          <div className="space-y-1.5">
            <label
              htmlFor="sysu-avatar-page"
              className="text-xs font-semibold text-gray-500 uppercase tracking-wider"
            >
              {t('ext.tools.content.avatar.page', { defaultValue: '追加到哪一页' })}
            </label>
            <select
              id="sysu-avatar-page"
              value={activityUuid}
              onChange={(e) => setActivityUuid(e.target.value)}
              disabled={metaLoading && pages.length === 0}
              data-testid="sysu-content-avatar-page"
              className="w-full bg-white nice-shadow rounded-lg text-sm text-gray-800 px-3 py-2 outline-none cursor-pointer disabled:opacity-50"
            >
              <option value="">
                {pages.length === 0
                  ? metaLoading
                    ? t('ext.common.loading', { defaultValue: '正在加载…' })
                    : t('ext.tools.content.avatar.no_pages', {
                        defaultValue: '这门课还没有富文本内容页',
                      })
                  : t('ext.tools.content.avatar.pick_page', { defaultValue: '请选择…' })}
              </option>
              {pages.map((p) => (
                <option key={p.uuid} value={p.uuid}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="sysu-avatar-title"
              className="text-xs font-semibold text-gray-500 uppercase tracking-wider"
            >
              {t('ext.tools.content.avatar.subtitle_label', { defaultValue: '小标题（可不填）' })}
            </label>
            <input
              id="sysu-avatar-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={200}
              placeholder={t('ext.tools.content.avatar.subtitle_ph', {
                defaultValue: '例如：本节要点回顾',
              })}
              className="w-full bg-white nice-shadow rounded-lg text-sm text-gray-800 px-3 py-2 outline-none"
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="sysu-avatar-script"
              className="text-xs font-semibold text-gray-500 uppercase tracking-wider"
            >
              {t('ext.tools.content.avatar.script', { defaultValue: '讲稿' })}
            </label>
            <textarea
              id="sysu-avatar-script"
              value={script}
              onChange={(e) => setScript(e.target.value)}
              rows={10}
              data-testid="sysu-content-avatar-script"
              placeholder={t('ext.tools.content.avatar.script_ph', {
                defaultValue:
                  '直接写要念的内容，支持 Markdown。空行分段，段末会自动停顿。代码块、图片、表格念不出来，会被跳过。',
              })}
              className="w-full bg-white nice-shadow rounded-lg text-sm text-gray-800 px-3 py-2 outline-none resize-y"
            />
            <div className="text-xs text-gray-400">
              {t('ext.tools.content.avatar.chars', {
                defaultValue: '{{count}} 字',
                count: script.length,
              })}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 pt-4">
          <div className="text-xs text-gray-400 min-w-0 truncate">
            {avatarPageUrl
              ? t('ext.tools.content.avatar.page_url', {
                  defaultValue: '页面地址：{{url}}',
                  url: avatarPageUrl,
                })
              : ''}
          </div>
          <button
            type="button"
            onClick={handleAppend}
            disabled={busy || !activityUuid || !script.trim()}
            data-testid="sysu-content-avatar-run"
            className="flex items-center gap-1.5 h-9 px-4 bg-gray-900 text-white hover:bg-gray-800 disabled:opacity-40 rounded-md text-sm font-semibold transition-all cursor-pointer"
          >
            {busy ? <LearnHouseSpinner size={16} /> : <Bot className="w-4 h-4" />}
            <span>{t('ext.tools.content.avatar.run', { defaultValue: '追加到页面末尾' })}</span>
          </button>
        </div>
      </Card>

      {result ? (
        <Card>
          <div className="space-y-3" data-testid="sysu-content-avatar-result">
            <div className="text-sm text-gray-800 font-semibold">
              {t('ext.tools.content.avatar.result_title', {
                defaultValue: '已追加到「{{name}}」',
                name: result.activity_name,
              })}
            </div>
            <div className="text-xs text-gray-400">
              {t('ext.tools.content.avatar.result_meta', {
                defaultValue: '切成 {{lines}} 句，链接 {{length}} 字符。追加前已自动存了一版，可以在内容页版本回滚里撤回。',
                lines: result.line_count,
                length: result.url_length,
              })}
            </div>
            <a
              href={result.embed_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-xs text-indigo-600 hover:text-indigo-800 font-medium"
            >
              <Link2 className="w-3.5 h-3.5" />
              {t('ext.tools.content.avatar.preview', { defaultValue: '先预览一下再给学生看' })}
            </a>
          </div>
        </Card>
      ) : null}
    </div>
  )
}

// ------------------------------------------------------------ 说明

function AboutPanel() {
  const { t } = useTranslation()
  const items: [any, string, string][] = [
    [
      Link2,
      t('ext.tools.content.about.paste_title', { defaultValue: '编辑器里粘贴视频链接' }),
      t('ext.tools.content.about.paste_body', {
        defaultValue:
          '在内容页编辑器里粘贴一条 bilibili 链接，会自动变成播放器。视频页、带分 P 的地址、手机版、av 号、b23.tv 短链、已经是播放器的地址、官方 iframe 代码整段，七种都认。抖音和腾讯视频会照常插入，但会提示你自己预览一下 —— 它们的播放器我们没能实际验证过。',
      }),
    ],
    [
      QrCode,
      t('ext.tools.content.about.qr_title', { defaultValue: '邀请码二维码' }),
      t('ext.tools.content.about.qr_body', {
        defaultValue:
          '在「用户 → 注册方式」页面，每个邀请码那一行都有一个二维码按钮，可以下载 SVG 去印刷或发到群里。',
      }),
    ],
    [
      FileArchive,
      t('ext.tools.content.about.transfer_title', { defaultValue: '导入导出的边界' }),
      t('ext.tools.content.about.transfer_body', {
        defaultValue:
          '能来回搬的只有内容页和整页嵌入。托管视频和 PDF 的原始文件不在压缩包里，作业请用作业工具的学期复用功能搬。导入一律新建章节，不会覆盖课程里已有的内容。',
      }),
    ],
    [
      Bot,
      t('ext.tools.content.about.avatar_title', { defaultValue: '虚拟助教怎么工作' }),
      t('ext.tools.content.about.avatar_body', {
        defaultValue:
          '讲稿不存在服务器上，而是压缩后塞进链接的 # 后面。页面读到之后用浏览器自带的语音合成念出来，同时驱动头像的口型和字幕。所以链接会很长，这是正常的；也因此这个链接不能手工改，改了讲稿就没了。',
      }),
    ],
  ]

  return (
    <Card>
      <SectionTitle
        icon={Info}
        title={t('ext.tools.content.about.title', { defaultValue: '这些工具怎么用' })}
      />
      <div className="space-y-5">
        {items.map(([Icon, heading, body], i) => (
          <div key={i} className="flex items-start gap-3">
            <Icon className="w-4 h-4 text-gray-400 mt-0.5 shrink-0" />
            <div className="min-w-0">
              <div className="text-sm font-semibold text-gray-800">{heading}</div>
              <p className="text-sm text-gray-600 leading-relaxed mt-1">{body}</p>
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

// ------------------------------------------------------------ 外壳

export default function ContentTools({ courseUuid }: SysuToolProps) {
  const { t } = useTranslation()
  const [tab, setTab] = React.useState<TabKey>('import')

  const tabs: { key: TabKey; label: string; icon: any }[] = [
    {
      key: 'import',
      label: t('ext.tools.content.tabs.import', { defaultValue: '导入 Markdown' }),
      icon: Upload,
    },
    {
      key: 'export',
      label: t('ext.tools.content.tabs.export', { defaultValue: '导出 Markdown' }),
      icon: Download,
    },
    {
      key: 'avatar',
      label: t('ext.tools.content.tabs.avatar', { defaultValue: '虚拟助教' }),
      icon: Bot,
    },
    {
      key: 'about',
      label: t('ext.tools.content.tabs.about', { defaultValue: '说明' }),
      icon: Info,
    },
  ]

  return (
    <div className="px-4 sm:px-10 pb-10">
      <div className="max-w-[1600px] mx-auto space-y-4">
        <div className="flex flex-wrap gap-1.5" role="tablist">
          {tabs.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              data-testid={`sysu-content-tab-${key}`}
              className={cn(
                'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors cursor-pointer',
                tab === key
                  ? 'bg-gray-900 text-white'
                  : 'bg-white nice-shadow text-gray-600 hover:bg-gray-50'
              )}
            >
              <Icon className="w-4 h-4" />
              {label}
            </button>
          ))}
        </div>

        {tab === 'import' ? <ImportPanel courseUuid={courseUuid} /> : null}
        {tab === 'export' ? <ExportPanel courseUuid={courseUuid} /> : null}
        {tab === 'avatar' ? <AvatarPanel courseUuid={courseUuid} /> : null}
        {tab === 'about' ? <AboutPanel /> : null}
      </div>
    </div>
  )
}
