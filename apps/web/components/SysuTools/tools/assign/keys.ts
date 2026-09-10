/**
 * 作业工具的 react-query key。
 *
 * 放在自己目录里而不是 `lib/query/keys.ts`，是为了不和骨架代理抢同一个文件；
 * 前缀统一是 `['ext', 'assign', …]`，需要整体失效时用 `['ext', 'assign']` 作前缀。
 */
export const assignKeys = {
  all: ['ext', 'assign'] as const,
  courseTree: (courseUuid: string) => ['ext', 'assign', 'tree', courseUuid] as const,
  assignments: (courseUuid: string) => ['ext', 'assign', 'assignments', courseUuid] as const,
  models: (orgId: number) => ['ext', 'assign', 'models', orgId] as const,
  results: (assignmentUuid: string) => ['ext', 'assign', 'results', assignmentUuid] as const,
  similarity: (assignmentUuid: string, threshold: number) =>
    ['ext', 'assign', 'similarity', assignmentUuid, threshold] as const,
  versions: (activityUuid: string) => ['ext', 'assign', 'versions', activityUuid] as const,
  diff: (activityUuid: string, a: number | null, b: number | null) =>
    ['ext', 'assign', 'diff', activityUuid, a, b] as const,
}
