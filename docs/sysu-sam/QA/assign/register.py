#!/usr/bin/env python3
"""把作业工具接进教学工具骨架：registry 一条 + 两个语言包的文案。

为什么单独一个脚本：作业工具这条分支是在骨架合入 `sysu-sam` **之前**开的，
`components/SysuTools/registry.ts` 与 `locales/ext/{zh,en}.json` 当时还不存在，
分支里放一份自己的拷贝只会在 rebase 时和骨架撞车。所以接入动作收成这个幂等脚本：
骨架合入、本分支 rebase 之后，在仓库根目录跑一次就行。

    python3 docs/sysu-sam/QA/assign/register.py

跑第二次不会重复插入。跑完记得 `bun run lint:strict` 再提交。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_locales import EN, SEARCH_EN, SEARCH_ZH, ZH, patch  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
REGISTRY = ROOT / "apps/web/components/SysuTools/registry.ts"
LOCALES = ROOT / "apps/web/locales/ext"

ENTRY = """  {
    key: 'assign',
    titleKey: 'ext.tools.assign.title',
    descKey: 'ext.tools.assign.description',
    icon: ClipboardPen,
    component: lazy(() => import('./tools/assign/AssignTools')),
    minRole: 'instructor',
    courseScoped: true,
  },
"""


def patch_registry() -> None:
    src = REGISTRY.read_text(encoding="utf-8")
    if "'assign'" in src:
        print("registry.ts 已经有 assign 条目，跳过")
        return

    # 1. 图标 import：把 ClipboardPen 并进现有的 lucide-react import
    match = re.search(r"import \{([^}]*)\} from 'lucide-react'", src)
    if not match:
        raise SystemExit("registry.ts 里找不到 lucide-react 的 import，请手工加 ClipboardPen")
    names = sorted({n.strip() for n in match.group(1).split(",") if n.strip()} | {"ClipboardPen"})
    src = src[: match.start()] + "import { %s } from 'lucide-react'" % ", ".join(names) + src[match.end():]

    # 2. 数组条目：插在 SYSU_TOOLS 的收尾 `]` 之前
    marker = re.search(r"export const SYSU_TOOLS: SysuTool\[\] = \[", src)
    if not marker:
        raise SystemExit("registry.ts 里找不到 SYSU_TOOLS 数组")
    close = src.index("\n]", marker.end())
    src = src[: close + 1] + ENTRY + src[close + 1:]

    REGISTRY.write_text(src, encoding="utf-8")
    print("patched", REGISTRY)


patch_registry()
patch(str(LOCALES / "zh.json"), ZH, SEARCH_ZH)
patch(str(LOCALES / "en.json"), EN, SEARCH_EN)
