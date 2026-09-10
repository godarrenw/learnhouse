import { useOrg } from '@components/Contexts/OrgContext'
import { getActivityMediaDirectory } from '@services/media/media'
import React from 'react'
/* --- SYSU-SAM --- */
import { useCampusNetwork } from '@services/media/useCampusNetwork'
import CampusOnlyNotice from '@components/Objects/Media/CampusOnlyNotice'
/* --- SYSU-SAM --- */

function DocumentPdfActivity({
  activity,
  course,
  orgUuid,
  className,
}: {
  activity: any
  course: any
  orgUuid?: string
  className?: string
}) {
  const org = useOrg() as any
  const resolvedOrgUuid = orgUuid || org?.org_uuid

  /* --- SYSU-SAM --- */
  // 跨域 iframe 加载失败不触发任何事件，等不到 onError，只能主动探。
  const campusNetwork = useCampusNetwork()
  if (campusNetwork === 'unreachable') {
    return (
      <div className={className ?? 'm-0 sm:m-8 bg-zinc-900 sm:rounded-md mt-0 sm:mt-14'}>
        <div className={className ? 'w-full h-full' : 'sm:rounded-lg w-full h-[85vh] sm:h-[900px]'}>
          <CampusOnlyNotice variant="dark" />
        </div>
      </div>
    )
  }
  /* --- SYSU-SAM --- */

  return (
    <div className={className ?? "m-0 sm:m-8 bg-zinc-900 sm:rounded-md mt-0 sm:mt-14"}>
      <iframe
        className={className ? "w-full h-full" : "sm:rounded-lg w-full h-[85vh] sm:h-[900px]"}
        src={getActivityMediaDirectory(
          resolvedOrgUuid,
          course?.course_uuid,
          activity.activity_uuid,
          activity.content.filename,
          'documentpdf'
        )}
      />
    </div>
  )
}

export default DocumentPdfActivity
