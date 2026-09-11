/* --- SYSU-SAM --- */
'use client'

import { useEffect, useState } from 'react'
import { getConfig } from '@services/config/config'

/**
 * 校园网可达性探测。
 *
 * 背景：学堂经 Cloudflare Tunnel 对校外开放后，视频 / PDF 这类重媒体被 nginx 302
 * 到只在校园网可解析的内部域名（deploy/extra/nginx.prod.conf）。校外用户的浏览器
 * 连不上那个域名，表现是 <video> 长时间转圈、跨域 iframe 一片空白 —— 而且跨域 iframe
 * 加载失败根本不触发任何事件，等不到错误回调。所以只能主动探一次。
 *
 * 做法：对 <媒体域名>/api/v1/health 发一次 no-cors 请求，2.5 秒超时。
 * no-cors 拿不到响应内容，但「有没有发生网络错误」足够区分校内校外。
 *
 * 关键：**没有配 NEXT_PUBLIC_LEARNHOUSE_HEAVY_MEDIA_URL 时，直接返回 reachable，
 * 一次网络请求都不发。** 这样在没做媒体分流的环境里（上游默认、本地开发、
 * 隧道方案的阶段一），行为与改造前完全一致，这个 hook 相当于不存在。
 *
 * 不要把它和上游的 NEXT_PUBLIC_LEARNHOUSE_MEDIA_URL 搞混：后者是「所有 /content/
 * 一刀切」的开关，设了以后课程封面、头像、机构 logo 会一起搬走，校外满页裂图。
 */
export type CampusNetworkStatus = 'checking' | 'reachable' | 'unreachable'

const PROBE_TIMEOUT_MS = 2500
const CACHE_KEY = 'sysu-sam:campus-media-reachable'

/** 同一次会话里只探一次，多个视频/PDF 组件共用这一个结果。 */
let inflight: Promise<CampusNetworkStatus> | null = null

function getHeavyMediaBase(): string | null {
  const raw = getConfig('NEXT_PUBLIC_LEARNHOUSE_HEAVY_MEDIA_URL')
  if (!raw || !String(raw).trim()) return null
  const trimmed = String(raw).trim()
  return trimmed.endsWith('/') ? trimmed.slice(0, -1) : trimmed
}

function readCache(): CampusNetworkStatus | null {
  try {
    const v = sessionStorage.getItem(CACHE_KEY)
    if (v === '1') return 'reachable'
    if (v === '0') return 'unreachable'
  } catch {
    // 无痕模式 / 禁用存储时 sessionStorage 会抛，忽略即可，大不了每次重探
  }
  return null
}

function writeCache(status: CampusNetworkStatus) {
  try {
    sessionStorage.setItem(CACHE_KEY, status === 'reachable' ? '1' : '0')
  } catch {
    // 同上
  }
}

async function probe(base: string): Promise<CampusNetworkStatus> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS)
  try {
    // GET 而不是 HEAD：后端 /api/v1/health 只注册了 GET，HEAD 会拿到 405。
    // no-cors 下 405 其实也算「连得上」，但少一个疑点更好排查。
    await fetch(`${base}/api/v1/health`, {
      method: 'GET',
      mode: 'no-cors',
      cache: 'no-store',
      credentials: 'omit',
      signal: controller.signal,
    })
    return 'reachable'
  } catch {
    // 超时、DNS 解析不到、连接被拒，都归为「不在校园网」
    return 'unreachable'
  } finally {
    clearTimeout(timer)
  }
}

export function useCampusNetwork(): CampusNetworkStatus {
  const base = getHeavyMediaBase()
  // 初始值刻意**不读** sessionStorage：服务端没有这个 API，只会拿到 'checking'，
  // 而客户端首帧若读出 'unreachable' 就和服务端 HTML 对不上，触发 hydration 不一致。
  // 所以缓存放到 effect 里读（effect 只在客户端跑），代价是多一次渲染。
  const [status, setStatus] = useState<CampusNetworkStatus>(
    base ? 'checking' : 'reachable'
  )

  useEffect(() => {
    if (!base) return

    const cached = readCache()
    if (cached) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 见上，为避免 hydration 不一致，缓存只能在客户端 effect 里读
      setStatus(cached)
      return
    }

    let cancelled = false
    if (!inflight) {
      inflight = probe(base).then((result) => {
        writeCache(result)
        inflight = null
        return result
      })
    }
    inflight.then((result) => {
      if (!cancelled) setStatus(result)
    })

    return () => {
      cancelled = true
    }
  }, [base])

  return status
}

/** 测试用：清掉会话缓存与进行中的探测。 */
export function resetCampusNetworkProbe() {
  inflight = null
  try {
    sessionStorage.removeItem(CACHE_KEY)
  } catch {
    // ignore
  }
}
/* --- SYSU-SAM END --- */
