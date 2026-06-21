from __future__ import annotations

import hashlib
import json
import textwrap
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from astrbot.api import logger

from .content import DivinationType

CANVAS_SIZE = (900, 1300)
FONT_CANDIDATES: list[str] = []


def _cfg_section(config: Any, key: str) -> dict[str, Any]:
    try:
        value = config.get(key, {}) if config is not None else {}
    except AttributeError:
        return {}
    return value if isinstance(value, dict) else {}


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
            return _render_omikuji_image(item, cache_dir, background_path, config)
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


def _cfg_str(config: dict[str, Any], key: str, default: str) -> str:
    value = config.get(key, default)
    return str(value if value is not None else default)


def _cfg_box(config: dict[str, Any], prefix: str, default: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x, y, width, height = default
    return (
        _cfg_int(config, f"{prefix}_x", x, 0, CANVAS_SIZE[0]),
        _cfg_int(config, f"{prefix}_y", y, 0, CANVAS_SIZE[1]),
        _cfg_int(config, f"{prefix}_width", width, 1, CANVAS_SIZE[0]),
        _cfg_int(config, f"{prefix}_height", height, 1, CANVAS_SIZE[1]),
    )


def _box_bounds(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x, y, width, height = box
    return (x, y, min(CANVAS_SIZE[0], x + width), min(CANVAS_SIZE[1], y + height))


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
    if not asset_path.exists() and asset_path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        candidates = [
            asset_path.with_suffix(".jpg"),
            asset_path.with_suffix(".png"),
            asset_path.with_suffix(".jpeg"),
        ]
        asset_path = next((path for path in candidates if path.exists()), asset_path)
    if not asset_path.exists():
        logger.warning("塔罗 asset 不存在: %s", asset_path)
        return None

    render_cfg = _cfg_section(config, "tarot_render")

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


def _render_omikuji_image(
    item: dict[str, Any],
    cache_dir: Path,
    background_path: Path | None = None,
    config: dict[str, Any] | None = None,
) -> Path:
    render_cfg = {}
    if config is not None:
        render_cfg = _cfg_section(config, "omikuji_render")
    template = _cfg_str(render_cfg, "template", "illustration")
    if template == "witch_paper":
        return _render_omikuji_witch_paper_image(item, cache_dir, render_cfg)
    return _render_omikuji_illustration_image(item, cache_dir, background_path)


def _render_omikuji_illustration_image(item: dict[str, Any], cache_dir: Path, background_path: Path | None = None) -> Path:
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


def _render_omikuji_witch_paper_image(item: dict[str, Any], cache_dir: Path, config: dict[str, Any]) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    template = _cfg_str(config, "template_path", "assets/layouts/omikuji_paper_b_v1.png")
    font_signature = _font_signature()
    key_source = f"witch-paper-v1|{sorted(item.items())}|{json.dumps(config, sort_keys=True, ensure_ascii=False)}|{font_signature}"
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:16]
    output = cache_dir / f"omikuji_witch_paper_{key}.png"
    if output.exists():
        return output

    data_dir = cache_dir.parent
    plugin_dir = Path(__file__).resolve().parent
    template_path = data_dir / template
    if not template_path.exists():
        template_path = plugin_dir / "templates" / template
    if template_path.exists():
        image = ImageOps.fit(Image.open(template_path).convert("RGBA"), CANVAS_SIZE)
    else:
        logger.warning("御神签签纸模板不存在，使用内置底色兜底: %s", template)
        image = Image.new("RGBA", CANVAS_SIZE, "#f7e7ee")

    draw = ImageDraw.Draw(image)
    title_font = _load_display_font(_cfg_int(config, "title_font_size", 34, 1, 160))
    sign_font = _load_display_font(_cfg_int(config, "sign_font_size", 118, 1, 220))
    verse_font = _load_body_font(_cfg_int(config, "verse_font_size", 34, 1, 120), _cfg_int(config, "verse_font_weight", 600, 100, 900))
    body_font = _load_body_font(_cfg_int(config, "body_font_size", 30, 1, 120), _cfg_int(config, "body_font_weight", 500, 100, 900))
    footer_font = _load_body_font(_cfg_int(config, "footer_font_size", 21, 1, 80), _cfg_int(config, "footer_font_weight", 500, 100, 900))

    title = _cfg_str(config, "title_text", "魔女御神签")
    footer = _cfg_str(config, "footer_text", "愿今日微光照见答案")
    sign = str(item.get("sign") or "小吉")
    verse = str(item.get("verse") or "云开月渐明")
    message = str(item.get("message") or "暂且静观，吉意自来。")

    title_box = _cfg_box(config, "title", (300, 58, 300, 58))
    sign_box = _cfg_box(config, "sign", (220, 275, 460, 260))
    verse_box = _cfg_box(config, "verse", (235, 714, 430, 56))
    body_box = _cfg_box(config, "body", (145, 850, 610, 265))
    footer_box = _cfg_box(config, "footer", (240, 1198, 420, 50))

    _center_text_in_box(
        draw,
        title,
        _box_bounds(title_box),
        title_font,
        _cfg_str(config, "title_color", "#7a4b72"),
        stroke_width=_cfg_int(config, "title_stroke_width", 2, 0, 20),
        stroke_fill=_cfg_str(config, "title_stroke_fill", "#fff8fb"),
    )
    _center_text_in_box(
        draw,
        sign,
        _box_bounds(sign_box),
        sign_font,
        _cfg_str(config, "sign_color", "#d35a82"),
        stroke_width=_cfg_int(config, "sign_stroke_width", 4, 0, 30),
        stroke_fill=_cfg_str(config, "sign_stroke_fill", "#fff4f0"),
    )
    _center_text_in_box(draw, verse, _box_bounds(verse_box), verse_font, _cfg_str(config, "verse_color", "#6b5270"))
    _draw_wrapped_text_in_box(
        draw,
        message,
        _box_bounds(body_box),
        body_font,
        _cfg_str(config, "body_color", "#4d4155"),
        line_gap=_cfg_int(config, "body_line_gap", 48, 1, 160),
        max_lines=_cfg_int(config, "body_max_lines", 5, 1, 10),
        horizontal_padding=_cfg_int(config, "body_padding_x", 10, 0, 160),
        align=_cfg_str(config, "body_align", "center"),
    )
    _center_text_in_box(draw, footer, _box_bounds(footer_box), footer_font, _cfg_str(config, "footer_color", "#93698a"))

    image.convert("RGB").save(output, format="PNG", optimize=True)
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


def _center_text_in_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: str,
    stroke_width: int = 0,
    stroke_fill: str | None = None,
) -> None:
    left, top, right, bottom = box
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    x = left + (right - left - width) / 2 - bbox[0]
    y = top + (bottom - top - height) / 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)


def _wrap_text_by_pixel(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        current = ""
        for char in paragraph:
            trial = current + char
            if draw.textlength(trial, font=font) <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = char
        if current:
            lines.append(current)
    return lines or [""]


def _draw_wrapped_text_in_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: str,
    line_gap: int,
    max_lines: int,
    horizontal_padding: int = 0,
    align: str = "center",
) -> None:
    left, top, right, bottom = box
    max_width = max(1, right - left - horizontal_padding * 2)
    lines = _wrap_text_by_pixel(draw, text, font, max_width)[:max_lines]
    if not lines:
        return
    heights = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        heights.append(bbox[3] - bbox[1])
    block_height = (len(lines) - 1) * line_gap + max(heights)
    y = top + (bottom - top - block_height) / 2
    for index, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        width = bbox[2] - bbox[0]
        if align == "left":
            x = left + horizontal_padding - bbox[0]
        else:
            x = left + (right - left - width) / 2 - bbox[0]
        draw.text((x, y + index * line_gap - bbox[1]), line, font=font, fill=fill)


def _wrap_text(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for part in text.splitlines() or [text]:
        lines.extend(textwrap.wrap(part, width=width, replace_whitespace=False) or [""])
    return lines[:5]


def _font_signature() -> str:
    paths = [
        Path(__file__).resolve().parent / "fonts" / "1.ttf",
        Path(__file__).resolve().parent / "fonts" / "NotoSansSC-VF.ttf",
    ]
    return "|".join(f"{path.name}:{path.stat().st_mtime_ns}" for path in paths if path.exists())


def _load_display_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    builtin = Path(__file__).resolve().parent / "fonts" / "1.ttf"
    if builtin.exists():
        return ImageFont.truetype(str(builtin), size=size)
    return _load_font(size)


def _load_body_font(size: int, weight: int = 500) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    builtin = Path(__file__).resolve().parent / "fonts" / "NotoSansSC-VF.ttf"
    if builtin.exists():
        font = ImageFont.truetype(str(builtin), size=size)
        try:
            font.set_variation_by_axes([weight])
        except Exception:
            pass
        return font
    return _load_font(size)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_path in _get_font_candidates():
        path = Path(font_path)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()
