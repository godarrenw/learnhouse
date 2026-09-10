'use client'
/**
 * 课程结构树（章节 + 活动），AI 出题、随堂测、版本回滚三个 Tab 都要用它做选择器。
 *
 * `getCourseMetadata` 自己会补 `course_` 前缀，所以要把 uuid 的前缀去掉再传。
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import { useLHSession } from '@components/Contexts/LHSessionContext'
import { getCourseMetadata } from '@services/courses/courses'
import { asArray } from '@services/utils/ts/requests'

import { assignKeys } from './keys'

export interface TreeActivity {
  id: number
  name: string
  activity_uuid: string
  activity_type: string
}

export interface TreeChapter {
  id: number
  name: string
  activities: TreeActivity[]
}

export function stripCoursePrefix(courseUuid: string) {
  return courseUuid.startsWith('course_') ? courseUuid.slice('course_'.length) : courseUuid
}

export function useCourseTree(courseUuid?: string) {
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token

  const query = useQuery({
    queryKey: assignKeys.courseTree(courseUuid ?? ''),
    queryFn: () =>
      getCourseMetadata(stripCoursePrefix(courseUuid as string), null, access_token, {
        withUnpublishedActivities: true,
      }),
    enabled: !!courseUuid && !!access_token,
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  })

  const chapters: TreeChapter[] = useMemo(
    () => asArray<TreeChapter>((query.data as any)?.chapters),
    [query.data]
  )

  /** 富文本内容页 —— 只有这些能拿来出题和回滚版本。 */
  const pages: (TreeActivity & { chapterName: string })[] = useMemo(
    () =>
      chapters.flatMap((chapter) =>
        (chapter.activities ?? [])
          .filter((a) => a.activity_type === 'TYPE_DYNAMIC')
          .map((a) => ({ ...a, chapterName: chapter.name }))
      ),
    [chapters]
  )

  return { ...query, chapters, pages }
}
