'use client'
/** 缺交名单：按班级名单对比提交记录，可按作业筛选。 */
import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { UserX } from 'lucide-react'

import { useLHSession } from '@components/Contexts/LHSessionContext'
import { useOrg } from '@components/Contexts/OrgContext'
import DataTable, { DataTableColumn } from '@components/SysuTools/shared/DataTable'
import ExportCsvButton, { CsvColumn } from '@components/SysuTools/shared/ExportCsvButton'
import { queryKeys } from '@/lib/query/keys'
import { getMissing } from '@services/ext/learning'

import { NeedCourse, PersonCell, ToolBody, ToolNote, Toolbar } from './shared'

export default function MissingTab({ courseUuid }: { courseUuid?: string }) {
  const { t } = useTranslation()
  const org = useOrg() as any
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token
  const orgId: number = org?.id ?? 0

  // 作业筛选和课程绑在一起存：换课程时筛选自动失效，不用在 effect 里 setState。
  const [filter, setFilter] = React.useState<{ course?: string; assignment: string | null }>({
    course: undefined,
    assignment: null,
  })
  const assignmentUuid = filter.course === courseUuid ? filter.assignment : null
  const setAssignmentUuid = React.useCallback(
    (next: string | null) => setFilter({ course: courseUuid, assignment: next }),
    [courseUuid]
  )

  const { data, isFetching } = useQuery({
    queryKey: queryKeys.ext.learning.missing(courseUuid ?? '', assignmentUuid),
    queryFn: () => getMissing(courseUuid as string, orgId, assignmentUuid, access_token),
    enabled: !!courseUuid && !!orgId && !!access_token,
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  })

  const rows: any[] = React.useMemo(() => data?.missing ?? [], [data])
  const assignments: any[] = data?.assignments ?? []

  const columns: DataTableColumn<any>[] = [
    {
      key: 'student',
      header: t('ext.tools.learning.table.student'),
      cell: (row) => <PersonCell name={row.name} email={row.email} />,
    },
    {
      key: 'usergroup',
      header: t('ext.tools.learning.table.usergroup'),
      cell: (row) => <span className="text-gray-400 text-xs">{row.usergroup}</span>,
    },
    {
      key: 'assignment',
      header: t('ext.tools.learning.missing.assignment'),
      cell: (row) => <span className="text-gray-800 text-sm">{row.assignment}</span>,
    },
    {
      key: 'due_date',
      header: t('ext.tools.learning.table.due_date'),
      cell: (row) => <span className="text-gray-400 text-xs">{row.due_date}</span>,
    },
    {
      key: 'status',
      align: 'end',
      header: t('ext.tools.learning.table.status'),
      cell: (row) => (
        <span className="bg-red-50 text-red-600 px-2 py-1 rounded-md text-xs font-medium">
          {row.status}
        </span>
      ),
    },
  ]

  const csvColumns: CsvColumn<any>[] = [
    { header: t('ext.tools.learning.csv.user_id'), value: (r) => r.user_id },
    { header: t('ext.tools.learning.table.student'), value: (r) => r.name },
    { header: t('ext.tools.learning.csv.email'), value: (r) => r.email },
    { header: t('ext.tools.learning.table.usergroup'), value: (r) => r.usergroup },
    { header: t('ext.tools.learning.missing.assignment'), value: (r) => r.assignment },
    { header: t('ext.tools.learning.table.due_date'), value: (r) => r.due_date },
    { header: t('ext.tools.learning.table.status'), value: (r) => r.status },
  ]

  if (!courseUuid) {
    return <NeedCourse message={t('ext.common.course_required')} />
  }

  return (
    <>
      <Toolbar
        start={
          <label className="flex items-center gap-2 min-w-0">
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
              {t('ext.tools.learning.missing.assignment')}
            </span>
            <select
              data-testid="learning-missing-assignment"
              value={assignmentUuid ?? ''}
              onChange={(event) => setAssignmentUuid(event.target.value || null)}
              className="bg-white nice-shadow rounded-md text-sm text-gray-800 px-3 py-2 min-w-[12rem] max-w-full truncate cursor-pointer"
            >
              <option value="">{t('ext.tools.learning.missing.all')}</option>
              {assignments.map((assignment) => (
                <option key={assignment.assignment_uuid} value={assignment.assignment_uuid}>
                  {assignment.title}
                </option>
              ))}
            </select>
          </label>
        }
        end={
          <ExportCsvButton
            filename={`missing-${courseUuid.slice(0, 8)}`}
            columns={csvColumns}
            rows={() => rows}
            disabled={rows.length === 0}
          />
        }
      />
      <ToolNote text={data?.note} />
      <ToolBody>
        <div data-testid="learning-missing">
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(row) => `${row.user_id}-${row.assignment_uuid}`}
            isInitialLoading={!data && isFetching}
            isRefreshing={!!data && isFetching}
            hasActiveFilters={!!assignmentUuid}
            onClearFilters={() => setAssignmentUuid(null)}
            emptyIcon={UserX}
            emptyMessage={
              assignmentUuid
                ? t('ext.tools.learning.missing.none_for_assignment')
                : t('ext.tools.learning.missing.none')
            }
          />
        </div>
      </ToolBody>
    </>
  )
}
