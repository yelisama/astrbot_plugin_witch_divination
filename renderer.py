from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from astrbot.api import logger

from .content import DivinationType

CANVAS_SIZE = (900, 1300)
FONT_CANDIDATES: list[str] = []


def _get_font_candidates() -> list[str]:
    if FONT_CANDIDATES:
        return FONT_CANDIDATES
    builtin = Path(__file__).resolve().parent / "fonts" / "1.ttf"
    extras = [
        str(builtin),
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    FONT_CANDIDATES[:] = extras
    return FONT_CANDIDATES


def render_text(div_type: DivinationType, item: dict[str, Any]) -> str:
    if div_type.renderer == "tarot":
        return "\n".join(
            [
                "今日塔罗",
                f"牌名：{item.get('card', '未名之牌')}",
                f"正逆位：{item.get('orientation', '正位')}",
                f"启示：{item.get('insight', '命运尚未写下答案。')}",
                f"建议：{item.get('advice', '慢慢来，别急。')}",
            ]
        )
    if div_type.renderer == "crystal":
        return "\n".join(
            [
                f"所见：{item.get('image', '朦胧星雾')}",
                f"微漾：{item.get('prophecy', '微光会在合适的时候出现。')}",
                f"浮影：{item.get('keyword', '等待')}",
            ]
        )
    return "\n".join(
        [
            "御神签",
            f"签位：{item.get('sign', '小吉')}",
            f"签文：{item.get('verse', '云开月渐明')}",
            f"解签：{item.get('message', '暂且静观，吉意自来。')}",
        ]
    )


def render_image(
    div_type: DivinationType,
    item: dict[str, Any],
    cache_dir: Path,
    background_path: Path | None = None,
    config: dict[str, Any] | None = None,
) -> Path | None:
    try:
        if div_type.renderer == "omikuji":
            return _render_omikuji_image(item, cache_dir, background_path)
        if div_type.renderer == "tarot":
            return _render_tarot_image(item, cache_dir, config)
    except Exception as exc:
        logger.warning("%s 图片渲染失败，回退文字: %s", div_type.id, exc)
    return None


def _cfg_int(config: dict[str, Any], key: str, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        value = int(config.get(key, default))
    except (TypeError, ValueError):
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def _render_tarot_image(item: dict[str, Any], cache_dir: Path, config: dict[str, Any] | None = None) -> Path | None:
    asset = str(item.get("asset") or "").strip()
    if not asset:
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)
    data_dir = cache_dir.parent
    asset_path = (data_dir / asset).resolve(strict=False)
    try:
        asset_path.relative_to(data_dir.resolve(strict=False))
    except ValueError:
        logger.warning("塔罗 asset 路径越界: %s", asset)
        return None
    if not asset_path.exists():
        logger.warning("塔罗 asset 不存在: %s", asset_path)
        return None

    render_cfg = config.get("tarot_render", {}) if isinstance(config, dict) else {}
    if not isinstance(render_cfg, dict):
        render_cfg = {}

    card_width = _cfg_int(render_cfg, "card_width", 900, 1, 2000)
    card_height = _cfg_int(render_cfg, "card_height", 1300, 1, 2400)
    card_x = _cfg_int(render_cfg, "card_x", -1, -2000, 2000)
    card_y = _cfg_int(render_cfg, "card_y", 0, -2000, 2000)
    panel_x = _cfg_int(render_cfg, "panel_x", 54, 0, CANVAS_SIZE[0])
    panel_y = _cfg_int(render_cfg, "panel_y", int(CANVAS_SIZE[1] * 3 / 5), 0, CANVAS_SIZE[1])
    panel_width = _cfg_int(render_cfg, "panel_width", CANVAS_SIZE[0] - panel_x * 2, 1, CANVAS_SIZE[0])
    panel_height = _cfg_int(render_cfg, "panel_height", CANVAS_SIZE[1] - panel_y - 54, 1, CANVAS_SIZE[1])
    panel_alpha = _cfg_int(render_cfg, "panel_alpha", 218, 0, 255)
    panel_radius = _cfg_int(render_cfg, "panel_radius", 30, 0, 120)
    title_size = _cfg_int(render_cfg, "title_font_size", 84, 1, 200)
    label_size = _cfg_int(render_cfg, "label_font_size", 35, 1, 120)
    body_size = _cfg_int(render_cfg, "body_font_size", 38, 1, 120)
    text_x = _cfg_int(render_cfg, "text_x", 92, 0, CANVAS_SIZE[0])
    title_y_offset = _cfg_int(render_cfg, "title_y_offset", 28, -500, 500)
    title_gap = _cfg_int(render_cfg, "title_gap", 98, 0, 500)
    line_gap = _cfg_int(render_cfg, "line_gap", 50, 1, 200)
    section_gap = _cfg_int(render_cfg, "section_gap", 30, 0, 300)
    title_stroke_width = _cfg_int(render_cfg, "title_stroke_width", 5, 0, 30)
    text_max_chars = _cfg_int(render_cfg, "text_max_chars", 19, 1, 80)

    key_source = (
        f"tarot-v5|{sorted(item.items())}|{asset_path.stat().st_mtime_ns}|"
        f"{sorted(render_cfg.items())}"
    )
    key = hashlib.sha1(key_source.encode()).hexdigest()[:16]
    output = cache_dir / f"tarot_{key}.png"
    if output.exists():
        return output

    with Image.open(asset_path) as src:
        card_image = ImageOps.contain(src.convert("RGB"), (card_width, card_height))
    image = Image.new("RGB", CANVAS_SIZE, "#efe8dc")
    paste_x = (CANVAS_SIZE[0] - card_image.width) // 2 if card_x < 0 else card_x
    image.paste(card_image, (paste_x, card_y))

    draw = ImageDraw.Draw(image)
    panel_box = (
        panel_x,
        panel_y,
        min(CANVAS_SIZE[0], panel_x + panel_width),
        min(CANVAS_SIZE[1], panel_y + panel_height),
    )
    _text_panel(draw, panel_box, alpha=panel_alpha, radius=panel_radius)

    meta_font = _load_font(title_size)
    body_font = _load_font(body_size)

    card = str(item.get("card") or "未名之牌")
    orientation = str(item.get("orientation") or "正位")
    insight = str(item.get("insight") or "命运尚未写下答案。")
    advice = str(item.get("advice") or "慢慢来，别急。")

    y = panel_y + title_y_offset
    _center_text(
        draw,
        f"{card} · {orientation}",
        y,
        meta_font,
        "#7a3454",
        stroke_width=title_stroke_width,
        stroke_fill="#ffffff",
    )
    y += title_gap
    line_x1 = max(0, panel_x + 51)
    line_x2 = min(CANVAS_SIZE[0], panel_x + panel_width - 51)
    draw.line((line_x1, y, line_x2, y), fill="#d3a15f", width=3)
    y += 24

    label_font = _load_font(label_size)
    for index, (label, text) in enumerate((("启示", insight), ("建议", advice))):
        if index:
            y += section_gap
        draw.text((text_x, y), label, font=label_font, fill="#8b3f5f")
        y += label_size + 8
        for line in _wrap_text(text, text_max_chars):
            draw.text((text_x, y), line, font=body_font, fill="#253048")
            y += line_gap
        y += 10

    image.save(output, format="PNG", optimize=True)
    return output


def _render_omikuji_image(item: dict[str, Any], cache_dir: Path, background_path: Path | None = None) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    bg_key = str(background_path) if background_path else "paper"
    key = hashlib.sha1(f"v8|{sorted(item.items())}|{bg_key}".encode()).hexdigest()[:16]
    output = cache_dir / f"omikuji_{key}.png"
    if output.exists():
        return output

    image = _make_canvas(background_path)
    draw = ImageDraw.Draw(image)
    _draw_background(draw)

    title_font = _load_font(66)
    sign_font = _load_font(100)
    verse_font = _load_font(56)
    body_font = _load_font(40)
    small_font = _load_font(30)

    sign = str(item.get("sign") or "小吉")
    verse = str(item.get("verse") or "云开月渐明")
    message = str(item.get("message") or "暂且静观，吉意自来。")

    _center_text(draw, "丛雨神社 御神签", 145, title_font, "#5b2333")
    _center_text(draw, sign, 445, sign_font, "#d94c68", stroke_width=5, stroke_fill="#fff7e8")

    message_lines = _wrap_text(message, 15)
    panel_top = 655
    panel_bottom = min(1175, 940 + max(len(message_lines), 1) * 62)
    _text_panel(draw, (115, panel_top, 785, panel_bottom), alpha=178, radius=28)
    _center_text(draw, verse, 705, verse_font, "#3d355f")
    draw.line((220, 790, 680, 790), fill="#d2a24f", width=3)
    draw.text((145, 835), "解签", font=body_font, fill="#8b3f5f")
    y = 910
    for line in message_lines:
        draw.text((145, y), line, font=body_font, fill="#2f3a56")
        y += 62

    draw.text((288, 1190), "愿今日风铃轻响，吉意自来", font=small_font, fill="#8f6b4a")
    image.save(output, format="PNG", optimize=True)
    return output


def _text_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], alpha: int = 175, radius: int = 24) -> None:
    overlay = Image.new("RGBA", CANVAS_SIZE, (255, 255, 255, 0))
    panel = ImageDraw.Draw(overlay)
    panel.rounded_rectangle(box, radius=radius, fill=(255, 255, 255, alpha), outline=(255, 255, 255, min(230, alpha + 40)), width=2)
    draw.bitmap((0, 0), overlay, fill=None)


def _make_canvas(background_path: Path | None) -> Image.Image:
    if background_path and background_path.exists():
        with Image.open(background_path) as bg:
            return ImageOps.fit(bg.convert("RGB"), CANVAS_SIZE)
    return Image.new("RGB", CANVAS_SIZE, "#efe3c8")


def _draw_sakura(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: str) -> None:
    petal = size // 2
    offsets = [(0, -petal), (petal, -4), (petal // 2, petal), (-petal // 2, petal), (-petal, -4)]
    for dx, dy in offsets:
        draw.ellipse((cx + dx - petal, cy + dy - petal, cx + dx + petal, cy + dy + petal), outline=color, width=3)
    draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=color)


def _draw_background(draw: ImageDraw.ImageDraw) -> None:
    width, height = CANVAS_SIZE
    draw.rectangle((36, 36, width - 36, height - 36), outline="#8d2c3b", width=8)
    draw.rectangle((66, 66, width - 66, height - 66), outline="#d3a15f", width=3)
    ornament_y = 108
    ornament_xs = list(range(110, width, 160))
    for index, x in enumerate(ornament_xs):
        cx = x + 28
        if index in (0, len(ornament_xs) - 1):
            _draw_sakura(draw, cx, ornament_y, 26, "#e4bc75")
        else:
            draw.ellipse((cx - 28, ornament_y - 28, cx + 28, ornament_y + 28), outline="#e4bc75", width=3)
    for y in range(150, height - 80, 130):
        draw.line((92, y, 115, y + 35), fill="#e2b86f", width=3)
        draw.line((808, y, 785, y + 35), fill="#e2b86f", width=3)


def _center_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: str,
    stroke_width: int = 0,
    stroke_fill: str | None = None,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    x = (CANVAS_SIZE[0] - (bbox[2] - bbox[0])) // 2
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)


def _wrap_text(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for part in text.splitlines() or [text]:
        lines.extend(textwrap.wrap(part, width=width, replace_whitespace=False) or [""])
    return lines[:5]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_path in _get_font_candidates():
        path = Path(font_path)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()
