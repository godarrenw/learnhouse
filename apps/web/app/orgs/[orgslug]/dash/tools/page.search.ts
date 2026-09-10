/**
 * 命令面板（Cmd+K）的搜索元数据。
 *
 * 图标用 Phosphor —— 菜单与搜索元数据是 Phosphor 的地盘，页面内部才用 Lucide。
 * 加新工具时在下面追加一条，并在 `locales/ext/*.json` 的 `search.<key>` 下
 * 补 description / keywords。
 */
import { Wrench, Pulse, FileText, GraduationCap } from '@phosphor-icons/react'
import type { SearchMeta } from '@/lib/dashboard-search/types'

export const searchMetas: SearchMeta[] = [
  {
    id: 'dash.tools.overview',
    titleKey: 'ext.overview.title',
    descriptionKey: 'ext.search.overview.description',
    keywordsKey: 'ext.search.overview.keywords',
    icon: Wrench,
    href: '/dash/tools',
    group: 'content',
  },
  {
    id: 'dash.tools.content',
    titleKey: 'ext.tools.content.title',
    descriptionKey: 'ext.search.content.description',
    keywordsKey: 'ext.search.content.keywords',
    icon: FileText,
    href: '/dash/tools/content',
    group: 'content',
  },
  {
    id: 'dash.tools.example',
    titleKey: 'ext.tools.example.title',
    descriptionKey: 'ext.search.example.description',
    keywordsKey: 'ext.search.example.keywords',
    icon: Pulse,
    href: '/dash/tools/example',
    group: 'content',
  },
  {
    id: 'dash.tools.learning',
    titleKey: 'ext.tools.learning.title',
    descriptionKey: 'ext.search.learning.description',
    keywordsKey: 'ext.search.learning.keywords',
    icon: GraduationCap,
    href: '/dash/tools/learning',
    group: 'content',
  },
]
