# utils.py
import os
import sys
from functools import lru_cache
import numpy as np
from sklearn.cluster import MiniBatchKMeans
from PyQt5.QtGui import QColor

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def normalize_color(rgb):
    r, g, b = rgb
    return (max(0, min(int(r), 255)), max(0, min(int(g), 255)), max(0, min(int(b), 255)))

def rgb_to_hsl(r, g, b):
    r /= 255.0; g /= 255.0; b /= 255.0
    cmax = max(r, g, b); cmin = min(r, g, b)
    delta = cmax - cmin
    h = 0; s = 0; l = (cmax + cmin) / 2
    if delta != 0:
        s = delta / (1 - abs(2 * l - 1))
        if cmax == r: h = ((g - b) / delta) % 6
        elif cmax == g: h = (b - r) / delta + 2
        else: h = (r - g) / delta + 4
        h = round(h * 60)
        if h < 0: h += 360
    return h, s, l

def hsl_to_rgb(h, s, l):
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    r, g, b = 0, 0, 0
    if 0 <= h < 60: r, g, b = c, x, 0
    elif 60 <= h < 120: r, g, b = x, c, 0
    elif 120 <= h < 180: r, g, b = 0, c, x
    elif 180 <= h < 240: r, g, b = 0, x, c
    elif 240 <= h < 300: r, g, b = x, 0, c
    elif 300 <= h < 360: r, g, b = c, 0, x
    return (r + m) * 255, (g + m) * 255, (b + m) * 255

def get_luminance(rgb):
    return (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255.0

def get_contrast_ratio(c1, c2):
    l1 = get_luminance(c1); l2 = get_luminance(c2)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)

def get_best_text_color(bg_color, candidates=None):
    if candidates and not isinstance(candidates, list): candidates = [candidates]
    if candidates and len(candidates) > 0 and isinstance(candidates[0], (int, float)): candidates = [candidates]
    if not candidates: candidates = []
    
    bg_r, bg_g, bg_b = bg_color
    bg_lum = get_luminance(bg_color)
    bg_h, bg_s, bg_l = rgb_to_hsl(bg_r, bg_g, bg_b)
    is_bg_grayscale = bg_s < 0.15

    best_color = None
    best_contrast = 0.0
    
    for c in candidates:
        r, g, b = c
        lum = get_luminance(c)
        contrast = (max(lum, bg_lum) + 0.05) / (min(lum, bg_lum) + 0.05)
        h, s, l = rgb_to_hsl(r, g, b)
        score = contrast
        if is_bg_grayscale and s > 0.25: score *= 0.8
        if contrast >= 4.5:
            if score > best_contrast: best_contrast = score; best_color = c
        else:
            if contrast > best_contrast and best_contrast < 4.5: best_contrast = contrast; best_color = c

    if best_contrast >= 4.5 and best_color: return best_color

    target = best_color if best_color else bg_color
    if is_bg_grayscale: target = (127, 127, 127) 
    r, g, b = target
    h, s, l = rgb_to_hsl(r, g, b)
    
    if bg_lum < 0.5:
        start_l = max(l, 0.5)
        for new_l in np.linspace(start_l, 1.0, 20):
            tr, tg, tb = hsl_to_rgb(h, s, new_l)
            tlum = get_luminance((tr, tg, tb))
            if ((max(tlum, bg_lum) + 0.05) / (min(tlum, bg_lum) + 0.05)) >= 4.5: return (int(tr), int(tg), int(tb))
        return (255, 255, 255)
    else:
        start_l = min(l, 0.5)
        for new_l in np.linspace(start_l, 0.0, 20):
            tr, tg, tb = hsl_to_rgb(h, s, new_l)
            tlum = get_luminance((tr, tg, tb))
            if ((max(tlum, bg_lum) + 0.05) / (min(tlum, bg_lum) + 0.05)) >= 4.5: return (int(tr), int(tg), int(tb))
        return (0, 0, 0)

def get_best_border_color(bg_color, text_color, candidates=None):
    if not candidates: candidates = []
    candidates = [c for c in candidates if isinstance(c, (list, tuple)) and len(c) >= 3]
    best_color = None; best_score = -1
    for c in candidates:
        text_contrast = get_contrast_ratio(c, text_color)
        bg_contrast = get_contrast_ratio(c, bg_color)
        if text_contrast < 1.5: continue
        score = text_contrast + (bg_contrast * 0.5)
        if score > best_score: best_score = score; best_color = c
    return best_color if best_color else (0,0,0)

def extract_palette_from_image(pil_img, num_lights=3, sample_size=150):
    from PIL import Image
    img = pil_img.resize((sample_size, int(pil_img.height * sample_size / pil_img.width)), Image.Resampling.LANCZOS)
    arr = np.array(img, dtype=float).reshape(-1, 3)
    n_clusters = 8
    kmeans = MiniBatchKMeans(n_clusters=n_clusters, n_init='auto', batch_size=1024).fit(arr)
    counts = np.bincount(kmeans.labels_)
    sorted_indices = np.argsort(counts)[::-1]

    scored_colors = []
    for i in sorted_indices:
        # Find the actual pixel color closest to this cluster center (not the average)
        cluster_mask = kmeans.labels_ == i
        cluster_pixels = arr[cluster_mask]
        cluster_center = kmeans.cluster_centers_[i]
        
        # Find the exact color from the image that is closest to the cluster center
        distances = np.linalg.norm(cluster_pixels - cluster_center, axis=1)
        closest_pixel_idx = np.argmin(distances)
        exact_color = cluster_pixels[closest_pixel_idx]
        
        r, g, b = exact_color
        h, s, l = rgb_to_hsl(r, g, b)
        dominance = counts[i] / len(arr)
        primary_score = dominance * 2.0
        if 0.25 < l < 0.75: primary_score *= 0.5
        if l < 0.2: primary_score *= 1.5
        elif l > 0.7: primary_score *= 0.4
        if s > 0.4: primary_score *= 0.6
        accent_score = s * 3.0 + dominance * 1.0
        if l < 0.2 or l > 0.8: accent_score *= 0.4
        scored_colors.append({"color": exact_color.astype(int).tolist(), "primary_score": primary_score, "accent_score": accent_score, "h": h, "s": s, "l": l, "dominance": dominance})

    scored_colors.sort(key=lambda x: x["primary_score"], reverse=True)
    best_primary = scored_colors[0]
    p_r, p_g, p_b = best_primary["color"]
    p_h, p_s, p_l = rgb_to_hsl(p_r, p_g, p_b)
    if p_l > 0.6:
        p_l = 0.6
        p_r, p_g, p_b = hsl_to_rgb(p_h, p_s, p_l)
        best_primary["color"] = [int(p_r), int(p_g), int(p_b)]
        best_primary["l"] = p_l

    accent_candidates = []
    for c in scored_colors:
        lum_diff = abs(c["l"] - best_primary["l"])
        rgb_dist = np.linalg.norm(np.array(c["color"]) - np.array(best_primary["color"]))
        if rgb_dist > 60 and lum_diff > 0.15: accent_candidates.append(c)
    
    if accent_candidates: best_accent = max(accent_candidates, key=lambda x: x["accent_score"])
    else:
        p_c = QColor(*best_primary["color"])
        fallback = p_c.lighter(160) if p_c.lightnessF() < 0.5 else p_c.darker(160)
        best_accent = {"color": [fallback.red(), fallback.green(), fallback.blue()], "s": 0, "l": fallback.lightnessF()}

    ui_palette = [best_primary["color"], best_accent["color"]]
    sorted_by_sat = sorted(scored_colors, key=lambda x: x["s"], reverse=True)
    blob_palette = []
    for c in sorted_by_sat:
        rgb_dist = np.linalg.norm(np.array(c["color"]) - np.array(best_primary["color"]))
        if rgb_dist > 40: blob_palette.append(c["color"])
        if len(blob_palette) >= 5: break
    
    if not blob_palette: blob_palette = [best_accent["color"]]
    while len(blob_palette) < 3:
        last_color = QColor(*blob_palette[-1])
        blob_palette.append(last_color.lighter(115).getRgb()[:3])

    lights_palette = blob_palette[:num_lights]
    text_candidates = [best_accent["color"]]
    for c in scored_colors:
        if np.linalg.norm(np.array(c["color"]) - np.array(best_primary["color"])) > 40: text_candidates.append(c["color"])

    best_text_color = list(get_best_text_color(best_primary["color"], text_candidates))
    contrast = get_contrast_ratio(best_text_color, best_primary["color"])
    border_needed = contrast < 3.5
    
    return ui_palette, lights_palette, blob_palette, best_text_color, border_needed


@lru_cache(maxsize=1)
def detect_opengl_background_support():
    """
    Lightweight runtime check for whether an OpenGL context can be created.
    Returns (is_supported, reason).
    """
    try:
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QOpenGLContext, QOffscreenSurface, QSurfaceFormat
    except Exception as exc:
        return False, f"OpenGL imports unavailable: {exc}"

    app = QApplication.instance()
    if app is None:
        return False, "QApplication not initialized"

    try:
        fmt = QSurfaceFormat()
        fmt.setRenderableType(QSurfaceFormat.OpenGL)
        fmt.setVersion(2, 1)
        fmt.setProfile(QSurfaceFormat.NoProfile)

        surface = QOffscreenSurface()
        surface.setFormat(fmt)
        surface.create()
        if not surface.isValid():
            return False, "Offscreen GL surface is invalid"

        ctx = QOpenGLContext()
        ctx.setFormat(fmt)
        if not ctx.create():
            return False, "OpenGL context creation failed"
        if not ctx.makeCurrent(surface):
            return False, "Could not make OpenGL context current"

        gl_format = ctx.format()
        major = gl_format.majorVersion()
        minor = gl_format.minorVersion()
        ctx.doneCurrent()
        if major <= 0:
            return False, "OpenGL version unavailable"

        return True, f"OpenGL {major}.{minor}"
    except Exception as exc:
        return False, f"OpenGL probe failed: {exc}"