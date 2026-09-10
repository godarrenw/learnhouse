'use client'
/** 成绩册：学生 × 作业矩阵，可按列排序，可导出 CSV。 */
import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Table2 } from 'lucide-react'

import { useLHSession } from '@components/Contexts/LHSessionContext'
import { useOrg } from '@components/Contexts/OrgContext'
import ExportCsvButton, { CsvColumn } from '@components/SysuTools/shared/ExportCsvButton'
import { queryKeys } from '@/lib/query/keys'
import { cn } from '@/lib/utils'
import { getGradebook, GradebookStudent } from '@services/ext/learning'

import SortableTable, { SortableColumn } from './SortableTable'
import {
  NeedCourse,
  PersonCell,
  ToolBody,
  ToolNote,
  Toolbar,
  compareNullable,
  compareText,
  useSort,
} from './shared'

/** 排序键：固定列用名字，作业列用 `cell:<下标>`。 */
type SortKey = 'name' | 'submitted' | 'total' | 'average' | string

const CELL_TONE: Record<string, string> = {
  not_submitted: 'text-gray-400',
  submitted: 'text-gray-800',
  submitted_late: 'text-amber-600',
  graded: 'text-emerald-600',
  graded_late: 'text-amber-600',
}

export default function GradebookTab({ courseUuid }: { courseUuid?: string }) {
  const { t } = useTranslation()
  const org = useOrg() as any
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token
  const orgId: number = org?.id ?? 0
  const sort = useSort<SortKey>('name')
  const [showPercent, setShowPercent] = React.useState(false)

  const { data, isFetching } = useQuery({
    queryKey: queryKeys.ext.learning.gradebook(courseUuid ?? ''),
    queryFn: () => getGradebook(courseUuid as string, orgId, access_token),
    enabled: !!courseUuid && !!orgId && !!access_token,
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  })

  const assignments: any[] = React.useMemo(() => data?.assignments ?? [], [data])
  const students: GradebookStudent[] = React.useMemo(() => data?.students ?? [], [data])

  const rows = React.useMemo(() => {
    const factor = sort.direction === 'asc' ? 1 : -1
    return [...students].sort((a, b) => {
      if (sort.key === 'name') return compareText(a.name, b.name, factor)
      if (sort.key === 'submitted') return compareNullable(a.submitted, b.submitted, factor)
      if (sort.key === 'total') return compareNullable(a.total_score, b.total_score, factor)
      if (sort.key === 'average') {
        return compareNullable(a.average_percentage, b.average_percentage, factor)
      }
      const index = Number(sort.key.slice('cell:'.length))
      return compareNullable(a.cells[index]?.percentage, b.cells[index]?.percentage, factor)
    })
  }, [students, sort.key, sort.direction])

  const columns: SortableColumn<GradebookStudent>[] = React.useMemo(() => {
    const list: SortableColumn<GradebookStudent>[] = [
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
    ]
    assignments.forEach((assignment, index) => {
      list.push({
        key: assignment.assignment_uuid,
        sortKey: `cell:${index}`,
        align: 'end',
        header: assignment.title,
        cell: (row) => {
          const cell = row.cells[index]
          if (!cell) return null
          const empty = cell.score === null && cell.percentage === null
          return (
            <div>
              <div className={cn('text-sm font-semibold', CELL_TONE[cell.status_code])}>
                {empty
                  ? '—'
                  : showPercent
                    ? `${cell.percentage ?? 0}%`
                    : `${cell.score ?? 0}/${cell.max_grade}`}
              </div>
              <div className="text-gray-400 text-xs">{cell.status}</div>
            </div>
          )
        },
      })
    })
    list.push(
      {
        key: 'submitted',
        sortKey: 'submitted',
        align: 'end',
        header: t('ext.tools.learning.table.submitted'),
        cell: (row) => (
          <span className="text-sm text-gray-800">
            {row.submitted}/{row.assignment_total}
          </span>
        ),
      },
      {
        key: 'total',
        sortKey: 'total',
        align: 'end',
        header: t('ext.tools.learning.table.total'),
        cell: (row) => (
          <span className="text-sm font-semibold text-gray-800">{row.total_score}</span>
        ),
      },
      {
        key: 'average',
        sortKey: 'average',
        align: 'end',
        header: t('ext.tools.learning.table.average'),
        cell: (row) =>
          row.average_percentage === null ? null : (
            <span className="text-sm text-gray-800">{row.average_percentage}%</span>
          ),
      }
    )
    return list
  }, [assignments, showPercent, t])

  const csvColumns: CsvColumn<GradebookStudent>[] = React.useMemo(() => {
    const list: CsvColumn<GradebookStudent>[] = [
      { header: t('ext.tools.learning.csv.user_id'), value: (r) => r.user_id },
      { header: t('ext.tools.learning.table.student'), value: (r) => r.name },
      { header: t('ext.tools.learning.csv.email'), value: (r) => r.email },
      { header: t('ext.tools.learning.table.usergroup'), value: (r) => r.usergroup },
    ]
    assignments.forEach((assignment, index) => {
      list.push({ header: assignment.title, value: (r) => r.cells[index]?.score ?? '' })
      list.push({
        header: `${assignment.title}·%`,
        value: (r) => r.cells[index]?.percentage ?? '',
      })
      list.push({
        header: `${assignment.title}·${t('ext.tools.learning.table.status')}`,
        value: (r) => r.cells[index]?.status ?? '',
      })
    })
    list.push(
      { header: t('ext.tools.learning.table.submitted'), value: (r) => r.submitted },
      { header: t('ext.tools.learning.table.total'), value: (r) => r.total_score },
      { header: t('ext.tools.learning.table.average'), value: (r) => r.average_percentage ?? '' }
    )
    return list
  }, [assignments, t])

  if (!courseUuid) {
    return <NeedCourse message={t('ext.common.course_required')} />
  }

  return (
    <>
      <Toolbar
        start={
          <button
            type="button"
            data-testid="learning-toggle-percent"
            onClick={() => setShowPercent(!showPercent)}
            className="text-xs font-medium text-indigo-600 hover:text-indigo-800 cursor-pointer"
          >
            {showPercent
              ? t('ext.tools.learning.gradebook.show_raw')
              : t('ext.tools.learning.gradebook.show_percent')}
          </button>
        }
        end={
          <ExportCsvButton
            filename={`gradebook-${courseUuid.slice(0, 8)}`}
            columns={csvColumns}
            rows={() => rows}
            disabled={rows.length === 0}
          />
        }
      />
      <ToolNote text={data?.note} />
      <ToolBody>
        <SortableTable
          testId="learning-gradebook-table"
          columns={columns}
          rows={rows}
          rowKey={(row) => String(row.user_id)}
          sortKey={sort.key}
          sortDirection={sort.direction}
          onSort={sort.toggle}
          isInitialLoading={!data && isFetching}
          isRefreshing={!!data && isFetching}
          emptyIcon={Table2}
          emptyMessage={t('ext.tools.learning.gradebook.empty')}
        />
      </ToolBody>
    </>
  )
}
