/* --- SYSU-SAM: 内容工具 · 编辑器粘贴视频链接自动变播放器 --- */
import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import i18next from 'i18next'
import toast from 'react-hot-toast'

import { resolveEmbedUrl } from './api'

/**
 * 老师在编辑器里粘贴一条 bilibili 链接，直接变成播放器。
 *
 * 不这么做的话，老师要走「插入块 → 选嵌入 → 回 bilibili 找官方 iframe 代码 →
 * 从里面抠出 src」四步，而且 b23.tv 短链抠出来是放不出播放器的。
 *
 * 触发条件很窄，避免误伤正常的粘贴：剪贴板里**只有一条**链接（去掉首尾空白后
 * 不含换行），且指向我们认识的视频站点。整段 `<iframe …>` 官方嵌入代码也认。
 * 其余情况一律 `return false`，交回给 TipTap 默认行为。
 *
 * 优先级必须高于 Link 扩展：Link 的 `linkOnPaste` 默认开着，会抢先把链接变成
 * 超链接文本。ProseMirror 按插件顺序问 handlePaste，TipTap 按扩展 priority 从高
 * 到低排插件，所以这里把 priority 抬到 1000（默认 100）。
 */

const VIDEO_HOST_RE =
  /(bilibili\.com|b23\.tv|player\.bilibili\.com|douyin\.com|v\.qq\.com|youtube\.com|youtu\.be|vimeo\.com)/i

const IFRAME_RE = /^<iframe[\s\S]*<\/iframe>$/i

export interface SysuBilibiliPasteOptions {
  getAccessToken: () => string | undefined
  /** 插入的播放器高度，和 Markdown 导入那条路保持一致 */
  embedHeight: number
}

/** 剪贴板内容是不是「单独一条视频链接」或「一整段 iframe 嵌入代码」。 */
export function matchPastedVideo(raw: string): string | null {
  const text = (raw || '').trim()
  if (!text) return null

  if (IFRAME_RE.test(text) && VIDEO_HOST_RE.test(text)) return text

  // 单条链接：不能有换行，不能有空格（bilibili 的分享文案会带一堆说明文字）
  if (/\s/.test(text)) return null
  if (!/^https?:\/\//i.test(text)) return null
  if (!VIDEO_HOST_RE.test(text)) return null
  return text
}

const SysuBilibiliPaste = Extension.create<SysuBilibiliPasteOptions>({
  name: 'sysuBilibiliPaste',

  // 必须高于 Link（默认 100），否则 linkOnPaste 会先把链接吃掉
  priority: 1000,

  addOptions() {
    return {
      getAccessToken: () => undefined,
      embedHeight: 400,
    }
  },

  addProseMirrorPlugins() {
    const { getAccessToken, embedHeight } = this.options
    const editor = this.editor

    const t = (key: string, defaultValue: string) =>
      i18next.t(key, { defaultValue }) as string

    /** 解析失败时的兜底：把原文当普通链接插进去，不让老师白粘一次。 */
    const insertPlainLink = (url: string) => {
      editor
        .chain()
        .focus()
        .insertContent([
          {
            type: 'text',
            text: url,
            marks: [{ type: 'link', attrs: { href: url } }],
          },
        ])
        .run()
    }

    const handleVideoPaste = (source: string) => {
      const accessToken = getAccessToken()
      if (!accessToken) return false

      const toastId = toast.loading(
        t('content.editor.paste.resolving', '正在解析视频链接…')
      )

      resolveEmbedUrl(source, accessToken)
        .then((res) => {
          const data = res.data as any
          if (!res.success || !data?.embed_url) {
            toast.error(
              data?.detail ||
                t('content.editor.paste.failed', '这条链接解析不出播放器，已按普通链接插入'),
              { id: toastId }
            )
            insertPlainLink(source)
            return
          }

          editor
            .chain()
            .focus()
            .insertContent({
              type: 'blockEmbed',
              attrs: {
                embedUrl: data.embed_url,
                embedType: 'url',
                embedHeight,
                embedWidth: '100%',
                alignment: 'center',
              },
            })
            .run()

          if (data.confirmed === false) {
            toast(
              t(
                'content.editor.paste.unconfirmed',
                '已插入播放器，但这个站点没有实测过，请自己预览一下'
              ),
              { id: toastId, icon: '⚠️' }
            )
          } else {
            toast.success(
              t('content.editor.paste.inserted', '已插入视频播放器'),
              { id: toastId }
            )
          }
        })
        .catch(() => {
          toast.error(
            t('content.editor.paste.failed', '这条链接解析不出播放器，已按普通链接插入'),
            { id: toastId }
          )
          insertPlainLink(source)
        })

      return true
    }

    return [
      new Plugin({
        key: new PluginKey('sysuBilibiliPaste'),
        props: {
          handlePaste(_view, event) {
            // 有文件的粘贴交给 PasteFileHandler，别抢
            if (event.clipboardData?.files?.length) return false
            const text = event.clipboardData?.getData('text/plain')
            const source = matchPastedVideo(text || '')
            if (!source) return false
            event.preventDefault()
            return handleVideoPaste(source)
          },
        },
      }),
    ]
  },
})

export default SysuBilibiliPaste
/* --- /SYSU-SAM --- */
