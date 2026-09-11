'use client'
/**
 * 学生扫码落地页 `/checkin/<session>?t=<token>`。
 * 放在 (withmenu) 下，学生扫进来能看到组织顶栏，认得出是哪个站点。
 */
import React, { Suspense, use } from 'react'
import CheckinClient from '@components/SysuCheckin/CheckinClient'

type CheckinPageParams = {
  orgslug: string
  session: string
}

function CheckinPage(props: { params: Promise<CheckinPageParams> }) {
  const params = use(props.params)
  return (
    // useSearchParams 需要 Suspense 边界，否则整页会被强制动态渲染
    <Suspense fallback={null}>
      <CheckinClient orgslug={params.orgslug} sessionUuid={params.session} />
    </Suspense>
  )
}

export default CheckinPage
