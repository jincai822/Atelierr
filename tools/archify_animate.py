#!/usr/bin/env python3
"""给 archify 渲染产物注入流线流动动画。

archify 本体没有动画能力（模板只有一个 pulse 圆点），本脚本在渲染后的
HTML 里注入一段 CSS：给 a-emphasis / a-default / a-dashed 三类流线加
marching-dash 流动效果（沿箭头方向）。幂等：已注入则跳过。

用法:
    python tools/archify_animate.py <rendered.html> [更多 html...]

配合 docs/architecture/README.md 的渲染流程使用：render → animate →
check-render-output → cp 到 ~/atelierr-data/exports/。
"""

from __future__ import annotations

import sys
from pathlib import Path

STYLE_BLOCK = """
<style id="atelierr-flow-animation">
/* 流线流动动画（渲染后注入；archify 本体无动画能力） */
svg path.a-emphasis,
svg path.a-default,
svg path.a-dashed {
  stroke-dasharray: 7 6;
  animation: atelierr-flow-dash 1.1s linear infinite;
}
svg path.a-emphasis {
  stroke-dasharray: 10 7;
  animation-duration: 0.9s;
}
@keyframes atelierr-flow-dash {
  to { stroke-dashoffset: -26; }
}
@media (prefers-reduced-motion: reduce) {
  svg path.a-emphasis,
  svg path.a-default,
  svg path.a-dashed { animation: none; }
}
</style>
"""

MARKER = 'id="atelierr-flow-animation"'


def animate(html_path: Path) -> bool:
    """注入动画 CSS；已注入返回 False。"""
    text = html_path.read_text(encoding="utf-8")
    if MARKER in text:
        return False
    if "</head>" not in text:
        raise ValueError(f"{html_path}: 找不到 </head>，不是预期的渲染产物")
    html_path.write_text(
        text.replace("</head>", STYLE_BLOCK + "\n</head>", 1), encoding="utf-8"
    )
    return True


def main(argv: list) -> int:
    """逐个处理命令行给出的 HTML 文件。返回 0 全部成功。"""
    if not argv:
        print(__doc__)
        return 1
    for name in argv:
        path = Path(name)
        changed = animate(path)
        print(f"{'已注入动画' if changed else '已有动画（跳过）'}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
