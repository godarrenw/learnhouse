export const queryKeys = {
  org: {
    detail: (slug: string) => ['org', slug] as const,
    users: (orgId: number) => ['org', orgId, 'users'] as const,
    usage: (orgId: number) => ['org', orgId, 'usage'] as const,
    admins: (orgId: number) => ['org', orgId, 'admins'] as const,
    inviteCodes: (orgId: number) => ['org', orgId, 'inviteCodes'] as const,
    roles: (orgId: number) => ['org', orgId, 'roles'] as const,
    auditLogs: (orgId: number) => ['org', orgId, 'auditLogs'] as const,
    automations: (orgId: number) => ['org', orgId, 'automations'] as const,
    apiTokens: (orgId: number) => ['org', orgId, 'apiTokens'] as const,
  },
  courses: {
    list: (orgSlug: string) => ['courses', orgSlug] as const,
    detail: (uuid: string) => ['course', uuid] as const,
    meta: (uuid: string) => ['course', uuid, 'meta'] as const,
    contributors: (uuid: string) => ['course', uuid, 'contributors'] as const,
    updates: (uuid: string) => ['course', uuid, 'updates'] as const,
    rights: (uuid: string) => ['course', uuid, 'rights'] as const,
  },
  activity: {
    detail: (uuid: string) => ['activity', uuid] as const,
    editorBootstrap: (uuid: string) => ['activity', uuid, 'editor-bootstrap'] as const,
    versions: (uuid: string) => ['activity', uuid, 'versions'] as const,
    state: (uuid: string) => ['activity', uuid, 'state'] as const,
  },
  trail: {
    org: (orgId: number) => ['trail', 'org', orgId] as const,
  },
  folders: {
    list: (orgId: number) => ['folders', orgId] as const,
    detail: (uuid: string) => ['folder', uuid] as const,
  },
  media: {
    list: (orgId: number) => ['media', orgId] as const,
    detail: (uuid: string) => ['media', uuid] as const,
  },
  community: {
    list: (orgId: number, page?: number) => ['communities', orgId, page] as const,
    detail: (uuid: string) => ['community', uuid] as const,
    rights: (uuid: string) => ['community', uuid, 'rights'] as const,
    discussions: (uuid: string, sort: string, page: number) => ['community', uuid, 'discussions', sort, page] as const,
    byCourse: (courseUuid: string) => ['community', 'byCourse', courseUuid] as const,
  },
  discussion: {
    detail: (uuid: string) => ['discussion', uuid] as const,
    comments: (uuid: string, page: number) => ['discussion', uuid, 'comments', page] as const,
    reactions: (uuid: string) => ['discussion', uuid, 'reactions'] as const,
  },
  assignments: {
    list: (orgSlug: string) => ['assignments', orgSlug] as const,
    detail: (uuid: string) => ['assignment', uuid] as const,
    tasks: (uuid: string) => ['assignment', uuid, 'tasks'] as const,
    submission: (uuid: string) => ['assignment', uuid, 'submission', 'me'] as const,
    taskSubmission: (uuid: string) => ['assignment', uuid, 'task-submission', 'me'] as const,
    analytics: (uuid: string) => ['assignment', uuid, 'analytics'] as const,
    allSubmissions: (uuid: string) => ['assignment', uuid, 'submissions'] as const,
  },
  usergroups: {
    list: (orgId: number) => ['usergroups', orgId] as const,
    resources: (ugId: string, orgId: number) => ['usergroup', ugId, 'resources', orgId] as const,
    members: (ugId: string) => ['usergroup', ugId, 'members'] as const,
  },
  playgrounds: {
    list: (orgSlug: string | number) => ['playgrounds', orgSlug] as const,
    detail: (uuid: string) => ['playground', uuid] as const,
  },
  boards: {
    list: (orgSlug: string | number) => ['boards', orgSlug] as const,
    detail: (uuid: string) => ['board', uuid] as const,
    members: (uuid: string) => ['board', uuid, 'members'] as const,
  },
  podcasts: {
    list: (orgSlug: string) => ['podcasts', orgSlug] as const,
    detail: (uuid: string) => ['podcast', uuid] as const,
    meta: (uuid: string) => ['podcast', uuid, 'meta'] as const,
    episodes: (uuid: string) => ['podcast', uuid, 'episodes'] as const,
  },
  ai: {
    ragSessions: (orgSlug: string) => ['ai', 'rag', 'sessions', orgSlug] as const,
  },
  certifications: {
    detail: (uuid: string) => ['certification', uuid] as const,
    byCourse: (courseUuid: string) => ['certification', 'byCourse', courseUuid] as const,
  },
  analytics: {
    pipe: (orgId: number, pipeName: string, params: string) => ['analytics', orgId, 'pipe', pipeName, params] as const,
    detail: (orgId: number, queryName: string, params: string) => ['analytics', orgId, 'detail', queryName, params] as const,
    db: (orgId: number, queryName: string, params: string) => ['analytics', orgId, 'db', queryName, params] as const,
    planInfo: (orgId: number) => ['analytics', orgId, 'planInfo'] as const,
    status: () => ['analytics', 'status'] as const,
    coursePipe: (orgId: number, courseUuid: string, pipeName: string, params: string) => ['analytics', orgId, 'course', courseUuid, 'pipe', pipeName, params] as const,
    courseDetail: (orgId: number, courseUuid: string, queryName: string, params: string) => ['analytics', orgId, 'course', courseUuid, 'detail', queryName, params] as const,
  },
  audit: {
    user: (orgId: number, userId: number, days: number) => ['audit', orgId, 'user', userId, days] as const,
    summary: (orgId: number, userIds: string, days: number) => ['audit', orgId, 'summary', userIds, days] as const,
  },
  courseUsergroups: {
    resources: (courseUuid: string, orgId: number) => ['courseUsergroups', courseUuid, orgId] as const,
  },
  superadmin: {
    status: () => ['superadmin', 'status'] as const,
    orgs: () => ['superadmin', 'orgs'] as const,
    users: () => ['superadmin', 'users'] as const,
    analytics: () => ['superadmin', 'analytics'] as const,
    apiTokens: () => ['superadmin', 'apiTokens'] as const,
  },
  payments: {
    configs: (orgId: number) => ['payments', orgId, 'configs'] as const,
    offers: (orgId: number) => ['payments', orgId, 'offers'] as const,
    customers: (orgId: number) => ['payments', orgId, 'customers'] as const,
    groups: (orgId: number) => ['payments', orgId, 'groups'] as const,
  },
  /* --- SYSU-SAM: 教学工具（ext）的 query key --- */
  // 每个工具在这里加一个工厂函数，前缀统一是 'ext'，这样一句
  // invalidateQueries({ queryKey: ['ext'] }) 就能刷掉全部教学工具的缓存。
  // 注意 courses 是本层自己的一份（带 include_unpublished），
  // 不要复用 queryKeys.courses.list —— 那个 key 被上游用不同参数占着。
  ext: {
    health: (orgId: number) => ['ext', 'health', orgId] as const,
    courses: (orgSlug: string) => ['ext', 'courses', orgSlug] as const,
    learning: {
      gradebook: (courseUuid: string) => ['ext', 'learning', 'gradebook', courseUuid] as const,
      missing: (courseUuid: string, assignmentUuid: string | null) =>
        ['ext', 'learning', 'missing', courseUuid, assignmentUuid ?? 'all'] as const,
      progress: (courseUuid: string) => ['ext', 'learning', 'progress', courseUuid] as const,
      student: (courseUuid: string, student: string) =>
        ['ext', 'learning', 'progress', courseUuid, student] as const,
      lint: (courseUuid: string) => ['ext', 'learning', 'lint', courseUuid] as const,
      // 组织级，不按课程分；概览页的「最近学习动态」卡片用
      recent: (orgId: number, days: number) =>
        ['ext', 'learning', 'recent', orgId, days] as const,
    },
    content: {
      avatarConfig: (orgId: number) => ['ext', 'content', 'avatarConfig', orgId] as const,
      courseTree: (courseUuid: string) => ['ext', 'content', 'tree', courseUuid] as const,
      qr: (text: string) => ['ext', 'content', 'qr', text] as const,
    },
  },
  /* --- /SYSU-SAM --- */
}
