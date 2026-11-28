# -*- coding: utf-8 -*-
"""网络图标加载（Modrinth 项目 icon_url）

- 磁盘缓存：%APPDATA%\\MCLite\\cache\\icons
- 圆角裁切 + 缩放，输出 tkinter PhotoImage
- 下载在后台线程，PhotoImage 在主线程创建，避免 Tk 跨线程崩溃
"""
import hashlib
import io
import os
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor

from . import util

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    HAS_PIL = True
except Exception:  # 没装 Pillow 时降级为纯色占位块
    HAS_PIL = False

ROOT = os.path.join(util.app_root(), "cache", "icons")
_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="icon")
_mem = {}

PALETTE = ["#3ddc84", "#5aa7f0", "#f0b429", "#e06c75", "#a78bfa", "#2fb56e", "#f78c6c"]


def _color_for(text):
    h = int(hashlib.md5((text or "?").encode("utf-8")).hexdigest()[:8], 16)
    return PALETTE[h % len(PALETTE)]


def _round(img, radius):
    w, h = img.size
    mask = Image.new("L", (w * 4, h * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w * 4 - 1, h * 4 - 1], radius=radius * 4, fill=255)
    mask = mask.resize((w, h), Image.LANCZOS)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _fit(img, size):
    img = img.convert("RGBA")
    return img.resize((size, size), Image.LANCZOS)


def placeholder(text, size=48, radius=12):
    """本地生成的占位图标：彩底 + 首字母"""
    if not HAS_PIL:
        return None
    color = _color_for(text)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=color)
    letter = (text or "?").strip()[:1].upper()
    try:
        font = ImageFont.truetype("arialbd.ttf", int(size * 0.46))
    except Exception:
        font = ImageFont.load_default()
    d = ImageDraw.Draw(img)
    try:
        box = d.textbbox((0, 0), letter, font=font)
        w, h = box[2] - box[0], box[3] - box[1]
        d.text(((size - w) / 2 - box[0], (size - h) / 2 - box[1]), letter, font=font, fill="#0f1115")
    except Exception:
        pass
    return img


def _cache_path(url):
    return os.path.join(ROOT, hashlib.md5(url.encode("utf-8")).hexdigest() + ".png")


def load_photo(url, text, size=48, radius=12, on_ready=None):
    """主线程调用。

    返回 PhotoImage（缓存命中时立即返回）或 None（异步加载中，完成后回调 on_ready）。
    """
    key = (url, size, radius)
    if key in _mem:
        return _mem[key]

    if not HAS_PIL:
        return None

    if not url:
        img = placeholder(text, size, radius)
        ph = ImageTk.PhotoImage(img)
        _mem[key] = ph
        return ph

    def work():
        raw = None
        path = _cache_path(url)
        try:
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    raw = f.read()
            else:
                raw = util.http_get(url, timeout=15)
                os.makedirs(ROOT, exist_ok=True)
                with open(path, "wb") as f:
                    f.write(raw)
            img = _fit(Image.open(io.BytesIO(raw)), size)
            img = _round(img, radius)
        except Exception:
            img = placeholder(text, size, radius)
        if img is None:
            return

        def done():
            try:
                ph = ImageTk.PhotoImage(img)
                _mem[key] = ph
                if on_ready:
                    on_ready(ph)
            except Exception:
                pass

        root = tk._default_root
        if root is not None:
            try:
                root.after(0, done)
            except Exception:
                pass

    _pool.submit(work)
    return None
