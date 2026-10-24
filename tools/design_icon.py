"""生成应用图标（开发工具，不参与打包）。

设计：蓝色圆角方片 + 白色「弹出」字形（上方三角 + 下方胶囊条）。
用图元画、每个尺寸单独渲染（不做"一张大图缩到 16px"），所以小尺寸下
三角与胶囊条的线宽不会糊掉。

产物：

* ``assets/app.ico`` —— 多帧 ICO（16/20/24/28/32/40/48/56/64/96/128/256），
  打包进 EXE，并用 Win32 ``LoadImageW`` 按窗口 DPI 取对应帧；
* ``assets/app.png`` —— 256px，给 README / ``iconphoto`` 用；
* ``build/icon_sheet.png`` —— 对比图（浅底 + 深底 + 模拟标题栏），用于人工确认。

用法::

    python tools/design_icon.py
"""

from __future__ import annotations

import io
import os
import struct
from pathlib import Path
from typing import List, Tuple

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
BUILD = ROOT / "build" / "icon"

# 用户定稿的强调色（与 theme.py 的 accent 同源）
ACCENT = (139, 212, 80)      # 浅草绿（亮绿）
ACCENT_DARK = (78, 154, 31)  # 深一档的草绿
WHITE = (255, 255, 255)

SIZES = (16, 20, 24, 28, 32, 40, 48, 56, 64, 96, 128, 256)
# 渲染倍数：先按 4 倍画，再缩到目标尺寸，得到抗锯齿边缘
SUPERSAMPLE = 4


def _round_rect(draw: ImageDraw.ImageDraw, box, radius: float, fill) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def _vertical_gradient(size: int, top: Tuple[int, int, int],
                       bottom: Tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        img.putpixel((0, y), tuple(int(round(top[i] + (bottom[i] - top[i]) * t))
                                   for i in range(3)))
    return img.resize((size, size), Image.Resampling.NEAREST)


def render(size: int) -> Image.Image:
    """按目标像素尺寸渲染一帧图标。``size`` 决定细节粗细，不是放大。"""
    s = size
    big = s * SUPERSAMPLE
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))

    # 圆角方片：遮罩 + 渐变
    radius = big * 0.22
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1),
                                           radius=radius, fill=255)
    gradient = _vertical_gradient(big, ACCENT, ACCENT_DARK).convert("RGBA")
    canvas.paste(gradient, (0, 0), mask)

    draw = ImageDraw.Draw(canvas)

    # 小尺寸加粗一点，避免缩到 16px 后"细得看不见"
    if s <= 20:
        tri_half = big * 0.315
        tri_top = big * 0.245
        tri_bottom = big * 0.575
        bar_half = big * 0.315
        bar_top = big * 0.655
        bar_bottom = big * 0.755
    elif s <= 32:
        tri_half = big * 0.305
        tri_top = big * 0.250
        tri_bottom = big * 0.565
        bar_half = big * 0.305
        bar_top = big * 0.650
        bar_bottom = big * 0.742
    else:
        tri_half = big * 0.295
        tri_top = big * 0.252
        tri_bottom = big * 0.556
        bar_half = big * 0.295
        bar_top = big * 0.642
        bar_bottom = big * 0.730

    cx = big / 2.0
    # 三角（视觉重心在上半部分，整体略上移补偿）
    draw.polygon(
        [(cx, tri_top), (cx + tri_half, tri_bottom), (cx - tri_half, tri_bottom)],
        fill=WHITE,
    )
    # 胶囊条
    bar_radius = (bar_bottom - bar_top) / 2.0
    _round_rect(draw, (cx - bar_half, bar_top, cx + bar_half, bar_bottom),
                bar_radius, WHITE)

    return canvas.resize((s, s), Image.Resampling.LANCZOS)


def _ico_bytes(frames: List[Tuple[int, bytes]]) -> bytes:
    """把若干 ``(边长, PNG 字节)`` 组装成 ICO。

    Vista 之后 ICO 允许直接放 PNG 帧；这样每一帧都能由 :func:`render`
    单独渲染，而不是让系统把一张大图缩小。
    """
    count = len(frames)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    directory = b""
    payload = b""
    for size, png in frames:
        directory += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0, 0, 1, 32, len(png), offset,
        )
        offset += len(png)
        payload += png
    return header + directory + payload


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)

    frames: List[Tuple[int, bytes]] = []
    for size in SIZES:
        img = render(size)
        img.save(BUILD / f"icon_{size}.png")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        frames.append((size, buf.getvalue()))

    (ASSETS / "app.ico").write_bytes(_ico_bytes(frames))
    render(256).save(ASSETS / "app.png")

    # 对照图：浅底 / 深底 / 模拟标题栏
    sheet_w = 900
    sheet_h = 300
    sheet = Image.new("RGB", (sheet_w, sheet_h), (243, 244, 246))
    draw = ImageDraw.Draw(sheet)
    draw.rectangle((0, 150, sheet_w, sheet_h), fill=(32, 32, 32))
    x = 20
    for size in SIZES:
        img = render(size)
        y = 60 - size // 2 + 20
        sheet.paste(img, (x, y), img)
        y2 = 220 - size // 2
        sheet.paste(img, (x, y2), img)
        x += max(size, 24) + 20
    # 模拟标题栏：16px 图标 + 标题
    bar = Image.new("RGB", (320, 32), (243, 243, 243))
    bar.paste(render(16), (12, 8), render(16))
    draw_bar = ImageDraw.Draw(bar)
    draw_bar.text((36, 10), "QuickPortableDiskTool", fill=(0, 0, 0))
    sheet.paste(bar, (20, 270))
    sheet.save(BUILD / "icon_sheet.png")
    print(f"wrote {ASSETS / 'app.ico'} ({os.path.getsize(ASSETS / 'app.ico')} bytes)")
    print(f"wrote {ASSETS / 'app.png'}")
    print(f"wrote {BUILD / 'icon_sheet.png'}")


if __name__ == "__main__":
    main()
