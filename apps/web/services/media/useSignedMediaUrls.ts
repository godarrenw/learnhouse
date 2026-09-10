/* --- SYSU-SAM --- */
'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { getAPIUrl } from '@services/config/config'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { getHeavyMediaBase, isHeavyMediaPath } from './media'

/**
 * 把主域名上的重媒体地址换成「媒体域名 + 限时签名」的地址。
 *
 * ## 为什么要签名
 *
 * 单租户模式下 `LH_access` 是 host-only cookie，只发给主域名，跟不到媒体子域；
 * 而 `<video src>` / `<iframe src>` 这类载体又发不出 `Authorization` 头。
 * 所以页面先用自己的会话向 `/ext/media/sign` 换一个绑死单条路径的限时签名，
 * 媒体请求带签名去，不需要任何 cookie。
 *
 * 签名只表明「请求是谁发的」；能不能看仍由后端原有的课程权限在服务时决定。
 *
 * ## 没配 HEAVY_MEDIA_URL 时会发生什么
 *
 * 什么都不发生：`ready` 恒为 true，`get()` 原样返回传进来的地址，**一个网络
 * 请求都不发**。上游默认部署、本地开发、隧道方案阶段一都走这条路径，行为与
 * 改造前一字不差。
 *
 * ## 用法
 *
 * ```tsx
 * const { ready, get } = useSignedMediaUrls([src, fallbackSrc])
 * if (!ready) return null          // 或者渲染骨架
 * <video src={get(src)} />
 * ```
 *
 * 传进来的 URL 顺序无所谓，内部按 URL 本身建索引；`undefined` / 空串会被跳过。
 */

export interface SignedMediaUrls {
  /** 签名是否已就绪（未启用媒体域名时恒为 true）。 */
  ready: boolean
  /** 换算后的地址。未启用、非重媒体、或签名缺失时原样返回。 */
  get: (_url: string | undefined | null) => string
  /** 最近一次取签名是否失败。失败时 get() 回落到原地址，让主域名兜底。 */
  error: boolean
}

interface Signature {
  path: string
  sig: string
  exp: number
  uid: number
}

/** 到期前这么久就重新签，避免正在看的视频 seek 时突然 403。 */
const REFRESH_MARGIN_MS = 30 * 60 * 1000

// 解析相对地址时的兜底 origin。getBackendUrl() 理论上总是绝对地址，
// 但服务端渲染时没有 window，别赌。
const FALLBACK_ORIGIN =
  typeof window === 'undefined' ? 'http://localhost' : window.location.href

function toPath(url: string): string | null {
  try {
    const u = new URL(url, FALLBACK_ORIGIN)
    return u.pathname
  } catch {
    return null
  }
}

export function useSignedMediaUrls(urls: (string | undefined | null)[]): SignedMediaUrls {
  const base = getHeavyMediaBase()
  const session = useLHSession() as any
  const accessToken = session?.data?.tokens?.access_token

  // 依赖数组只能放简单表达式（react-hooks/use-memo 规则），所以先算出字符串键。
  const urlsKey = urls.filter(Boolean).join('|')

  // 只保留需要签名的路径，去重并排序，这样同一批 URL 换个顺序不会触发重签。
  const paths = useMemo(() => {
    if (!base) return [] as string[]
    const set = new Set<string>()
    for (const u of urlsKey.split('|')) {
      if (!u) continue
      const p = toPath(u)
      if (p && isHeavyMediaPath(p)) set.add(p)
    }
    return Array.from(set).sort()
  }, [base, urlsKey])

  const key = paths.join('|')
  const needsSigning = !!base && paths.length > 0

  // signedFor 记录「手上这批签名对应的是哪一批路径」。ready 由它推导，
  // 不用单独的 state —— 在 effect 里 setReady 会多一次级联渲染，
  // 也会被 react-hooks/set-state-in-effect 规则挡住。
  const [signatures, setSignatures] = useState<Record<string, Signature>>({})
  const [signedFor, setSignedFor] = useState<string | null>(null)
  const [error, setError] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const ready = !needsSigning || signedFor === key

  useEffect(() => {
    if (!needsSigning) return
    // 还没拿到会话就先别签；token 到位后这个 effect 会再跑一次。
    // 匿名用户换不到签名，但公开课程本来也不需要签名（后端匿名可取）。
    if (!accessToken) return

    let cancelled = false

    const run = async () => {
      const qs = paths.map((p) => `path=${encodeURIComponent(p)}`).join('&')
      try {
        const res = await fetch(`${getAPIUrl()}ext/media/sign?${qs}`, {
          headers: { Authorization: `Bearer ${accessToken}` },
          credentials: 'include',
        })
        if (!res.ok) throw new Error(`sign failed: ${res.status}`)
        const data = await res.json()
        if (cancelled) return

        const map: Record<string, Signature> = {}
        for (const s of data.signatures ?? []) map[s.path] = s
        setSignatures(map)
        setError(false)
        setSignedFor(key)

        // 到期前 30 分钟自动续签，取这批里最早到期的那条为准。
        const exps = (data.signatures ?? []).map((s: Signature) => s.exp)
        const earliest = exps.length ? Math.min(...exps) : NaN
        if (Number.isFinite(earliest)) {
          const delay = earliest * 1000 - Date.now() - REFRESH_MARGIN_MS
          if (timerRef.current) clearTimeout(timerRef.current)
          timerRef.current = setTimeout(run, Math.max(delay, 60_000))
        }
      } catch {
        if (cancelled) return
        // 换签名失败就回落到主域名地址：校内用户照样能看（主域名本来也服务媒体），
        // 校外用户会看到 CampusOnlyNotice 或播放失败。总之不要卡在 loading。
        setError(true)
        setSignedFor(key)
      }
    }

    run()
    return () => {
      cancelled = true
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [needsSigning, key, accessToken, paths])

  const get = useMemo(() => {
    return (url: string | undefined | null): string => {
      if (!url) return ''
      if (!base) return url
      const p = toPath(url)
      if (!p || !isHeavyMediaPath(p)) return url
      const s = signatures[p]
      if (!s) return url
      // 保留原有 query（播放器可能带自己的参数），再补上三个签名参数。
      // p 用的是 pathname，与后端签名时用的 request.url.path 是同一形态，
      // 不要在这里再 encode 一次，否则签的和验的对不上。
      const original = new URL(url, FALLBACK_ORIGIN)
      const params = original.searchParams
      params.set('sig', s.sig)
      params.set('exp', String(s.exp))
      params.set('uid', String(s.uid))
      return `${base}${p}?${params.toString()}`
    }
  }, [base, signatures])

  return { ready, get, error }
}
/* --- SYSU-SAM END --- */
