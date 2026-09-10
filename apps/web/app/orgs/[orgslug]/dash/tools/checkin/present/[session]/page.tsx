'use client'
/**
 * 投屏页路由。放在 /dash 下是为了直接复用后台 layout 的鉴权，
 * 页面本体用 fixed inset-0 盖住左侧菜单，实际观感是全屏无菜单。
 */
import React, { use } from 'react'
import CheckinPresent from '@components/SysuTools/tools/checkin/CheckinPresent'

type PresentParams = {
  orgslug: string
  session: string
}

function CheckinPresentPage(props: { params: Promise<PresentParams> }) {
  const params = use(props.params)
  return (
    <CheckinPresent orgslug={params.orgslug} sessionUuid={params.session} />
  )
}

export default CheckinPresentPage
