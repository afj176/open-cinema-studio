"""Open Cinema motion graphics: kinetic type that takes on each film's look.

Pure Pillow + NumPy, resolution independent, deterministic for a given seed. Everything is a
function of time, so a frame can be rendered on its own (for previews) or as a sequence.

Building blocks: title slam, glowing line, starburst, typewriter label, HUD frame.
Compositions: title over footage, shot stamp over footage, full-frame cards (title, trailer
line, credits).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path(__file__).resolve().parent / "fonts"


@dataclass(frozen=True)
class Style:
    ink: str
    accent: str
    glow: str
    bg: str
    face: str  # barlow | fraunces | manrope
    upper: bool = True


try:
    from .director import LOOK_PALETTES
except ImportError:  # imported as a plain module (tests, tools)
    from director import LOOK_PALETTES

LOWERCASE_LOOKS = {"16mm indie"}
STYLES: dict[str, Style] = {look: Style(*palette, upper=look not in LOWERCASE_LOOKS)
                            for look, palette in LOOK_PALETTES.items()}


def style_for(look: str, palette: str = "") -> Style:
    """The look's style; a custom 'bg,ink,accent,glow' palette overrides its colours but keeps its typeface."""
    style = STYLES.get(look, STYLES["None"])
    colours = [c.strip() for c in (palette or "").split(",") if c.strip().startswith("#") and len(c.strip()) == 7]
    if len(colours) == 4:
        bg, ink, accent, glow = colours
        return Style(ink, accent, glow, bg, style.face, style.upper)
    return style


def rgb(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha


@lru_cache(maxsize=64)
def font(face: str, size: int) -> ImageFont.FreeTypeFont:
    size = max(8, int(size))
    if face == "barlow":
        return ImageFont.truetype(str(FONTS / "BarlowCondensed-Black.ttf"), size)
    if face == "mono":
        f = ImageFont.truetype(str(FONTS / "JetBrainsMono-Variable.ttf"), size)
        f.set_variation_by_name("Bold")
        return f
    if face == "fraunces":
        f = ImageFont.truetype(str(FONTS / "Fraunces-Variable.ttf"), size)
        f.set_variation_by_name("Black")
        return f
    f = ImageFont.truetype(str(FONTS / "Manrope-Variable.ttf"), size)
    f.set_variation_by_name("ExtraBold")
    return f


# ---------------------------------------------------------------- easing

def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def ease_out_expo(p: float) -> float:
    p = clamp(p)
    return 1.0 if p >= 1 else 1 - 2 ** (-10 * p)


def ease_in_out(p: float) -> float:
    p = clamp(p)
    return 0.5 - 0.5 * math.cos(math.pi * p)


# ---------------------------------------------------------------- text layout

def fit_lines(text: str, face: str, width: int, height: int, max_lines: int = 2) -> tuple[list[str], int]:
    """Split into balanced lines and pick the largest size that fits the box."""
    words = text.split()
    candidates = [[text]]
    items = text.split(" · ")
    if len(items) > 1 and max_lines > 1:  # lists break between items, never before a separator
        cut = min(range(1, len(items)),
                  key=lambda i: abs(len(" · ".join(items[:i])) - len(" · ".join(items[i:]))))
        candidates.append([" · ".join(items[:cut]), " · ".join(items[cut:])])
    elif len(words) > 1 and max_lines > 1:
        best = min(range(1, len(words)),
                   key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
        candidates.append([" ".join(words[:best]), " ".join(words[best:])])
    best_lines, best_size = candidates[0], 8
    for lines in candidates:
        size = height // len(lines)
        while size > 8:
            f = font(face, size)
            widest = max(f.getlength(line) for line in lines)
            if widest <= width and size * len(lines) * 1.02 <= height:
                break
            size = int(size * 0.94)
        if size > best_size:
            best_lines, best_size = lines, size
    return best_lines, best_size


def text_layer(lines: list[str], face: str, size: int, fill, tracking: float = 0.0) -> Image.Image:
    """Render lines centred on a tight transparent layer with optional letter spacing."""
    f = font(face, size)
    gap = size * tracking
    widths = [sum(f.getlength(ch) for ch in line) + gap * max(0, len(line) - 1) for line in lines]
    line_h = int(size * 1.02)
    pad = int(size * 0.3)
    w, h = int(max(widths)) + 2 * pad, line_h * len(lines) + 2 * pad
    layer = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for index, line in enumerate(lines):
        x = pad + (w - 2 * pad - widths[index]) / 2
        y = pad + index * line_h
        for ch in line:
            draw.text((x, y), ch, font=f, fill=fill)
            x += f.getlength(ch) + gap
    return layer


def paste_center(canvas: Image.Image, layer: Image.Image, cx: float, cy: float, scale: float = 1.0,
                 alpha: float = 1.0) -> None:
    if alpha <= 0.002:
        return
    if abs(scale - 1.0) > 1e-3:
        layer = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))),
                             Image.Resampling.BICUBIC)
    if alpha < 0.999:
        a = np.asarray(layer).copy()
        a[..., 3] = (a[..., 3].astype(np.float32) * alpha).astype(np.uint8)
        layer = Image.fromarray(a, "RGBA")
    canvas.alpha_composite(layer, (int(cx - layer.width / 2), int(cy - layer.height / 2)))


# ---------------------------------------------------------------- building blocks

def title_slam(canvas: Image.Image, text: str, style: Style, t: float, start: float, end: float,
               box: tuple[float, float, float, float] = (0.5, 0.47, 0.82, 0.34), backing: bool = False) -> None:
    """Heavy type punches in from oversize with motion blur and an offset accent shadow."""
    local = t - start
    if local < 0 or t > end:
        return
    W, H = canvas.size
    cx, cy, bw, bh = box[0] * W, box[1] * H, box[2] * W, box[3] * H
    text = text.upper() if style.upper else text
    lines, size = fit_lines(text, style.face, int(bw), int(bh))
    p = ease_out_expo(local / 0.32)
    scale = 1.0 + 0.55 * (1 - p) + 0.035 * clamp(local / max(0.01, end - start))
    tracking = 0.09 * (1 - p) + 0.01
    out = clamp((t - (end - 0.14)) / 0.14)
    alpha = clamp(local / 0.06) * (1 - out)
    scale *= 1 + 0.25 * out
    shadow = text_layer(lines, style.face, size, rgb(style.accent), tracking)
    ink = text_layer(lines, style.face, size, rgb(style.ink), tracking)
    offset = size * (0.035 + 0.12 * (1 - p))
    if backing:  # soft dark shadow so type reads over busy footage
        soft = text_layer(lines, style.face, size, (0, 0, 0, 255), tracking)
        soft = soft.filter(ImageFilter.GaussianBlur(radius=size * 0.12))
        paste_center(canvas, soft, cx + size * 0.03, cy + size * 0.06, scale * 1.02, alpha * 0.75)
    paste_center(canvas, shadow, cx + offset, cy + offset * 0.55, scale, alpha * 0.9)
    if p < 0.97:  # zoom blur while it lands
        for k, fade in ((1.18, 0.18), (1.09, 0.28)):
            paste_center(canvas, ink, cx, cy, scale * (1 + (k - 1) * (1 - p)), alpha * fade)
    paste_center(canvas, ink, cx, cy, scale, alpha)


def _bezier(points: list[tuple[float, float]], n: int) -> np.ndarray:
    p0, p1, p2, p3 = (np.array(p, dtype=np.float32) for p in points)
    s = np.linspace(0, 1, n, dtype=np.float32)[:, None]
    return ((1 - s) ** 3) * p0 + 3 * ((1 - s) ** 2) * s * p1 + 3 * (1 - s) * s * s * p2 + (s ** 3) * p3


def glow_line(canvas: Image.Image, style: Style, t: float, start: float, dur: float, seed: int = 7,
              width_scale: float = 1.0) -> None:
    """The signature device: one glowing line streaking through the frame with a hot head."""
    p = (t - start) / dur
    if p <= 0 or p >= 1.35:
        return
    W, H = canvas.size
    rnd = random.Random(seed)
    y0, y3 = rnd.uniform(0.25, 0.8) * H, rnd.uniform(0.2, 0.75) * H
    pts = [(-0.08 * W, y0), (rnd.uniform(0.2, 0.4) * W, rnd.uniform(0.05, 0.95) * H),
           (rnd.uniform(0.6, 0.8) * W, rnd.uniform(0.05, 0.95) * H), (1.08 * W, y3)]
    path = _bezier(pts, 240)
    head = int(clamp(ease_in_out(min(p, 1.0))) * (len(path) - 1))
    tail = max(0, head - int(len(path) * 0.38))
    if head - tail < 2:
        return
    fade = 1.0 - clamp((p - 1.0) / 0.35)
    layer = Image.new("RGBA", (W // 2, H // 2), (0, 0, 0, 0))
    core = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    draw, core_draw = ImageDraw.Draw(layer), ImageDraw.Draw(core)
    seg = path[tail:head + 1] / 2
    lw = max(2, int(W / 420 * width_scale))
    for i in range(len(seg) - 1):  # tail tapers in
        taper = ((i + 1) / len(seg)) ** 1.4
        draw.line([tuple(seg[i]), tuple(seg[i + 1])], fill=rgb(style.glow, int(255 * fade * taper)),
                  width=lw * 3)
        core_draw.line([tuple(seg[i]), tuple(seg[i + 1])], fill=rgb("#FFFFFF", int(235 * fade * taper)),
                       width=max(1, lw // 2))
    halo = layer.filter(ImageFilter.GaussianBlur(radius=max(4, W / 110)))
    glow = layer.filter(ImageFilter.GaussianBlur(radius=max(2, W / 320)))
    hx, hy = seg[-1]
    r = max(2, W / 380)
    head_glow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(head_glow).ellipse([hx - 5 * r, hy - 5 * r, hx + 5 * r, hy + 5 * r],
                                      fill=rgb(style.glow, int(230 * fade)))
    head_glow = head_glow.filter(ImageFilter.GaussianBlur(radius=3 * r))
    core_draw.ellipse([hx - r, hy - r, hx + r, hy + r], fill=(255, 255, 255, int(255 * fade)))
    merged = halo
    for part in (halo, glow, head_glow, core):
        merged = Image.alpha_composite(merged, part)
    canvas.alpha_composite(merged.resize((W, H), Image.Resampling.BILINEAR))


def starburst(canvas: Image.Image, style: Style, t: float, start: float, dur: float, seed: int = 3,
              strength: float = 1.0) -> None:
    """Radial speed lines that flash outward on impact."""
    p = (t - start) / dur
    if p <= 0 or p >= 1:
        return
    W, H = canvas.size
    cx, cy = W / 2, H * 0.47
    rnd = random.Random(seed)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    reach = math.hypot(W, H) * 0.62
    alpha = (1 - p) ** 1.5 * strength
    for _ in range(70):
        ang = rnd.uniform(0, math.tau)
        r0 = reach * (0.12 + 0.55 * ease_out_expo(p) * rnd.uniform(0.6, 1.0))
        r1 = r0 + reach * rnd.uniform(0.08, 0.35)
        color = style.accent if rnd.random() < 0.25 else style.ink
        draw.line([(cx + math.cos(ang) * r0, cy + math.sin(ang) * r0),
                   (cx + math.cos(ang) * r1, cy + math.sin(ang) * r1)],
                  fill=rgb(color, int(150 * alpha)), width=max(1, W // 1100))
    canvas.alpha_composite(layer)


def typewriter(canvas: Image.Image, text: str, style: Style, t: float, start: float, x: float, y: float,
               size: float, highlight: str = "", hold: float = 99.0, cps: float = 30.0,
               panel: bool = False) -> None:
    """Mono text typed on with a block cursor; the highlight word sits in an accent box."""
    local = t - start
    if local < 0 or local > hold:
        return
    W, H = canvas.size
    f = font("mono", int(size * H))
    shown = text[: int(local * cps)]
    fade = 1 - clamp((local - (hold - 0.25)) / 0.25)
    draw = ImageDraw.Draw(canvas)
    px, py = x * W, y * H
    if panel:
        full_w = f.getlength(text)
        pad = size * H * 0.8
        draw.rounded_rectangle([px - pad, py - pad * 0.7, px + full_w + pad, py + size * H + pad * 0.7],
                               radius=int(pad * 0.4), fill=(0, 0, 0, int(120 * fade)),
                               outline=rgb(style.ink, int(60 * fade)), width=max(1, W // 1400))
    start_hl = text.find(highlight) if highlight else -1
    cursor_x = px
    for i, ch in enumerate(shown):
        cw = f.getlength(ch)
        in_hl = start_hl >= 0 and start_hl <= i < start_hl + len(highlight)
        if in_hl:
            draw.rectangle([cursor_x - 1, py - size * H * 0.12, cursor_x + cw + 1, py + size * H * 1.12],
                           fill=rgb(style.accent, int(255 * fade)))
        if not in_hl:  # a 1px dark offset keeps small type legible over footage
            draw.text((cursor_x + 1.5, py + 1.5), ch, font=f, fill=(0, 0, 0, int(200 * fade)))
        draw.text((cursor_x, py), ch, font=f,
                  fill=rgb(style.bg if in_hl else style.ink, int(255 * fade)))
        cursor_x += cw
    if len(shown) < len(text) or int(local * 2.2) % 2 == 0:
        draw.rectangle([cursor_x + 2, py, cursor_x + 2 + size * H * 0.55, py + size * H * 1.05],
                       fill=rgb(style.accent, int(230 * fade)))


def hud(canvas: Image.Image, style: Style, t: float, start: float, end: float, labels: dict[str, str],
        frame_number: int | None = None) -> None:
    """Thin corner brackets and tiny mono labels, like a camera monitor."""
    if t < start or t > end:
        return
    alpha = clamp((t - start) / 0.3) * (1 - clamp((t - (end - 0.3)) / 0.3))
    W, H = canvas.size
    draw = ImageDraw.Draw(canvas)
    m, L, lw = 0.035, 0.045, max(1, W // 1000)
    color = rgb(style.ink, int(110 * alpha))
    for sx, sy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        x = W * (m if sx == 0 else 1 - m)
        y = H * (m if sy == 0 else 1 - m)
        dx = W * L * (1 if sx == 0 else -1)
        dy = W * L * (1 if sy == 0 else -1)
        draw.line([(x, y), (x + dx, y)], fill=color, width=lw)
        draw.line([(x, y), (x, y + dy)], fill=color, width=lw)
    f = font("mono", int(H * 0.017))
    label_color = rgb(style.ink, int(150 * alpha))
    if labels.get("tl"):
        draw.text((W * (m + 0.008), H * (m + 0.012)), labels["tl"], font=f, fill=label_color)
    if labels.get("tr"):
        draw.text((W * (1 - m - 0.008) - f.getlength(labels["tr"]), H * (m + 0.012)), labels["tr"],
                  font=f, fill=label_color)
    br = labels.get("br") or (f"FRAME {frame_number:04d}" if frame_number is not None else "")
    if br:
        draw.text((W * (1 - m - 0.008) - f.getlength(br), H * (1 - m - 0.03)), br, font=f, fill=label_color)


# ---------------------------------------------------------------- compositions

def _scrim(frame: np.ndarray, amount: float) -> np.ndarray:
    """Darken the footage toward the centre so type reads, without a visible box."""
    if amount <= 0:
        return frame
    H, W = frame.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / (W * 0.55)) ** 2 + ((yy - H * 0.47) / (H * 0.5)) ** 2)
    mask = np.clip(1.2 - d, 0, 1) * amount
    return frame * (1 - 0.55 * mask[..., None])


def _over(frame: np.ndarray, layer: Image.Image) -> np.ndarray:
    a = np.asarray(layer).astype(np.float32) / 255.0
    return frame * (1 - a[..., 3:4]) + a[..., :3] * a[..., 3:4]


def title_overlay(frames: np.ndarray, fps: float, title: str, subtitle: str, look: str,
                  start: float = 0.5, hold: float = 3.2, seed: int = 11, palette: str = "") -> np.ndarray:
    """Main title over the opening shot: line streak, slam on impact, typed subtitle, HUD."""
    style = style_for(look, palette)
    n, H, W = frames.shape[:3]
    out = frames.astype(np.float32).copy()
    end = min(start + hold, n / fps - 0.2)
    for i in range(n):
        t = i / fps
        if t > end + 0.05:
            break
        ramp = clamp((t - start + 0.4) / 0.4) * (1 - clamp((t - (end - 0.2)) / 0.3))
        frame = _scrim(out[i], 0.85 * ramp)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        hud(layer, style, t, start - 0.3, end, {"tl": "OPEN CINEMA", "tr": title.upper()[:40]}, i)
        glow_line(layer, style, t, start - 0.35, 0.9, seed)
        starburst(layer, style, t, start, 0.55, seed, 0.6)
        title_slam(layer, title, style, t, start, end, backing=True)
        if subtitle:
            f_size = 0.03
            sub = subtitle.upper() if style.upper else subtitle
            width = font("mono", int(f_size * H)).getlength(sub) / W
            typewriter(layer, sub, style, t, start + 0.55, 0.5 - width / 2, 0.72, f_size,
                       hold=end - start - 0.55)
        out[i] = _over(frame, layer)
    return np.clip(out, 0, 1)


def stamp_overlay(frames: np.ndarray, fps: float, text: str, highlight: str, look: str,
                  start: float = 0.35, hold: float = 2.6, palette: str = "") -> np.ndarray:
    """A HUD slate on a shot: corner brackets and a typed label, then it gets out of the way."""
    style = style_for(look, palette)
    n, H, W = frames.shape[:3]
    out = frames.astype(np.float32).copy()
    end = start + hold
    for i in range(n):
        t = i / fps
        if t > end + 0.05:
            break
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        hud(layer, style, t, start - 0.2, end, {}, None)
        typewriter(layer, text, style, t, start, 0.055, 0.88, 0.026, highlight=highlight, hold=hold)
        out[i] = _over(out[i], layer)
    return np.clip(out, 0, 1)


def _card_background_base(W: int, H: int, style: Style) -> np.ndarray:
    base = np.array(rgb(style.bg)[:3], dtype=np.float32) / 255.0
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / (W * 0.7)) ** 2 + ((yy - H / 2) / (H * 0.7)) ** 2)
    lift = np.clip(1 - d, 0, 1)[..., None] * 0.06
    return base + lift


def _card_background(W: int, H: int, style: Style, rng: np.random.Generator,
                     base: np.ndarray | None = None) -> np.ndarray:
    if base is None:
        base = _card_background_base(W, H, style)
    grain = rng.normal(0, 0.018, (H, W, 1)).astype(np.float32)
    return np.clip(base + grain, 0, 1)


def cards(texts: list[str], fps: float, width: int, height: int, look: str, per_card: float = 1.1,
          labels: list[str] | None = None, seed: int = 5, line_every: int = 2, palette: str = "") -> np.ndarray:
    """Full-frame type cards, hard cut from one to the next (trailer lines, title card, credits).

    `labels` puts a small mono role line above each card's main text (e.g. DIRECTED BY).
    """
    style = style_for(look, palette)
    rng = np.random.default_rng(seed)
    background_base = _card_background_base(width, height, style)
    total = int(round(per_card * len(texts) * fps))
    out = np.zeros((total, height, width, 3), dtype=np.float32)
    for i in range(total):
        t = i / fps
        k = min(len(texts) - 1, int(t // per_card))
        local_start = k * per_card
        frame = _card_background(width, height, style, rng, background_base)
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        hud(layer, style, t, 0, per_card * len(texts), {"tl": "OPEN CINEMA"}, i)
        starburst(layer, style, t, local_start, 0.6, seed + k, 0.9)
        if k % line_every == 0:
            glow_line(layer, style, t, local_start - 0.1, per_card * 0.9, seed + 31 * k)
        box = (0.5, 0.52, 0.8, 0.3) if labels and labels[k] else (0.5, 0.48, 0.82, 0.36)
        title_slam(layer, texts[k], style, t, local_start, local_start + per_card + 0.2, box)
        if labels and labels[k]:
            f = font("mono", int(height * 0.028))
            lab = labels[k].upper()
            ImageDraw.Draw(layer).text((width / 2 - f.getlength(lab) / 2, height * 0.3), lab, font=f,
                                       fill=rgb(style.accent, int(255 * clamp((t - local_start) / 0.15))))
        # Compose into the per-frame buffer; avoid multiple full-frame RGB
        # temporaries and avoid a second copy of the entire video on return.
        overlay = np.asarray(layer).astype(np.float32) / 255.0
        alpha = overlay[..., 3:4]
        np.multiply(frame, 1 - alpha, out=frame)
        frame += overlay[..., :3] * alpha
        out[i] = frame
    return np.clip(out, 0, 1, out=out)


def type_sheet(title: str, look: str, width: int = 1344, height: int = 768) -> Image.Image:
    """The title set in the look's typeface, dark on light: a spelling-perfect reference for image editing."""
    style = style_for(look)
    text = title.upper() if style.upper else title
    lines, size = fit_lines(text, style.face, int(width * 0.86), int(height * 0.62))
    sheet = Image.new("RGBA", (width, height), (236, 234, 228, 255))
    paste_center(sheet, text_layer(lines, style.face, size, (24, 22, 20, 255), 0.02), width / 2, height / 2)
    return sheet.convert("RGB")


def preview(look: str, title: str, width: int = 1280, height: int = 704, palette: str = "") -> Image.Image:
    """One representative title frame on a card background, for UI previews."""
    style = style_for(look, palette)
    frame = _card_background(width, height, style, np.random.default_rng(1))
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    hud(layer, style, 1.0, 0, 3, {"tl": "OPEN CINEMA", "tr": title.upper()[:40]}, 24)
    glow_line(layer, style, 0.55, 0.0, 0.9, 11)
    title_slam(layer, title, style, 1.2, 0.5, 3.0)
    return Image.fromarray((_over(frame, layer) * 255).astype(np.uint8), "RGB")
