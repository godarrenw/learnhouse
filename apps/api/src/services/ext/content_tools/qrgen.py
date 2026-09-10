# -*- coding: utf-8 -*-
"""纯标准库二维码编码器（byte 模式 / 纠错等级 M / 版本 1–10）。

为什么自己写：这个 skill 的硬性约束是「不装任何第三方包」，而老师最常要的
就是把注册链接印成二维码贴在教室或发到群里。注册链接大约 55 字节，
落在版本 4 上，用不着完整的 40 版本实现。

覆盖范围与取舍：
- 只做 **byte 模式**（UTF-8 字节流），中文、英文、URL 都能编。
- 纠错等级固定 **M**（约能容忍 15% 污损），这是印刷张贴的通用选择。
- 版本 **1–10 自动选**，容量上限 213 字节；超了直接抛错，不静默截断。
- 掩码 0–7 全部试一遍，按国标的四条罚分规则选最优。

输出两种格式：
- `to_svg()` 矢量，放大不糊，可以直接贴进 PPT 或印刷。
- `to_png()` 位图，用 zlib 手写 PNG（真彩 RGB，无压缩损失）。

移植自教学工具 skill 的 `qrgen.py`（SYSU-SAM），逻辑逐行照搬，未改算法。
读回校验在测试里做（`tests/ext/test_content_tools.py`），编码器只管把矩阵算对。
"""
import struct
import zlib

# ---------------------------------------------------------------- 常量表

# 纠错等级 M 的分块表：版本 → [(块数, 每块总码字数, 每块数据码字数), ...]
# 数值来自 ISO/IEC 18004 表 13-22，已与 qrcode 库的 RS_BLOCK_TABLE 逐版本比对过。
RS_BLOCKS_M = {
    1: [(1, 26, 16)],
    2: [(1, 44, 28)],
    3: [(1, 70, 44)],
    4: [(2, 50, 32)],
    5: [(2, 67, 43)],
    6: [(4, 43, 27)],
    7: [(4, 49, 31)],
    8: [(2, 60, 38), (2, 61, 39)],
    9: [(3, 58, 36), (2, 59, 37)],
    10: [(4, 69, 43), (1, 70, 44)],
}

# 定位校正图形的中心坐标（版本 1 没有）
ALIGN_CENTERS = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

# 版本 2–6 在所有码字之后还要补 7 个 0 的余数位；版本 1 和 7–13 是 0 位
REMAINDER_BITS = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0}

MODE_BYTE = 0b0100
EC_LEVEL_M_BITS = 0b00        # 格式信息里 M 的编码就是 00
MAX_VERSION = 10


class QRError(ValueError):
    """内容装不下，或者参数不对。"""


def data_capacity_bytes(version):
    """某个版本在 byte 模式 / 等级 M 下最多能装多少字节。"""
    data_cw = sum(cnt * dc for cnt, _tc, dc in RS_BLOCKS_M[version])
    count_bits = 8 if version <= 9 else 16      # 版本 10 起字符计数指示符变 16 位
    return (data_cw * 8 - 4 - count_bits) // 8


def choose_version(nbytes):
    """挑能装下这么多字节的最小版本。装不下抛 QRError。"""
    for v in range(1, MAX_VERSION + 1):
        if nbytes <= data_capacity_bytes(v):
            return v
    raise QRError(
        "内容 %d 字节，超过本编码器上限 %d 字节（版本 10 / 纠错 M）。"
        "二维码不适合装长文本，请改用短链接。" % (nbytes, data_capacity_bytes(MAX_VERSION)))


# ---------------------------------------------------------------- GF(256)

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:                 # 本原多项式 x^8+x^4+x^3+x^2+1
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gf_mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree):
    """生成多项式 (x-a^0)(x-a^1)…(x-a^(degree-1))，系数从高次到低次。"""
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, c in enumerate(poly):
            nxt[j] ^= _gf_mul(c, 1)
            nxt[j + 1] ^= _gf_mul(c, _EXP[i])
        poly = nxt
    return poly


def _rs_ec(data, ec_count):
    """算一块数据的纠错码字。"""
    gen = _rs_generator(ec_count)
    rem = list(data) + [0] * ec_count
    for i in range(len(data)):
        coef = rem[i]
        if coef == 0:
            continue
        for j, g in enumerate(gen):
            rem[i + j] ^= _gf_mul(g, coef)
    return rem[len(data):]


# ---------------------------------------------------------------- 数据编码


def _encode_data(payload, version):
    """内容 → 完整码字序列（数据块 + 纠错块，按国标交织）。"""
    blocks = RS_BLOCKS_M[version]
    total_data = sum(cnt * dc for cnt, _tc, dc in blocks)
    count_bits = 8 if version <= 9 else 16

    bits = []

    def put(value, length):
        for k in range(length - 1, -1, -1):
            bits.append((value >> k) & 1)

    put(MODE_BYTE, 4)
    put(len(payload), count_bits)
    for byte in payload:
        put(byte, 8)

    # 结束符最多 4 个 0，然后补齐到整字节
    put(0, min(4, total_data * 8 - len(bits)))
    if len(bits) % 8:
        put(0, 8 - len(bits) % 8)

    codewords = [int("".join(str(b) for b in bits[i:i + 8]), 2)
                 for i in range(0, len(bits), 8)]
    # 填充码字，11101100 / 00010001 轮流补
    pad = [0xEC, 0x11]
    while len(codewords) < total_data:
        codewords.append(pad[(len(codewords) - len(bits) // 8) % 2])

    # 切块、算纠错
    data_blocks, ec_blocks = [], []
    pos = 0
    for cnt, total_cw, data_cw in blocks:
        for _ in range(cnt):
            chunk = codewords[pos:pos + data_cw]
            pos += data_cw
            data_blocks.append(chunk)
            ec_blocks.append(_rs_ec(chunk, total_cw - data_cw))

    # 交织：所有块的第 1 个数据码字、第 2 个……然后所有块的纠错码字同理
    out = []
    for i in range(max(len(b) for b in data_blocks)):
        for b in data_blocks:
            if i < len(b):
                out.append(b[i])
    for i in range(max(len(b) for b in ec_blocks)):
        for b in ec_blocks:
            if i < len(b):
                out.append(b[i])
    return out


# ---------------------------------------------------------------- 矩阵

def _bch_format(value):
    """格式信息的 15 位 BCH 编码（5 位数据 + 10 位校验，再异或掩码）。"""
    d = value << 10
    g = 0b10100110111
    for i in range(4, -1, -1):
        if d & (1 << (i + 10)):
            d ^= g << i
    return ((value << 10) | d) ^ 0b101010000010010


def _bch_version(version):
    """版本信息的 18 位 BCH 编码（版本 7 起才要放）。"""
    d = version << 12
    g = 0b1111100100101
    for i in range(5, -1, -1):
        if d & (1 << (i + 12)):
            d ^= g << i
    return (version << 12) | d


def _mask_fn(mask, r, c):
    if mask == 0:
        return (r + c) % 2 == 0
    if mask == 1:
        return r % 2 == 0
    if mask == 2:
        return c % 3 == 0
    if mask == 3:
        return (r + c) % 3 == 0
    if mask == 4:
        return (r // 2 + c // 3) % 2 == 0
    if mask == 5:
        return (r * c) % 2 + (r * c) % 3 == 0
    if mask == 6:
        return ((r * c) % 2 + (r * c) % 3) % 2 == 0
    return ((r + c) % 2 + (r * c) % 3) % 2 == 0


def _blank(size):
    return [[None] * size for _ in range(size)]


def _place_function_patterns(m, version):
    """定位图形、分隔符、定时图形、校正图形、暗模块、版本信息。

    返回 reserved 矩阵：True 表示这个格子是功能图形（含格式信息保留区），
    数据不能往里放。
    """
    size = len(m)
    reserved = [[False] * size for _ in range(size)]

    def finder(top, left):
        for r in range(-1, 8):
            for c in range(-1, 8):
                rr, cc = top + r, left + c
                if not (0 <= rr < size and 0 <= cc < size):
                    continue
                inner = (0 <= r <= 6 and c in (0, 6)) or (0 <= c <= 6 and r in (0, 6)) \
                    or (2 <= r <= 4 and 2 <= c <= 4)
                m[rr][cc] = 1 if inner else 0
                reserved[rr][cc] = True

    finder(0, 0)
    finder(0, size - 7)
    finder(size - 7, 0)

    # 定时图形
    for i in range(8, size - 8):
        bit = 1 if i % 2 == 0 else 0
        m[6][i] = bit
        reserved[6][i] = True
        m[i][6] = bit
        reserved[i][6] = True

    # 校正图形
    centers = ALIGN_CENTERS[version]
    for a in centers:
        for b in centers:
            if (a, b) in ((6, 6), (6, size - 7), (size - 7, 6)):
                continue
            for r in range(-2, 3):
                for c in range(-2, 3):
                    on = max(abs(r), abs(c)) != 1
                    m[a + r][b + c] = 1 if on else 0
                    reserved[a + r][b + c] = True

    # 固定的暗模块
    m[size - 8][8] = 1
    reserved[size - 8][8] = True

    # 格式信息保留区（内容稍后按掩码填）
    for i in range(9):
        if not reserved[8][i]:
            reserved[8][i] = True
        if not reserved[i][8]:
            reserved[i][8] = True
    for i in range(8):
        reserved[8][size - 1 - i] = True
        reserved[size - 1 - i][8] = True

    # 版本信息（版本 7 起，左下和右上各一块 6x3）
    if version >= 7:
        vinfo = _bch_version(version)
        for i in range(18):
            bit = (vinfo >> i) & 1
            r, c = i // 3, size - 11 + i % 3
            m[r][c] = bit
            reserved[r][c] = True
            m[c][r] = bit
            reserved[c][r] = True
    return reserved


def _place_format(m, mask):
    """把格式信息（纠错等级 + 掩码号）写进两处保留区。"""
    size = len(m)
    fmt = _bch_format((EC_LEVEL_M_BITS << 3) | mask)
    for i in range(15):
        # 格式信息按「最高位排在 (8,0)」的顺序放，所以这里从高位往低位取
        bit = (fmt >> (14 - i)) & 1
        # 第一处：左上角围着定位图形拐一圈
        if i < 6:
            m[8][i] = bit
        elif i == 6:
            m[8][7] = bit
        elif i == 7:
            m[8][8] = bit
        elif i == 8:
            m[7][8] = bit
        else:
            m[14 - i][8] = bit
        # 第二处：左下 7 格 + 右上 8 格，冗余一份
        # 注意 i<7 而不是 i<8：(size-8, 8) 是固定的暗模块，写进去会把它覆盖掉
        if i < 7:
            m[size - 1 - i][8] = bit
        else:
            m[8][size - 15 + i] = bit


def _place_data(m, reserved, codewords, version):
    """码字按之字形从右下角往上填。"""
    size = len(m)
    bits = []
    for cw in codewords:
        for k in range(7, -1, -1):
            bits.append((cw >> k) & 1)
    bits.extend([0] * REMAINDER_BITS[version])   # 余数位固定填 0

    idx = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:            # 第 6 列是竖向定时图形，整列跳过
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for r in rows:
            for c in (col, col - 1):
                if reserved[r][c]:
                    continue
                m[r][c] = bits[idx] if idx < len(bits) else 0
                idx += 1
        upward = not upward
        col -= 2
    return idx


def _penalty(m):
    """国标的四条罚分规则，用来挑最不容易误读的掩码。"""
    size = len(m)
    score = 0

    # 规则 1：同色连续 5 格起，每多一格加 1 分
    for line in list(m) + [list(col) for col in zip(*m)]:
        run, prev = 1, line[0]
        for v in line[1:]:
            if v == prev:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run, prev = 1, v
        if run >= 5:
            score += 3 + (run - 5)

    # 规则 2：每个 2x2 同色方块 3 分
    for r in range(size - 1):
        for c in range(size - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3

    # 规则 3：出现 1:1:3:1:1 比例的伪定位图形，每处 40 分
    pat1 = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    pat2 = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
    for line in list(m) + [list(col) for col in zip(*m)]:
        for i in range(size - 10):
            seg = line[i:i + 11]
            if seg == pat1 or seg == pat2:
                score += 40

    # 规则 4：深色格子占比每偏离 50% 五个百分点加 10 分
    dark = sum(sum(row) for row in m)
    ratio = dark * 100 // (size * size)
    score += 10 * (abs(ratio - 50) // 5)
    return score


def make_matrix(text, version=None):
    """内容 → 二维码矩阵（list[list[int]]，1 是深色）。

    version 不给就自动选最小可用版本。返回 (矩阵, 版本, 掩码号)。
    """
    payload = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    if not payload:
        raise QRError("二维码内容不能为空")
    if version is None:
        version = choose_version(len(payload))
    elif not (1 <= version <= MAX_VERSION):
        raise QRError("本编码器只支持版本 1–%d" % MAX_VERSION)
    elif len(payload) > data_capacity_bytes(version):
        raise QRError("版本 %d 装不下 %d 字节（上限 %d）"
                      % (version, len(payload), data_capacity_bytes(version)))

    codewords = _encode_data(payload, version)
    size = version * 4 + 17

    best = None
    for mask in range(8):
        m = _blank(size)
        reserved = _place_function_patterns(m, version)
        _place_data(m, reserved, codewords, version)
        for r in range(size):
            for c in range(size):
                if not reserved[r][c] and _mask_fn(mask, r, c):
                    m[r][c] ^= 1
        _place_format(m, mask)
        m = [[int(v or 0) for v in row] for row in m]
        s = _penalty(m)
        if best is None or s < best[0]:
            best = (s, m, mask)
    return best[1], version, best[2]


# ---------------------------------------------------------------- 输出


def to_svg(matrix, scale=8, quiet=4, caption=None, dark="#000000", light="#ffffff"):
    """矩阵 → SVG 文本。caption 会排在码图下方居中。"""
    size = len(matrix)
    side = (size + quiet * 2) * scale
    cap_h = int(scale * 3.2) if caption else 0
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d" shape-rendering="crispEdges">' % (side, side + cap_h, side, side + cap_h),
        '<rect width="%d" height="%d" fill="%s"/>' % (side, side + cap_h, light),
    ]
    # 同一行连续的深色格子合成一个矩形，文件更小
    for r, row in enumerate(matrix):
        c = 0
        while c < size:
            if row[c]:
                run = 1
                while c + run < size and row[c + run]:
                    run += 1
                parts.append('<rect x="%d" y="%d" width="%d" height="%d" fill="%s"/>' % (
                    (c + quiet) * scale, (r + quiet) * scale, run * scale, scale, dark))
                c += run
            else:
                c += 1
    if caption:
        esc = (caption.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        parts.append(
            '<text x="%d" y="%d" text-anchor="middle" fill="%s" '
            'font-family="PingFang SC, Microsoft YaHei, Helvetica, Arial, sans-serif" '
            'font-size="%d">%s</text>' % (side // 2, side + int(cap_h * 0.7), dark,
                                          int(scale * 1.8), esc))
    parts.append("</svg>")
    return "\n".join(parts)


def _png_bytes(rows_rgb, width, height):
    """把逐行 RGB 字节拼成 PNG（zlib 手写，不依赖任何图像库）。"""
    raw = b"".join(b"\x00" + row for row in rows_rgb)   # 每行前面的 0 是「无过滤器」

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def to_png(matrix, scale=8, quiet=4, dark=(0, 0, 0), light=(255, 255, 255),
           caption_height=0):
    """矩阵 → PNG 字节。

    caption_height > 0 时在下方留出一条空白（给 tools.py 里的 PIL 分支写字用；
    没有 PIL 就只是一条白边，码图本身照常能扫）。
    """
    size = len(matrix)
    width = (size + quiet * 2) * scale
    height = width + int(caption_height)
    blank = bytes(light) * width
    rows = [blank for _ in range(quiet * scale)]
    for row in matrix:
        line = bytearray()
        line += bytes(light) * (quiet * scale)
        for v in row:
            line += bytes(dark if v else light) * scale
        line += bytes(light) * (quiet * scale)
        line = bytes(line)
        rows.extend([line] * scale)
    while len(rows) < height:
        rows.append(blank)
    return _png_bytes(rows, width, height)
