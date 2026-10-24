"""生成工具栏图标与主题图标（构建期用，运行期不依赖 Pillow）。

图元描述 + 16 倍超采样降采样；按 主题×状态×8 档 DPI 预渲染，底色烤进像素，
输出 assets/icons/<name>-<size>-<theme>-<state>.png。
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "assets", "icons")

SCALES = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0)
BASE = 20

THEMES = {
    "light": {
        "normal": ("#FFFFFF", "#000000"),
        "hover": ("#E9EBEF", "#000000"),
        "accent": ("#0067C0", "#FFFFFF"),
        "accent_hover": ("#005BA8", "#FFFFFF"),
    },
    "dark": {
        "normal": ("#2B2B2B", "#FFFFFF"),
        "hover": ("#363636", "#FFFFFF"),
        "accent": ("#4CC2FF", "#0A0A0A"),
        "accent_hover": ("#6FCEFF", "#0A0A0A"),
    },
}

ACCENT_ICONS = {"eject"}
PLAIN_STATES = ("normal", "hover")
SUPERSAMPLE = 16

#: 磁盘图标（“显示全部磁盘”按钮）的比例，见 :func:`_disk`
DISK_LEFT, DISK_TOP, DISK_RIGHT, DISK_BOTTOM = 0.110, 0.160, 0.890, 0.840
DISK_STROKE, DISK_RADIUS = 0.100, 0.170
DISK_SLOT = (0.255, 0.520, 0.500, 0.060)   # 插入槽：x0, x1, y, 线宽
DISK_LED_X, DISK_LED_R = 0.680, 0.060      # 指示灯：圆心 x（垂直居中）, 半径


def _gear(draw, box, ink, background):
    x0, y0, x1, y1 = box
    size = x1 - x0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    root, tip = size * 0.270, size * 0.387
    points = []
    for index in range(8):
        centre = 2.0 * math.pi * index / 8
        for offset, radius in ((-0.24, root), (-0.15, tip), (0.15, tip), (0.24, root)):
            angle = centre + offset
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    draw.polygon(points, fill=ink)
    hole = size * 0.122
    draw.ellipse((cx - hole, cy - hole, cx + hole, cy + hole), fill=background)


def _refresh(draw, box, ink, _background):
    """按参考图实测比例重画：环径 0.80、线宽 0.10、尾巴是"横+竖"折角，尖端朝下。

    参考图量得（505×463 归一化）：环外径 ≈0.83、线宽 ≈0.10；
    横线 y≈0.37 从 x≈0.57 到 0.84；竖线 x≈0.84 从 y≈0.15 到 0.44。
    """
    x0, y0, x1, y1 = box
    size = x1 - x0
    cx, cy = (x0 + x1) / 2.0 - size * 0.02, (y0 + y1) / 2.0
    radius = size * 0.315
    width = max(1.4, size * 0.100)
    draw.arc((cx - radius, cy - radius, cx + radius, cy + radius),
             start=40, end=320, fill=ink, width=int(round(width)))
    half = width / 2.0
    bar_y = y0 + size * 0.355
    tail_x = x0 + size * 0.845
    start_x = x0 + size * 0.560
    top_y = y0 + size * 0.150
    bottom_y = y0 + size * 0.455
    draw.line((start_x, bar_y, tail_x, bar_y), fill=ink, width=int(round(width)))
    draw.line((tail_x, top_y, tail_x, bottom_y), fill=ink, width=int(round(width)))
    for px_, py_ in ((start_x, bar_y), (tail_x, bar_y), (tail_x, top_y),
                     (tail_x, bottom_y)):
        draw.ellipse((px_ - half, py_ - half, px_ + half, py_ + half), fill=ink)


def _disk(draw, box, ink, _background):
    """简易磁盘：圆角机身 + 插入槽 + 指示灯。

    全部比例写成常量，一次只调一档：机身墨迹 0.78×0.68、线宽 0.10（与刷新同一档）、
    圆角 0.17；机身中线上一道插入槽（0.255→0.520）和右侧指示灯（直径 0.12）。
    按 35px（175% DPI 下的实际按钮图标）算：机身 27×24 px，墨迹 29×25，
    与齿轮 29×27、刷新 27×26 同级（实测像素数 450 vs 424，见提交说明）。
    """
    x0, y0, x1, y1 = box
    size = x1 - x0
    stroke = max(1, int(round(size * DISK_STROKE)))
    body = (x0 + size * DISK_LEFT, y0 + size * DISK_TOP,
            x0 + size * DISK_RIGHT, y0 + size * DISK_BOTTOM)
    draw.rounded_rectangle(body, radius=int(round(size * DISK_RADIUS)),
                           outline=ink, width=stroke)
    slot_x0, slot_x1, slot_y, slot_w = DISK_SLOT
    mid_y = y0 + size * slot_y
    draw.line((x0 + size * slot_x0, mid_y, x0 + size * slot_x1, mid_y),
              fill=ink, width=max(1, int(round(size * slot_w))))
    led_r = size * DISK_LED_R
    led_cx = x0 + size * DISK_LED_X
    draw.ellipse((led_cx - led_r, mid_y - led_r, led_cx + led_r, mid_y + led_r),
                 fill=ink)


def _help(draw, box, ink, _background):
    x0, y0, x1, y1 = box
    size = x1 - x0
    cx = (x0 + x1) / 2.0
    width = max(1.4, size * 0.125)
    hook_r = size * 0.195
    hook_cy = y0 + size * 0.315
    draw.arc((cx - hook_r, hook_cy - hook_r, cx + hook_r, hook_cy + hook_r),
             start=195, end=350, fill=ink, width=int(round(width)))
    end_angle = math.radians(350)
    ex = cx + hook_r * math.cos(end_angle)
    ey = hook_cy + hook_r * math.sin(end_angle)
    neck = (cx, y0 + size * 0.475)
    stem_bottom = (cx, y0 + size * 0.615)
    draw.line([(ex, ey), neck], fill=ink, width=int(round(width)))
    draw.line([neck, stem_bottom], fill=ink, width=int(round(width)))
    for point in ((ex, ey), neck, stem_bottom):
        draw.ellipse((point[0] - width / 2, point[1] - width / 2,
                      point[0] + width / 2, point[1] + width / 2), fill=ink)
    dot_r = size * 0.080
    dot_y = y0 + size * 0.805
    draw.ellipse((cx - dot_r, dot_y - dot_r, cx + dot_r, dot_y + dot_r), fill=ink)


def _eject(draw, box, ink, _background=None, app_icon=None):
    x0, y0, x1, y1 = box
    size = x1 - x0
    apex = (x0 + size * 0.50, y0 + size * 0.125)
    left = (x0 + size * 0.155, y0 + size * 0.500)
    right = (x0 + size * 0.845, y0 + size * 0.500)
    cx = (apex[0] + left[0] + right[0]) / 3.0
    cy = (apex[1] + left[1] + right[1]) / 3.0
    # 只填多边形：不再在底角补圆，免得出现两个"肿瘤"般的凸起
    draw.polygon((apex, left, right), fill=ink)
    bar = (x0 + size * 0.155, y0 + size * 0.675,
           x0 + size * 0.845, y0 + size * 0.855)
    draw.rounded_rectangle(bar, radius=int(round(size * 0.055)), fill=ink)


def _monitor(draw, box, ink, _background):
    x0, y0, x1, y1 = box
    size = x1 - x0
    width = max(1.4, size * 0.115)
    left, right = x0 + size * 0.075, x1 - size * 0.075
    top, bottom = y0 + size * 0.175, y1 - size * 0.355
    draw.rectangle((left, top, right, bottom), outline=ink, width=int(round(width)))
    draw.line((x0 + size * 0.315, y1 - size * 0.185, x1 - size * 0.315, y1 - size * 0.185),
              fill=ink, width=int(round(width)))


def _sun(draw, box, ink, _background):
    x0, y0, x1, y1 = box
    size = x1 - x0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    disc = size * 0.270
    draw.ellipse((cx - disc, cy - disc, cx + disc, cy + disc), fill=ink)
    dot = size * 0.068
    for index in range(8):
        angle = math.radians(index * 45)
        dx = cx + size * 0.430 * math.cos(angle)
        dy = cy + size * 0.430 * math.sin(angle)
        draw.ellipse((dx - dot, dy - dot, dx + dot, dy + dot), fill=ink)


def _moon(draw, box, ink, _background):
    x0, y0, x1, y1 = box
    size = x1 - x0
    cx, cy = (x0 + x1) / 2.0 + size * 0.055, (y0 + y1) / 2.0
    r_out, r_in, offset = size * 0.425, size * 0.360, size * 0.215
    a = (r_out ** 2 - r_in ** 2 + offset ** 2) / (2.0 * offset)
    chord = math.sqrt(max(0.0, r_out ** 2 - a ** 2))
    theta = math.atan2(chord, a)
    phi = math.atan2(chord, a - offset)
    points = []
    for index in range(49):
        angle = theta + (2 * math.pi - 2 * theta) * index / 48
        points.append((cx + r_out * math.cos(angle), cy + r_out * math.sin(angle)))
    for index in range(49):
        angle = (2 * math.pi - phi) - (2 * math.pi - 2 * phi) * index / 48
        points.append((cx + offset + r_in * math.cos(angle), cy + r_in * math.sin(angle)))
    draw.polygon(points, fill=ink)


PAINTERS = {
    "gear": _gear, "refresh": _refresh, "help": _help, "eject": _eject,
    "monitor": _monitor, "sun": _sun, "moon": _moon, "disk": _disk,
}


def render(name: str, size: int, background: str, ink: str) -> Image.Image:
    big = size * SUPERSAMPLE
    canvas = Image.new("RGB", (big, big), background)
    draw = ImageDraw.Draw(canvas)
    PAINTERS[name](draw, (0, 0, big, big), ink, background)
    return canvas.resize((size, size), Image.LANCZOS)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    count = 0
    for name in PAINTERS:
        for scale in SCALES:
            size = int(round(BASE * scale))
            for theme_name, states in THEMES.items():
                for state, (background, ink) in states.items():
                    accent = state.startswith("accent")
                    if accent and name not in ACCENT_ICONS:
                        continue
                    if not accent and state not in PLAIN_STATES:
                        continue
                    image = render(name, size, background, ink)
                    image.save(os.path.join(OUT, f"{name}-{size}-{theme_name}-{state}.png"))
                    count += 1
    print(f"generated {count} icons in {OUT}")


if __name__ == "__main__":
    main()
