"""在右半对局参考图上叠加控制点。

用法（坐标均为右半副本的原图像素）：
    ./.venv/Scripts/python.exe scripts/overlay_control_points.py 1100,300,P1 1200,400,P2
不传坐标时绘制下方默认控制点。默认输出到 gui_ref/对局ui参考_右半_控制点.png。
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "gui_ref" / "对局ui参考_右半.png"
OUTPUT = ROOT / "gui_ref" / "对局ui参考_右半_控制点.png"
CARD_BACK = ROOT / "assets" / "cardbacks" / "月明风清.png"
# 以右上角为原点，水平向左为 w+、竖直向下为 h+。
CONTROL_POINTS = (
    (255, 440, "TL1"),  # 原始量距点；实际绘制使用垂线校正后的 TL1
    (188, 292, "TR1"),
    (103, 244, "TR2"),
    (57, 220, "TR3"),
)
REFERENCE_LINES = ((1, 25), (2, 40), (3, 45))  # 水平向左 0°，顺时针为正
E_POINT = (128, 643, "E")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("points", nargs="*", help="x,y,标签；标签可省略")
    args = parser.parse_args()

    image = Image.open(SOURCE).convert("RGBA")
    card_back = Image.open(CARD_BACK).convert("RGBA")
    original_card_size = card_back.size
    alpha_bbox = card_back.getchannel("A").getbbox()
    if alpha_bbox is not None:
        card_back = card_back.crop((alpha_bbox[0], 0, alpha_bbox[2], card_back.height))
    cropped_card_size = card_back.size
    tl1 = CONTROL_POINTS[0]
    tr1 = CONTROL_POINTS[1]
    card_width = math.hypot(tr1[0] - tl1[0], tr1[1] - tl1[1])
    scale = card_width / min(card_back.size)
    card_size = (round(card_back.width * scale), round(card_back.height * scale))
    card_back = card_back.resize(card_size, Image.Resampling.LANCZOS)
    print(f"卡背原始尺寸={original_card_size}，去透明两侧={cropped_card_size}，"
          f"目标宽度={card_width:.3f}，缩放后={card_size}")
    draw = ImageDraw.Draw(image)
    for point_index, angle in REFERENCE_LINES:
        w, h, _label = CONTROL_POINTS[point_index]
        cx, cy = image.width - w, h
        radians = math.radians(angle)
        dx = -math.cos(radians) * card_width / 2
        dy = -math.sin(radians) * card_width / 2
        draw.line((cx - dx, cy - dy, cx + dx, cy + dy), fill="#40ff60", width=3)
    control_points = list(CONTROL_POINTS[1:])
    groups = []
    for point_index, angle in REFERENCE_LINES:
        w, h, _label = CONTROL_POINTS[point_index]
        radians = math.radians(angle)
        tl_w = w + card_width * math.sin(radians)
        tl_h = h + card_width * math.cos(radians)
        label = f"TL{point_index}"
        tl = (tl_w, tl_h, label)
        control_points.append(tl)
        groups.append((tl, CONTROL_POINTS[point_index], point_index))
        print(f"{label}: w={tl_w:.3f}, h={tl_h:.3f}")
    for tl, tr, index in groups:
        top_w, top_h = tr[0] - tl[0], tr[1] - tl[1]
        top_length = math.hypot(top_w, top_h)
        down_w = top_h / top_length * card_back.height
        down_h = -top_w / top_length * card_back.height
        bl = (tl[0] + down_w, tl[1] + down_h, f"BL{index}")
        br = (tr[0] + down_w, tr[1] + down_h, f"BR{index}")
        center = ((tl[0] + tr[0] + down_w) / 2,
                  (tl[1] + tr[1] + down_h) / 2, f"C{index}")
        vertices = [(image.width - point[0], point[1]) for point in (tl, tr, br, bl)]
        color = ("#409cff", "#ffd840", "#ff4040")[index - 1]
        draw.line(vertices + [vertices[0]], fill=color, width=3, joint="curve")
        control_points.extend((bl, br, center))
        for point in (bl, br, center):
            print(f"{point[2]}: w={point[0]:.3f}, h={point[1]:.3f}")
    mirrored_points = [
        (w, 2 * E_POINT[1] - h, f"{label[:-1]}{int(label[-1]) + 3}")
        for w, h, label in control_points]
    control_points.extend(mirrored_points)
    point_map = {point[2]: point for point in control_points}
    for point_index, angle in REFERENCE_LINES:
        w, h, _label = point_map[f"TR{point_index + 3}"]
        cx, cy = image.width - w, h
        radians = math.radians(-angle)
        dx = -math.cos(radians) * card_width / 2
        dy = -math.sin(radians) * card_width / 2
        draw.line((cx - dx, cy - dy, cx + dx, cy + dy), fill="#40ff60", width=3)
    for _tl, _tr, index in groups:
        mirrored = [point_map[f"{prefix}{index + 3}"]
                    for prefix in ("TL", "TR", "BR", "BL")]
        vertices = [(image.width - point[0], point[1]) for point in mirrored]
        color = ("#409cff", "#ffd840", "#ff4040")[index - 1]
        draw.line(vertices + [vertices[0]], fill=color, width=3, joint="curve")
    control_points.append(E_POINT)
    print(f"E: w={E_POINT[0]}, h={E_POINT[1]}；已镜像 15 个控制点至第 4-6 组")
    font_path = ROOT / "assets" / "fonts" / "方正北魏楷书.ttf"
    font = ImageFont.truetype(str(font_path), 28) if font_path.is_file() else ImageFont.load_default()
    specs = list(args.points)
    if not specs:
        for w, h, label in control_points:
            x, y = image.width - w, h
            if label.startswith("C"):
                x, y = round(x), round(y)
            specs.append(f"{x},{y},{label}")
    for index, spec in enumerate(specs, 1):
        parts = spec.split(",", 2)
        if len(parts) < 2:
            parser.error(f"控制点格式错误：{spec!r}")
        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError:
            parser.error(f"控制点坐标必须为数字：{spec!r}")
        label = parts[2] if len(parts) == 3 else str(index)
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), outline="#ff4040", width=3)
        draw.line((x - 12, y, x + 12, y), fill="#ff4040", width=2)
        draw.line((x, y - 12, x, y + 12), fill="#ff4040", width=2)
        draw.text((x + 12, y - 32), label, font=font, fill="white",
                  stroke_width=2, stroke_fill="black")
    image.save(OUTPUT)
    print(f"已叠加 {len(specs)} 个控制点：{OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
