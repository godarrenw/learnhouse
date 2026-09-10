'use client'
/** 学习进度：每人完成多少活动，点开看明细。 */
import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, Circle, TrendingUp } from 'lucide-react'

import { useLHSession } from '@components/Contexts/LHSessionContext'
import { useOrg } from '@components/Contexts/OrgContext'
import LearnHouseSpinner from '@components/Objects/Loaders/LearnHouseSpinner'
import Modal from '@components/Objects/StyledElements/Modal/Modal'
import ExportCsvButton, { CsvColumn } from '@components/SysuTools/shared/ExportCsvButton'
import { queryKeys } from '@/lib/query/keys'
import { getProgress, getStudentProgress } from '@services/ext/learning'

import SortableTable, { SortableColumn } from './SortableTable'
import {
  NeedCourse,
  PersonCell,
  ToolBody,
  ToolNote,
  Toolbar,
  compareNullable,
  compareText,
  formatTime,
  useSort,
} from './shared'

type SortKey = 'name' | 'percentage' | 'last_active'

function StudentDetail({
  courseUuid,
  orgId,
  student,
}: {
  courseUuid: string
  orgId: number
  student: string
}) {
  const { t } = useTranslation()
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token

  const { data, isFetching } = useQuery({
    queryKey: queryKeys.ext.learning.student(courseUuid, student),
    queryFn: () => getStudentProgress(courseUuid, orgId, student, access_token),
    enabled: !!orgId && !!access_token,
    staleTime: 60_000,
  })

  if (!data && isFetching) {
    return (
      <div className="py-16 flex justify-center">
        <LearnHouseSpinner size={28} />
      </div>
    )
  }

  const steps: any[] = data?.steps ?? []
  const facts = [
    {
      label: t('ext.tools.learning.progress.completed'),
      value: `${data?.completed ?? 0}/${data?.total_activities ?? 0}（${data?.percentage ?? 0}%）`,
    },
    {
      label: t('ext.tools.learning.progress.started_at'),
      value: formatTime(data?.started_at) ?? '—',
    },
    {
      label: t('ext.tools.learning.progress.last_active'),
      value: formatTime(data?.last_active_at) ?? '—',
    },
  ]

  return (
    <div className="min-w-0" data-testid="learning-student-detail">
      <div className="flex flex-wrap gap-6 pb-4 border-b border-gray-100">
        {facts.map((fact) => (
          <div key={fact.label}>
            <div className="text-xs text-gray-400">{fact.label}</div>
            <div className="text-gray-800 font-semibold text-sm">{fact.value}</div>
          </div>
        ))}
      </div>
      {steps.length === 0 ? (
        <div className="py-16 text-center text-gray-400 text-sm font-medium">
          {t('ext.tools.learning.progress.no_steps')}
        </div>
      ) : (
        <ul className="divide-y divide-gray-50 max-h-[24rem] overflow-y-auto">
          {steps.map((step) => (
            <li key={step.activity_id} className="py-3 flex items-start gap-3 min-w-0">
              {step.complete ? (
                <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
              ) : (
                <Circle className="w-4 h-4 text-gray-300 shrink-0 mt-0.5" />
              )}
              <div className="min-w-0 flex-1">
                <div className="text-gray-800 font-semibold text-sm truncate">
                  {step.activity_name}
                </div>
                <div className="text-gray-400 text-xs truncate">{step.chapter}</div>
              </div>
              <div className="text-gray-400 text-xs whitespace-nowrap">
                {formatTime(step.completed_at) ?? '—'}
              </div>
            </li>
          ))}
        </ul>
      )}
      {data?.denominator_note ? (
        <p className="pt-4 text-xs text-gray-400">{data.denominator_note}</p>
      ) : null}
    </div>
  )
}

export default function ProgressTab({ courseUuid }: { courseUuid?: string }) {
  const { t } = useTranslation()
  const org = useOrg() as any
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token
  const orgId: number = org?.id ?? 0
  const sort = useSort<SortKey>('name')
  const [openStudent, setOpenStudent] = React.useState<any>(null)

  const { data, isFetching } = useQuery({
    queryKey: queryKeys.ext.learning.progress(courseUuid ?? ''),
    queryFn: () => getProgress(courseUuid as string, orgId, access_token),
    enabled: !!courseUuid && !!orgId && !!access_token,
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  })

  const students: any[] = React.useMemo(() => data?.students ?? [], [data])

  const rows = React.useMemo(() => {
    const factor = sort.direction === 'asc' ? 1 : -1
    return [...students].sort((a, b) => {
      if (sort.key === 'name') return compareText(a.name, b.name, factor)
      if (sort.key === 'last_active') {
        return compareText(a.last_active_at, b.last_active_at, factor)
      }
      return compareNullable(a.percentage, b.percentage, factor)
    })
  }, [students, sort.key, sort.direction])

  const columns: SortableColumn<any>[] = [
    {
      key: 'student',
      sortKey: 'name',
      header: t('ext.tools.learning.table.student'),
      cell: (row) => <PersonCell name={row.name} email={row.email} />,
    },
    {
      key: 'usergroup',
      header: t('ext.tools.learning.table.usergroup'),
      cell: (row) => <span className="text-gray-400 text-xs">{row.usergroup}</span>,
    },
    {
      key: 'percentage',
      sortKey: 'percentage',
      align: 'end',
      header: t('ext.tools.learning.progress.percentage'),
      cell: (row) => (
        <div>
          <div className="text-sm font-semibold text-gray-800">
            {row.percentage === null ? '—' : `${row.percentage}%`}
          </div>
          <div className="text-gray-400 text-xs">
            {row.completed}/{row.total_activities}
          </div>
        </div>
      ),
    },
    {
      key: 'last_active',
      sortKey: 'last_active',
      align: 'end',
      header: t('ext.tools.learning.progress.last_active'),
      cell: (row) => (
        <span className="text-gray-400 text-xs">{formatTime(row.last_active_at)}</span>
      ),
    },
    {
      key: 'actions',
      align: 'end',
      header: t('ext.common.actions'),
      cell: (row) => (
        <button
          type="button"
          data-testid="learning-progress-detail"
          onClick={() => setOpenStudent(row)}
          className="text-xs font-medium text-indigo-600 hover:text-indigo-800 cursor-pointer"
        >
          {t('ext.tools.learning.progress.detail')}
        </button>
      ),
    },
  ]

  const csvColumns: CsvColumn<any>[] = [
    { header: t('ext.tools.learning.csv.user_id'), value: (r) => r.user_id },
    { header: t('ext.tools.learning.table.student'), value: (r) => r.name },
    { header: t('ext.tools.learning.csv.email'), value: (r) => r.email },
    { header: t('ext.tools.learning.table.usergroup'), value: (r) => r.usergroup },
    { header: t('ext.tools.learning.progress.completed'), value: (r) => r.completed },
    {
      header: t('ext.tools.learning.progress.total_activities'),
      value: (r) => r.total_activities,
    },
    { header: t('ext.tools.learning.progress.percentage'), value: (r) => r.percentage ?? '' },
    {
      header: t('ext.tools.learning.progress.last_active'),
      value: (r) => r.last_active_at ?? '',
    },
  ]

  if (!courseUuid) {
    return <NeedCourse message={t('ext.common.course_required')} />
  }

  return (
    <>
      <Toolbar
        start={
          <span className="text-xs text-gray-400">
            {t('ext.tools.learning.progress.total_activities')}：{data?.total_activities ?? '—'}
          </span>
        }
        end={
          <ExportCsvButton
            filename={`progress-${courseUuid.slice(0, 8)}`}
            columns={csvColumns}
            rows={() => rows}
            disabled={rows.length === 0}
          />
        }
      />
      <ToolNote text={data?.denominator_note} />
      <ToolBody>
        <SortableTable
          testId="learning-progress-table"
          columns={columns}
          rows={rows}
          rowKey={(row) => String(row.user_id)}
          sortKey={sort.key}
          sortDirection={sort.direction}
          onSort={sort.toggle}
          isInitialLoading={!data && isFetching}
          isRefreshing={!!data && isFetching}
          emptyIcon={TrendingUp}
          emptyMessage={data?.note || t('ext.tools.learning.progress.empty')}
        />
      </ToolBody>
      <Modal
        isDialogOpen={!!openStudent}
        onOpenChange={(open) => {
          if (!open) setOpenStudent(null)
        }}
        dialogTitle={openStudent?.name ?? ''}
        dialogDescription={t('ext.tools.learning.progress.detail_desc')}
        minWidth="md"
        dialogContent={
          openStudent ? (
            <StudentDetail
              courseUuid={courseUuid}
              orgId={orgId}
              student={openStudent.user_uuid}
            />
          ) : null
        }
      />
    </>
  )
}
