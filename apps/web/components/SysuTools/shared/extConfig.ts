/**
 * 教学工具（ext）的前端配置读取。
 *
 * 读的是组织配置 JSON blob 里的 `ext` 段，也就是 `org.config.config.ext[key]`，
 * 与后端 `src/services/ext/config.py` 读的是同一份数据。
 *
 * 前端拿不到环境变量（后端那层的第二级回退），所以这里只有两级：
 * 组织配置 → 传进来的 fallback。**凡是前端也要用的配置，都应该写进组织配置的
 * ext 段**，别只设环境变量。
 *
 * 用法：
 *
 * ```ts
 * const org = useOrg() as any
 * const avatarUrl = getExtConfig(org, 'avatar_page_url', '')
 * ```
 */

/** 组织配置 JSON 里属于部署方的那一段。 */
export const EXT_CONFIG_SECTION = 'ext'

export function getExtConfigSection(org: any): Record<string, any> {
  const section = org?.config?.config?.[EXT_CONFIG_SECTION]
  return section && typeof section === 'object' ? section : {}
}

/**
 * 取一个 ext 配置项。空字符串算「没配」，回退到 fallback；
 * `false` 和 `0` 是有效取值，会原样返回。
 */
export function getExtConfig<T = any>(org: any, key: string, fallback: T): T {
  const value = getExtConfigSection(org)[key]
  if (value === undefined || value === null || value === '') return fallback
  return value as T
}
