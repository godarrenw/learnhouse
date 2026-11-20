import { useOrg } from '@components/Contexts/OrgContext'
import { getAPIUrl } from '@services/config/config'
import { getActivityMediaDirectory } from '@services/media/media'
import React, { useState } from 'react'
import { getActivityDocuments } from './documents'
import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation()
  const [selectedFilename, setSelectedFilename] = useState('')
  const [interactiveFilename, setInteractiveFilename] = useState('')
  const documents = getActivityDocuments(activity)
  const selected = documents.find(({ filename }) => filename === selectedFilename) || documents[0]
  if (!selected) return null
  const { filename, name } = selected
  const collection = documents.length > 1
  const previewClass = collection ? 'w-full h-full' : className
  const interactive = interactiveFilename === filename

  const preview = filename.endsWith('_documenthtml.txt') ? (
    <div className={`flex flex-col ${previewClass ?? 'm-0 sm:m-8 sm:rounded-md mt-0 sm:mt-14 bg-white'}`}>
      <button
        type="button"
        aria-pressed={interactive}
        className="m-2 self-start rounded-md border border-gray-200 bg-white px-3 py-1 text-sm text-gray-700 hover:bg-gray-50"
        onClick={() => setInteractiveFilename(interactive ? '' : filename)}
      >
        {t('dashboard.courses.structure.activity.document_file.interactive_preview')}
      </button>
      <iframe
        key={`${filename}:${interactive}`}
        className={previewClass ? 'min-h-0 w-full flex-1' : 'sm:rounded-lg w-full h-[85vh] sm:h-[900px]'}
        src={`${getAPIUrl()}activities/${encodeURIComponent(activity.activity_uuid)}/document-html?document=${encodeURIComponent(filename)}&interactive=${interactive}`}
        title={name}
        sandbox={interactive ? 'allow-scripts' : ''}
        referrerPolicy="no-referrer"
      />
    </div>
  ) : <DocumentPdfActivity key={filename} {...props} className={previewClass} filename={filename} title={name} />

  if (!collection) return preview

  return (
    <div className={className ?? 'sm:m-8 sm:mt-14 sm:rounded-md bg-white'}>
      <div className="flex flex-col h-full gap-2">
        <label className="flex flex-wrap items-center gap-2 px-3 pt-3 text-sm font-medium text-gray-700">
          {t('dashboard.courses.structure.activity.document_file.select')}
          <select
            className="max-w-full rounded-md border border-gray-200 bg-white px-2 py-1"
            value={filename}
            onChange={(event) => {
              setSelectedFilename(event.target.value)
              setInteractiveFilename('')
            }}
          >
            {documents.map((item) => (
              <option key={item.filename} value={item.filename}>{item.name}</option>
            ))}
          </select>
        </label>
        <div className={className ? 'min-h-0 flex-1' : 'h-[85vh] sm:h-[900px]'}>{preview}</div>
      </div>
    </div>
  )
}

function DocumentPdfActivity({
  activity, course, orgUuid, className, filename, title,
}: DocumentActivityProps & { filename: string; title: string }) {
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
    filename,
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
        title={title}
      />
      {/* --- SYSU-SAM END --- */}
    </div>
  )
}

export default DocumentActivity
