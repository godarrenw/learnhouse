import { useOrg } from '@components/Contexts/OrgContext'
import { getAPIUrl } from '@services/config/config'
import { getActivityMediaDirectory } from '@services/media/media'
import React from 'react'
/* --- SYSU-SAM --- */
import { useCampusNetwork } from '@services/media/useCampusNetwork'
import { useSignedMediaUrls } from '@services/media/useSignedMediaUrls'
import CampusOnlyNotice from '@components/Objects/Media/CampusOnlyNotice'
/* --- SYSU-SAM END --- */

interface DocumentActivityProps {
  activity: any
  course: any
  orgUuid?: string
  className?: string
}

function DocumentActivity(props: DocumentActivityProps) {
  const { activity, className } = props
  const filename = activity.content?.filename
  if (typeof filename !== 'string' || !filename) return null
  if (!filename.endsWith('_documenthtml.txt')) return <DocumentPdfActivity {...props} />

  return (
    <div className={className ?? 'm-0 sm:m-8 sm:rounded-md mt-0 sm:mt-14 bg-white'}>
      <iframe
        key={filename}
        className={className ? 'w-full h-full' : 'sm:rounded-lg w-full h-[85vh] sm:h-[900px]'}
        src={`${getAPIUrl()}activities/${encodeURIComponent(activity.activity_uuid)}/document-html`}
        title={activity.name}
        sandbox=""
        referrerPolicy="no-referrer"
      />
    </div>
  )
}

function DocumentPdfActivity({ activity, course, orgUuid, className }: DocumentActivityProps) {
  const org = useOrg() as any
  const resolvedOrgUuid = orgUuid || org?.org_uuid

  /* --- SYSU-SAM --- */
  // 跨域 iframe 加载失败不触发任何事件，等不到 onError，只能主动探。
  const campusNetwork = useCampusNetwork()
  // 重媒体分流：PDF 讲义换成「媒体域名 + 限时签名」，未启用时原样返回。
  const rawPdfUrl = getActivityMediaDirectory(
    resolvedOrgUuid,
    course?.course_uuid,
    activity.activity_uuid,
    activity.content.filename,
    'documentpdf'
  )
  const signed = useSignedMediaUrls([rawPdfUrl])
  if (campusNetwork === 'unreachable') {
    return (
      <div className={className ?? 'm-0 sm:m-8 bg-zinc-900 sm:rounded-md mt-0 sm:mt-14'}>
        <div className={className ? 'w-full h-full' : 'sm:rounded-lg w-full h-[85vh] sm:h-[900px]'}>
          <CampusOnlyNotice variant="dark" />
        </div>
      </div>
    )
  }
  /* --- SYSU-SAM END --- */

  return (
    <div className={className ?? "m-0 sm:m-8 bg-zinc-900 sm:rounded-md mt-0 sm:mt-14"}>
      {/* --- SYSU-SAM: src 改走签名后的地址，其余不变 --- */}
      <iframe
        className={className ? "w-full h-full" : "sm:rounded-lg w-full h-[85vh] sm:h-[900px]"}
        src={signed.get(rawPdfUrl)}
      />
      {/* --- SYSU-SAM END --- */}
    </div>
  )
}

export default DocumentActivity
