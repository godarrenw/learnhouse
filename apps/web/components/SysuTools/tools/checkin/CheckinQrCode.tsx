'use client'
/**
 * 二维码。用仓库里已有的 `qrcode` 依赖渲染成 SVG 字符串再内联，
 * 不引新库、不打 canvas，投影时缩放不糊。
 */
import React from 'react'
import QRCode from 'qrcode'

type Props = {
  value: string
  /** 边长（px），投屏页给的是一个很大的值 */
  size?: number
  className?: string
}

export default function CheckinQrCode({ value, size = 320, className }: Props) {
  // 把渲染结果和它对应的 value 存在一起：token 轮换时，新码没算出来之前
  // 宁可先空着，也不要把上一轮的旧二维码继续显示出去。
  const [rendered, setRendered] = React.useState<{ value: string; svg: string }>({
    value: '',
    svg: '',
  })

  React.useEffect(() => {
    if (!value) return
    let cancelled = false
    QRCode.toString(value, {
      type: 'svg',
      errorCorrectionLevel: 'M',
      margin: 1,
      color: { dark: '#000000', light: '#ffffff' },
    })
      .then((markup) => {
        if (!cancelled) setRendered({ value, svg: markup })
      })
      .catch(() => {
        if (!cancelled) setRendered({ value, svg: '' })
      })
    return () => {
      cancelled = true
    }
  }, [value])

  const svg = rendered.value === value ? rendered.svg : ''

  return (
    <div
      className={className}
      style={{ width: size, height: size, maxWidth: '100%' }}
      // qrcode 的输出是它自己生成的 SVG，不含用户输入的原文（内容被编码成方块），
      // 这里的 value 也只由本应用拼接，不来自第三方。
      dangerouslySetInnerHTML={{ __html: svg }}
      data-testid="checkin-qr"
    />
  )
}
