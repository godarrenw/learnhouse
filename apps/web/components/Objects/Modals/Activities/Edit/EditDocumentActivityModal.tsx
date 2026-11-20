'use client'
import React, { useState } from 'react'
import LearnHouseSpinner from '@components/Objects/Loaders/LearnHouseSpinner'
import { FileText } from '@phosphor-icons/react'
import { constructAcceptValue } from '@/lib/constants'
import { updateDocumentActivity } from '@services/courses/activities'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import toast from 'react-hot-toast'
import { useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '@/lib/query/keys'
import { revalidateTags } from '@services/utils/ts/requests'
import { useTranslation } from 'react-i18next'
import { getActivityDocuments, MAX_DOCUMENTS } from '@components/Objects/Activities/DocumentPdf/documents'

const SUPPORTED_FILES = constructAcceptValue(['pdf', 'html'])

interface EditDocumentActivityModalProps {
  activity: any
  courseUuid: string
  orgSlug: string
  onClose: () => void
}

function EditDocumentActivityModal({ activity, courseUuid, orgSlug, onClose }: EditDocumentActivityModalProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token

  const [name, setName] = useState(activity.name || '')
  const [documentFiles, setDocumentFiles] = useState<File[]>([])
  const [removedDocuments, setRemovedDocuments] = useState<string[]>([])
  const [isSubmitting, setIsSubmitting] = useState(false)
  const documents = getActivityDocuments(activity)
  const documentCount = documents.length - removedDocuments.length + documentFiles.length
  const invalidCount = documentCount < 1 || documentCount > MAX_DOCUMENTS

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (invalidCount) return
    setIsSubmitting(true)

    const toastId = toast.loading('Updating document activity...')
    try {
      const res = await updateDocumentActivity(
        activity.activity_uuid,
        access_token,
        name !== activity.name ? name : undefined,
        documentFiles,
        removedDocuments,
      )

      if (res?.success === false) {
        const detail = res.data?.detail
        toast.error(typeof detail === 'string' ? detail : 'Failed to update document activity', { id: toastId })
      } else {
        toast.success('Document activity updated', { id: toastId })
        void queryClient.invalidateQueries({
          queryKey: queryKeys.courses.meta(courseUuid.replace(/^course_/, '')),
        })
        void revalidateTags(['courses'], orgSlug)
        onClose()
      }
    } catch {
      toast.error('Failed to update document activity', { id: toastId })
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div
        className="relative flex items-center justify-center h-20 rounded-xl overflow-hidden"
        style={{
          backgroundImage:
            'repeating-linear-gradient(0deg, transparent, transparent 8px, rgba(167,243,208,0.25) 8px, rgba(167,243,208,0.25) 9px), repeating-linear-gradient(90deg, transparent, transparent 8px, rgba(167,243,208,0.25) 8px, rgba(167,243,208,0.25) 9px)',
        }}
      >
        <span className="flex items-center gap-2 bg-white nice-shadow rounded-full px-4 py-1.5 text-sm font-medium text-gray-600">
          <FileText size={18} weight="duotone" className="text-emerald-400" />
          {t('dashboard.courses.structure.activity.types.document')}
        </span>
      </div>

      <div className="rounded-xl nice-shadow p-4 space-y-4">
        <div className="space-y-1.5">
          <label htmlFor="document-collection-name" className="text-sm font-medium text-gray-700">
            {t('dashboard.courses.structure.activity.document_file.collection_name')}
          </label>
          <input
            id="document-collection-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            type="text"
            required
            placeholder="Enter a name..."
            className="w-full h-9 px-3 text-sm rounded-lg bg-gray-50 border border-gray-200 outline-none focus:border-gray-300 focus:ring-1 focus:ring-gray-200 transition-colors"
          />
        </div>

        {documents.length > 0 && (
          <fieldset className="space-y-1.5">
            <legend className="text-sm font-medium text-gray-700">
              {t('dashboard.courses.structure.activity.document_file.keep')}
            </legend>
            <div className="max-h-40 space-y-1 overflow-y-auto">
              {documents.map(({ filename, name }) => (
                <label key={filename} className="flex items-start gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={!removedDocuments.includes(filename)}
                    onChange={(event) => {
                      const keep = event.target.checked
                      setRemovedDocuments((current) =>
                        keep ? current.filter((item) => item !== filename) : [...current, filename]
                      )
                    }}
                  />
                  <span className="break-all">{name}</span>
                </label>
              ))}
            </div>
          </fieldset>
        )}

        <div className="space-y-1.5">
          <label htmlFor="document-collection-files" className="text-sm font-medium text-gray-700">
            {t('dashboard.courses.structure.activity.document_file.add')}
          </label>
          <input
            id="document-collection-files"
            type="file"
            multiple
            accept={SUPPORTED_FILES}
            onChange={(event) => setDocumentFiles(Array.from(event.target.files ?? []))}
            className="w-full text-sm text-gray-500 file:me-3 file:py-1.5 file:px-3 file:rounded-full file:border-0 file:text-xs file:font-medium file:bg-gray-100 file:text-gray-700 hover:file:bg-gray-200 transition-colors"
          />
          <p className={`text-xs ${invalidCount ? 'text-red-500' : 'text-gray-500'}`}>
            {t('dashboard.courses.structure.activity.document_file.limit', { max: MAX_DOCUMENTS })}
          </p>
        </div>
      </div>

      <div className="flex justify-end">
        <button
          type="submit"
          disabled={isSubmitting || invalidCount}
          className="inline-flex items-center justify-center h-9 px-5 text-sm font-medium text-white bg-black rounded-lg hover:bg-gray-800 transition-colors disabled:opacity-50"
        >
          {isSubmitting ? (
            <LearnHouseSpinner size={18} className="[&>div]:border-t-white" />
          ) : (
            'Save changes'
          )}
        </button>
      </div>
    </form>
  )
}

export default EditDocumentActivityModal
