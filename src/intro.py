"""Generate intro slide images with logos and Arabic title."""

from __future__ import annotations

from pathlib import Path

import freetype
import uharfbuzz as hb
from PIL import Image, ImageDraw, ImageFont


_ARABIC_ORDINALS: dict[int, str] = {
    1: "الأول",
    2: "الثاني",
    3: "الثالث",
    4: "الرابع",
    5: "الخامس",
    6: "السادس",
    7: "السابع",
    8: "الثامن",
    9: "التاسع",
    10: "العاشر",
}


def lesson_subtitle(number: int) -> str:
    ordinal = _ARABIC_ORDINALS.get(number, str(number))
    return f"الدرس {ordinal}"


def _resolve_path(project_root: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute():
        return path
    return project_root / path


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))


def _rgba(color: tuple[int, int, int], alpha: int) -> tuple[int, int, int, int]:
    return (*color, alpha)


def _remove_black_background(image: Image.Image, threshold: int = 55) -> Image.Image:
    """Make dark pixels transparent with soft edges."""
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    soften_range = 40

    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            peak = max(r, g, b)
            if peak <= threshold:
                pixels[x, y] = (0, 0, 0, 0)
            elif peak <= threshold + soften_range:
                fade = (peak - threshold) / soften_range
                pixels[x, y] = (r, g, b, int(a * fade))

    return rgba


def _clean_alpha_edges(image: Image.Image) -> Image.Image:
    """Zero RGB where alpha is negligible and premultiply for FFmpeg overlays."""
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            if a < 20:
                pixels[x, y] = (0, 0, 0, 0)
            else:
                pixels[x, y] = (r * a // 255, g * a // 255, b * a // 255, a)
    return rgba


def _load_font(font_path: Path, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if font_path.exists():
        return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default()


def _fit_image_width(image: Image.Image, target_width: int) -> Image.Image:
    if image.width <= target_width:
        return image
    ratio = target_width / image.width
    new_size = (target_width, max(1, int(image.height * ratio)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _shape_arabic(text: str, font_path: Path, font_size: int) -> tuple[hb.Face, hb.Font, hb.Buffer]:
    font_data = font_path.read_bytes()
    face = hb.Face(font_data)
    font = hb.Font(face)
    font.scale = (font_size * 64, font_size * 64)

    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.direction = "rtl"
    buffer.language = "ar"
    buffer.script = "Arab"
    hb.shape(font, buffer)
    return face, font, buffer


def _measure_arabic_text(text: str, font_path: Path, font_size: int) -> float:
    _, _, buffer = _shape_arabic(text, font_path, font_size)
    return sum(position.x_advance for position in buffer.glyph_positions) / 64


def _wrap_text_by_width(
    text: str,
    font_path: Path,
    font_size: int,
    max_width: int,
) -> list[str]:
    words = text.split()
    if not words:
        return [text]

    def measure(value: str) -> float:
        return _measure_arabic_text(value, font_path, font_size)

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if measure(candidate) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_arabic_text(
    canvas: Image.Image,
    text: str,
    *,
    font_path: Path,
    font_size: int,
    color: tuple[int, int, int],
    center_x: int,
    center_y: int,
) -> None:
    _, _, buffer = _shape_arabic(text, font_path, font_size)

    ft_face = freetype.Face(str(font_path))
    ft_face.set_char_size(font_size * 64)

    total_width = sum(position.x_advance for position in buffer.glyph_positions) / 64
    cursor_x = center_x - total_width / 2
    baseline_y = center_y

    for info, position in zip(buffer.glyph_infos, buffer.glyph_positions):
        cursor_x += position.x_offset / 64
        ft_face.load_glyph(
            info.codepoint,
            freetype.FT_LOAD_DEFAULT | freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL,
        )
        bitmap = ft_face.glyph.bitmap
        if bitmap.width == 0 or bitmap.rows == 0:
            cursor_x += position.x_advance / 64
            continue

        glyph_image = Image.frombytes(
            "L",
            (bitmap.width, bitmap.rows),
            bytes(bitmap.buffer),
            "raw",
            "L",
            bitmap.pitch,
        )
        paste_x = int(cursor_x + ft_face.glyph.bitmap_left)
        paste_y = int(baseline_y - ft_face.glyph.bitmap_top - (position.y_offset / 64))
        color_layer = Image.new("RGBA", glyph_image.size, (*color, 0))
        color_layer.putalpha(glyph_image)
        canvas.paste(color_layer, (paste_x, paste_y), color_layer)
        cursor_x += position.x_advance / 64


def _paste_centered(base: Image.Image, overlay: Image.Image, top: int) -> None:
    x = (base.width - overlay.width) // 2
    base.paste(overlay, (x, top), overlay)


def _draw_diamond(
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    size: int,
    fill: tuple[int, int, int, int],
) -> None:
    cx, cy = center
    points = [(cx, cy - size), (cx + size, cy), (cx, cy + size), (cx - size, cy)]
    draw.polygon(points, fill=fill)


def _draw_horizontal_rule(
    draw: ImageDraw.ImageDraw,
    y: int,
    left: int,
    right: int,
    color: tuple[int, int, int, int],
    *,
    diamond_size: int = 7,
    diamond_color: tuple[int, int, int, int] | None = None,
) -> None:
    draw.line([(left, y), (right, y)], fill=color, width=1)
    accent = diamond_color or color
    _draw_diamond(draw, (left, y), diamond_size, accent)
    _draw_diamond(draw, (right, y), diamond_size, accent)


def _draw_pill(
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    width: int,
    height: int,
    fill: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    cx, cy = center
    box = [cx - width // 2, cy - height // 2, cx + width // 2, cy + height // 2]
    draw.rounded_rectangle(box, radius=height // 2, fill=fill)
    return tuple(box)  # type: ignore[return-value]


def prepare_logo_with_transparency(logo_path: Path) -> Image.Image:
    logo = Image.open(logo_path)
    if logo.mode == "RGBA" and logo.getextrema()[3][0] > 0:
        return _remove_black_background(logo)
    return _remove_black_background(logo)


def generate_intro_image(
    title: str,
    settings: dict,
    output_path: Path,
    project_root: Path,
    *,
    episode_number: int | None = None,
    episode_subtitle: str | None = None,
) -> Path:
    intro_settings = settings["intro"]
    width, height = settings["resolution"]
    background = _hex_to_rgb(intro_settings["background"])
    primary = _hex_to_rgb(intro_settings.get("primary_color", intro_settings["title_color"]))
    title_color = _hex_to_rgb(intro_settings["title_color"])
    line_color = _hex_to_rgb(intro_settings.get("line_color", "#B8B8B8"))
    subtitle_color = _hex_to_rgb(intro_settings.get("subtitle_color", "#7A7A7A"))
    production_color = _hex_to_rgb(intro_settings.get("production_text_color", "#8A8A8A"))
    number_text_color = _hex_to_rgb(intro_settings.get("number_text_color", "#FFFFFF"))

    canvas = Image.new("RGBA", (width, height), (*background, 255))

    logo_main_path = _resolve_path(project_root, intro_settings["logo_main"])
    logo_partner_path = _resolve_path(project_root, intro_settings["logo_partner"])
    font_path = _resolve_path(project_root, intro_settings["font"])
    subtitle_font_path = _resolve_path(
        project_root,
        intro_settings.get("subtitle_font", intro_settings.get("number_font", intro_settings["font"])),
    )
    number_font_path = _resolve_path(
        project_root,
        intro_settings.get("number_font", intro_settings["font"]),
    )
    production_font_path = _resolve_path(
        project_root,
        intro_settings.get("production_font", subtitle_font_path),
    )

    font_size = intro_settings.get("font_size", 96)
    subtitle_font_size = intro_settings.get("subtitle_font_size", 34)
    number_font_size = intro_settings.get("number_font_size", 30)
    production_font_size = intro_settings.get("production_font_size", 22)
    logo_main_width = intro_settings.get("logo_main_width", 360)
    logo_partner_width = intro_settings.get("logo_partner_width", 130)
    edge_margin = intro_settings.get("edge_margin", int(height * 0.08))
    content_width_ratio = intro_settings.get("content_width_ratio", 0.72)

    production_text = intro_settings.get("production_text", "إنتاج وتنفيذ")

    main_logo = _fit_image_width(
        _remove_black_background(Image.open(logo_main_path)),
        logo_main_width,
    )
    partner_logo = _fit_image_width(
        _remove_black_background(Image.open(logo_partner_path)),
        logo_partner_width,
    )

    draw = ImageDraw.Draw(canvas)
    content_width = int(width * content_width_ratio)
    content_left = (width - content_width) // 2
    content_right = content_left + content_width
    line_rgba = _rgba(line_color, 255)
    primary_rgba = _rgba(primary, 255)

    max_text_width = int(width * 0.78)
    lines = _wrap_text_by_width(title, font_path, font_size, max_text_width)
    line_spacing = int(font_size * 0.28)
    title_block_height = len(lines) * font_size + max(0, len(lines) - 1) * line_spacing

    number_radius = intro_settings.get("number_circle_radius", 34)
    title_to_number_gap = intro_settings.get("title_to_number_gap", 48)
    number_subtitle_gap = intro_settings.get("number_subtitle_gap", 16)

    subtitle = episode_subtitle
    if subtitle is None and episode_number is not None:
        subtitle = lesson_subtitle(episode_number)

    meta_row_height = 0
    if episode_number is not None or subtitle:
        meta_row_height = max(
            number_radius * 2 if episode_number is not None else 0,
            subtitle_font_size if subtitle else 0,
        )

    content_stack_height = title_block_height + title_to_number_gap + meta_row_height

    production_font = _load_font(production_font_path, production_font_size)
    production_bbox = draw.textbbox((0, 0), production_text, font=production_font, anchor="mm")
    production_height = production_bbox[3] - production_bbox[1]
    production_text_width = _measure_arabic_text(production_text, production_font_path, production_font_size)
    footer_box_pad_x = intro_settings.get("footer_box_pad_x", 28)
    footer_box_pad_y = intro_settings.get("footer_box_pad_y", 14)
    footer_box_width = max(partner_logo.width, int(production_text_width)) + footer_box_pad_x * 2
    footer_box_height = production_height + partner_logo.height + footer_box_pad_y * 3

    top_y = edge_margin
    footer_line_y = height - edge_margin - footer_box_height // 2 - 8
    footer_top = footer_line_y - footer_box_height // 2

    content_area_top = top_y + main_logo.height
    content_area_bottom = footer_top
    content_stack_top = content_area_top + max(0, (content_area_bottom - content_area_top - content_stack_height) // 2)

    title_text_offset_y = intro_settings.get("title_text_offset_y", 10)

    _paste_centered(canvas, main_logo, top_y)

    title_start_y = content_stack_top + font_size // 2

    for index, line in enumerate(lines):
        _draw_arabic_text(
            canvas,
            line,
            font_path=font_path,
            font_size=font_size,
            color=title_color,
            center_x=width // 2,
            center_y=title_start_y + index * (font_size + line_spacing) + title_text_offset_y,
        )

    meta_row_y = (
        content_stack_top
        + title_block_height
        + title_to_number_gap
        + meta_row_height // 2
    )

    if episode_number is not None and subtitle:
        subtitle_width = _measure_arabic_text(subtitle, subtitle_font_path, subtitle_font_size)
        group_width = subtitle_width + number_subtitle_gap + number_radius * 2
        group_left = (width - group_width) // 2
        subtitle_cx = group_left + subtitle_width / 2
        circle_cx = group_left + subtitle_width + number_subtitle_gap + number_radius

        circle_box = [
            circle_cx - number_radius,
            meta_row_y - number_radius,
            circle_cx + number_radius,
            meta_row_y + number_radius,
        ]
        draw.ellipse(circle_box, fill=primary_rgba)
        number_font = _load_font(number_font_path, number_font_size)
        draw.text(
            (circle_cx, meta_row_y),
            str(episode_number),
            font=number_font,
            fill=number_text_color,
            anchor="mm",
        )
        subtitle_center_y = meta_row_y + int(subtitle_font_size * 0.28)
        _draw_arabic_text(
            canvas,
            subtitle,
            font_path=subtitle_font_path,
            font_size=subtitle_font_size,
            color=subtitle_color,
            center_x=int(subtitle_cx),
            center_y=subtitle_center_y,
        )
    elif episode_number is not None:
        circle_box = [
            width // 2 - number_radius,
            meta_row_y - number_radius,
            width // 2 + number_radius,
            meta_row_y + number_radius,
        ]
        draw.ellipse(circle_box, fill=primary_rgba)
        number_font = _load_font(number_font_path, number_font_size)
        draw.text(
            (width // 2, meta_row_y),
            str(episode_number),
            font=number_font,
            fill=number_text_color,
            anchor="mm",
        )
    elif subtitle:
        _draw_arabic_text(
            canvas,
            subtitle,
            font_path=subtitle_font_path,
            font_size=subtitle_font_size,
            color=subtitle_color,
            center_x=width // 2,
            center_y=meta_row_y,
        )

    _draw_horizontal_rule(
        draw,
        footer_line_y,
        content_left,
        content_right,
        line_rgba,
        diamond_size=intro_settings.get("diamond_size", 7),
        diamond_color=primary_rgba,
    )

    footer_box = [
        width // 2 - footer_box_width // 2,
        footer_line_y - footer_box_height // 2,
        width // 2 + footer_box_width // 2,
        footer_line_y + footer_box_height // 2,
    ]
    footer_fill = _rgba(_hex_to_rgb(intro_settings.get("footer_box_fill", "#F7F7F7")), 255)
    footer_border = _rgba(_hex_to_rgb(intro_settings.get("footer_box_border", "#D4D4D4")), 255)
    draw.rounded_rectangle(footer_box, radius=12, fill=footer_fill, outline=footer_border, width=1)

    production_y = footer_box[1] + footer_box_pad_y + production_height // 2
    _draw_arabic_text(
        canvas,
        production_text,
        font_path=production_font_path,
        font_size=production_font_size,
        color=production_color,
        center_x=width // 2,
        center_y=production_y,
    )

    partner_top = int(production_y + production_height // 2 + footer_box_pad_y)
    _paste_centered(canvas, partner_logo, partner_top)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, format="PNG")
    return output_path
