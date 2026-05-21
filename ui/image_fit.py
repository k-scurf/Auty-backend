"""Uniform image fitting for profile snapshots."""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageTk


def fit_cover_bgr(bgr: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    """Scale and center-crop BGR image to exact output size (cover fit)."""
    if bgr is None or bgr.size == 0:
        return np.zeros((out_h, out_w, 3), dtype=np.uint8)

    h, w = bgr.shape[:2]
    scale = max(out_w / max(w, 1), out_h / max(h, 1))
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    resized = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    x0 = max(0, (new_w - out_w) // 2)
    y0 = max(0, (new_h - out_h) // 2)
    return resized[y0 : y0 + out_h, x0 : x0 + out_w].copy()


def bgr_to_photo_cover(bgr: np.ndarray, out_w: int, out_h: int) -> ImageTk.PhotoImage:
    fitted = fit_cover_bgr(bgr, out_w, out_h)
    rgb = cv2.cvtColor(fitted, cv2.COLOR_BGR2RGB)
    return ImageTk.PhotoImage(Image.fromarray(rgb))


def bgr_to_photo_cover_rounded(
    bgr: np.ndarray, out_w: int, out_h: int, *, radius: int = 12
) -> ImageTk.PhotoImage:
    fitted = fit_cover_bgr(bgr, out_w, out_h)
    rgb = cv2.cvtColor(fitted, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb).convert("RGBA")
    mask = Image.new("L", (out_w, out_h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, out_w, out_h), radius=radius, fill=255)
    pil.putalpha(mask)
    return ImageTk.PhotoImage(pil)
