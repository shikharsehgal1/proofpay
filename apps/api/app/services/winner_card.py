"""
Deterministic winner card rendering.

Imagine may supply aesthetic backgrounds later; numeric metrics are always
programmatically overlaid so models cannot hallucinate numbers on the card.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


def render_winner_card(
    *,
    username: str,
    improvement_pct: float,
    visible: str,
    hidden: str,
    bounty_title: str,
    out_dir: Path,
    background_path: Optional[Path] = None,
) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = 1200, 630
    if background_path and background_path.exists():
        img = Image.open(background_path).convert("RGB").resize((w, h))
    else:
        img = Image.new("RGB", (w, h), (8, 10, 18))
        draw = ImageDraw.Draw(img)
        # gradient-ish bars
        for y in range(h):
            c = int(8 + (y / h) * 30)
            draw.line([(0, y), (w, y)], fill=(c, c + 4, c + 18))

    draw = ImageDraw.Draw(img)
    try:
        font_lg = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 64)
        font_md = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 36)
        font_sm = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 28)
    except Exception:
        font_lg = ImageFont.load_default()
        font_md = font_lg
        font_sm = font_lg

    draw.rectangle([40, 40, w - 40, h - 40], outline=(120, 200, 255), width=3)
    draw.text((80, 80), "PROOFPAY VERIFIED", fill=(120, 220, 255), font=font_md)
    draw.text((80, 150), f"@{username}", fill=(255, 255, 255), font=font_lg)
    draw.text(
        (80, 250),
        f"+{improvement_pct:.1f}% latency improvement",
        fill=(100, 255, 180),
        font=font_md,
    )
    draw.text((80, 320), f"Visible tests: {visible}", fill=(220, 220, 230), font=font_sm)
    draw.text((80, 370), f"Hidden tests: {hidden}", fill=(220, 220, 230), font=font_sm)
    draw.text((80, 420), "Reproduced ✓", fill=(100, 255, 180), font=font_sm)
    title = (bounty_title or "")[:60]
    draw.text((80, 520), title, fill=(160, 170, 190), font=font_sm)

    out = out_dir / "winner_card.png"
    img.save(out, format="PNG")
    return str(out)
