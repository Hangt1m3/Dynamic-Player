# ui/widgets.py
import math
import random
import numpy as np
from PyQt5.QtCore import (Qt, pyqtProperty, pyqtSignal, QObject, QPointF, QRectF, QSize, 
                          QPropertyAnimation, QEasingCurve, QTimer, QParallelAnimationGroup, QRect, QEvent)
from PyQt5.QtWidgets import (QLabel, QProgressBar, QGraphicsOpacityEffect, QSizePolicy, QWidget, 
                             QPushButton, QComboBox, QGroupBox, QCheckBox, QRadioButton, QAbstractButton)
from PyQt5.QtGui import (QPainter, QPainterPath, QBrush, QColor, QFont, QFontMetrics, QRadialGradient, QPen, QPixmap, QFontDatabase, QLinearGradient)
from PyQt5.QtWidgets import QStyledItemDelegate
class BlobManager:
    """Manages the positions and properties of all blobs to prevent overlap."""
    def __init__(self, parent, parent_size, palette=None):
        self.parent = parent
        self.parent_size = parent_size
        self.palette = palette or []
        self.blobs = []
        self.dying_blobs = []
        self.density = 200000

    def add_blob(self, blob): self.blobs.append(blob)
    def remove_blob(self, blob):
        if blob in self.blobs: self.blobs.remove(blob)
        if blob in self.dying_blobs: self.dying_blobs.remove(blob)

    def stop_all(self):
        for blob in list(self.blobs):
            blob.stop()
        for blob in list(self.dying_blobs):
            blob.stop()
        self.blobs.clear()
        self.dying_blobs.clear()

    def update_palette(self, new_palette):
        self.palette = new_palette or []
        if not self.palette:
            for blob in list(self.blobs): blob.stop()
            return
        for i, blob in enumerate(self.blobs):
            new_color = self.palette[i % len(self.palette)]
            blob.change_color_animated(new_color)
        self.adjust_blob_count()

    def resize(self, size):
        old_size = self.parent_size
        self.parent_size = size
        if old_size.width() > 0 and old_size.height() > 0:
            w_ratio = size.width() / old_size.width()
            h_ratio = size.height() / old_size.height()
            old_ref = self._coverage_radius_reference(old_size)
            new_ref = self._coverage_radius_reference(size)
            scale_ratio = new_ref / old_ref if old_ref > 0 else 1.0
            for blob in self.blobs + self.dying_blobs:
                blob.handle_resize(w_ratio, h_ratio, scale_ratio)
        self.adjust_blob_count()

    def _coverage_radius_reference(self, size=None):
        target_size = size or self.parent_size
        width = max(1, target_size.width())
        height = max(1, target_size.height())
        # Blobs should be ~38% of the short edge so multiple colors fit simultaneously
        # on both portrait and landscape screens. The axis correction in the GL shader
        # follows the same principle: size is always relative to min(width, height).
        return float(min(width, height)) * 0.38

    def adjust_blob_count(self):
        if not self.palette: return
        unique_colors_count = max(1, len(set(c.rgba() for c in self.palette)))
        area = max(1, self.parent_size.width() * self.parent_size.height())
        area_target = max(0, min(8, area // 650000))
        # Spawn more blobs for portrait/ultrawide screens so all palette colors
        # remain visible along the long axis at the same time.
        width = max(1, self.parent_size.width())
        height = max(1, self.parent_size.height())
        long_short = float(max(width, height)) / max(float(min(width, height)), 1.0)
        aspect_boost = int(min(12, max(0, long_short - 1.05) * 6))
        target_count = max(unique_colors_count * 3, min(36, unique_colors_count * 4 + area_target + aspect_boost))

        # Add blobs if we have too few
        while len(self.blobs) < target_count:
            if not self.palette: break
            # Cycle through palette to ensure even representation
            color_index = len(self.blobs) % len(self.palette)
            color = self.palette[color_index]
            Blob(self, color, start_delay=random.randint(0, 2000))
            
        # Remove blobs if we have too many
        while len(self.blobs) > target_count :
            if self.blobs:
                # Remove the most transparent (fading) blob first
                blob_to_remove = min(self.blobs, key=lambda b: b.opacity)
                self.blobs.remove(blob_to_remove)
                self.dying_blobs.append(blob_to_remove)
                blob_to_remove.graceful_remove()

    def get_new_position(self, new_blob_radius):
        for _ in range(40):
            candidate_pos = QPointF(random.uniform(-0.3, 1.3) * self.parent_size.width(), random.uniform(-0.3, 1.3) * self.parent_size.height())
            is_overlapping_too_much = False
            for other_blob in self.blobs + self.dying_blobs:
                if other_blob.opacity <= 0.15:
                    continue
                dist = np.linalg.norm(np.array([candidate_pos.x(), candidate_pos.y()]) - np.array([other_blob.center.x(), other_blob.center.y()]))
                if dist < (new_blob_radius + other_blob.radius) * 0.74:
                    is_overlapping_too_much = True; break
            if not is_overlapping_too_much: return candidate_pos
        return QPointF(random.uniform(0, 1) * self.parent_size.width(), random.uniform(0, 1) * self.parent_size.height())

class Blob(QObject):
    _pixmap_cache = {}
    _pixmap_cache_order = []
    _pixmap_cache_limit = 96

    def __init__(self, manager, color, start_delay=0):
        super().__init__()
        self.manager = manager
        self._color = QColor(color)
        self._opacity = 0.0
        self._center = QPointF(0, 0)
        self._scale = 1.0
        self._drift_progress = 0.0
        self.start_pos = QPointF(0, 0)
        self.end_pos = QPointF(0, 0)
        self.radius = 1.0 
        self.pixmap = None
        self.animation_group = QParallelAnimationGroup(self)
        self.color_anim = QPropertyAnimation(self, b"color"); self.color_anim.setDuration(1200); self.color_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.opacity_anim = QPropertyAnimation(self, b"opacity"); self.opacity_anim.setEasingCurve(QEasingCurve.Linear)
        self.drift_anim = QPropertyAnimation(self, b"driftProgress"); self.drift_anim.setEasingCurve(QEasingCurve.Linear)
        self.scale_anim = QPropertyAnimation(self, b"scale"); self.scale_anim.setEasingCurve(QEasingCurve.Linear)
        self.animation_group.addAnimation(self.opacity_anim); self.animation_group.addAnimation(self.drift_anim); self.animation_group.addAnimation(self.scale_anim)
        self.animation_group.setLoopCount(1); self.animation_group.finished.connect(self.on_animation_finish)
        self.manager.add_blob(self)
        self.reposition(is_initial=True)
        if start_delay > 0: QTimer.singleShot(start_delay, self.animation_group.start)
        else: self.animation_group.start()

    def stop(self): self.animation_group.stop(); self.manager.remove_blob(self)
    def on_animation_finish(self): self.reposition(); QTimer.singleShot(random.randint(0, 900), self.animation_group.start)
    def handle_resize(self, w_ratio, h_ratio, scale_ratio):
        self.start_pos = QPointF(self.start_pos.x() * w_ratio, self.start_pos.y() * h_ratio)
        self.end_pos = QPointF(self.end_pos.x() * w_ratio, self.end_pos.y() * h_ratio)
        self.radius *= scale_ratio; self.update_pixmap(); self.set_drift_progress(self._drift_progress)
    def reposition(self, is_initial=False):
        if not is_initial and self.manager.palette: self.color = random.choice(self.manager.palette)
        duration = random.randint(20000, 45000)
        ref_dim = self.manager._coverage_radius_reference()
        self.radius = random.uniform(0.62, 1.08) * ref_dim 
        self.update_pixmap()
        self.start_pos = self.manager.get_new_position(self.radius); self.end_pos = self.manager.get_new_position(self.radius)
        self.opacity_anim.setDuration(duration)
        if is_initial:
            self.opacity_anim.setStartValue(random.uniform(0.24, 0.40))
        else:
            self.opacity_anim.setStartValue(max(self.opacity, 0.18))
        self.opacity_anim.setKeyValueAt(0.5, random.uniform(0.78, 0.96))
        self.opacity_anim.setEndValue(0.18)
        self.drift_anim.setDuration(duration); self.drift_anim.setStartValue(0.0); self.drift_anim.setEndValue(1.0)
        self.scale_anim.setDuration(duration); self.scale_anim.setStartValue(random.uniform(0.8, 1.0)); self.scale_anim.setKeyValueAt(0.5, random.uniform(0.9, 1.2)); self.scale_anim.setEndValue(random.uniform(0.8, 1.0))
    def update_pixmap(self):
        base_size = int(self.radius * 2); max_texture_size = 256 
        size = min(base_size, max_texture_size)
        if size <= 0: return
        cache_key = (size, self._color.rgba())
        cached = Blob._pixmap_cache.get(cache_key)
        if cached is not None:
            self.pixmap = cached
            return

        self.pixmap = QPixmap(size, size); self.pixmap.fill(Qt.transparent)
        painter = QPainter()
        if not painter.begin(self.pixmap):
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            # Keep a visibly solid center, then blur out for a softer lava-lamp edge.
            gradient = QRadialGradient(size / 2, size / 2, size / 2)
            core_color = QColor(self._color)
            mid_color = QColor(self._color)
            edge_color = QColor(self._color)
            outer_color = QColor(self._color)
            core_color.setAlpha(238)
            mid_color.setAlpha(215)
            edge_color.setAlpha(132)
            outer_color.setAlpha(0)
            gradient.setColorAt(0.00, core_color)
            gradient.setColorAt(0.24, core_color)
            gradient.setColorAt(0.55, mid_color)
            gradient.setColorAt(0.82, edge_color)
            gradient.setColorAt(0.96, QColor(self._color.red(), self._color.green(), self._color.blue(), 26))
            gradient.setColorAt(1.00, outer_color)
            painter.setBrush(QBrush(gradient)); painter.setPen(Qt.NoPen); painter.drawEllipse(0, 0, size, size)

            # Add a soft off-center highlight to make blobs read as gel instead of flat glow.
            highlight = QRadialGradient(size * 0.36, size * 0.32, size * 0.46)
            highlight_base = QColor(self._color).lighter(118)
            highlight_inner = QColor(highlight_base.red(), highlight_base.green(), highlight_base.blue(), 34)
            highlight_mid = QColor(highlight_base.red(), highlight_base.green(), highlight_base.blue(), 10)
            highlight_outer = QColor(255, 255, 255, 0)
            highlight.setColorAt(0.00, highlight_inner)
            highlight.setColorAt(0.40, highlight_mid)
            highlight.setColorAt(1.00, highlight_outer)
            painter.setBrush(QBrush(highlight)); painter.setPen(Qt.NoPen); painter.drawEllipse(0, 0, size, size)
        finally:
            painter.end()

        Blob._pixmap_cache[cache_key] = self.pixmap
        Blob._pixmap_cache_order.append(cache_key)
        if len(Blob._pixmap_cache_order) > Blob._pixmap_cache_limit:
            oldest = Blob._pixmap_cache_order.pop(0)
            Blob._pixmap_cache.pop(oldest, None)
    
    def get_opacity(self): return self._opacity
    def set_opacity(self, value): self._opacity = value
    opacity = pyqtProperty(float, fget=get_opacity, fset=set_opacity)
    def get_center(self): return self._center
    def set_center(self, value): self._center = value
    center = pyqtProperty(QPointF, fget=get_center, fset=set_center)
    def get_drift_progress(self): return self._drift_progress
    def set_drift_progress(self, value):
        self._drift_progress = value
        dx = self.end_pos.x() - self.start_pos.x(); dy = self.end_pos.y() - self.start_pos.y()
        self._center = QPointF(self.start_pos.x() + dx * value, self.start_pos.y() + dy * value)
    driftProgress = pyqtProperty(float, fget=get_drift_progress, fset=set_drift_progress)
    def get_scale(self): return self._scale
    def set_scale(self, value): self._scale = value; self.radius_scaled = self.radius * self._scale
    scale = pyqtProperty(float, fget=get_scale, fset=set_scale)
    def get_color(self): return self._color
    def set_color(self, value): self._color = value; self.update_pixmap()
    color = pyqtProperty(QColor, fget=get_color, fset=set_color)
    def change_color_animated(self, new_color):
        self.color_anim.stop(); self.color_anim.setStartValue(self.color); self.color_anim.setEndValue(new_color); self.color_anim.start()
    def graceful_remove(self):
        if self.opacity < 0.05: self.stop(); return
        self.animation_group.stop(); self.death_anim = QPropertyAnimation(self, b"opacity"); self.death_anim.setDuration(1000)
        self.death_anim.setStartValue(self.opacity); self.death_anim.setEndValue(0.0); self.death_anim.setEasingCurve(QEasingCurve.OutQuad)
        self.death_anim.finished.connect(self.stop); self.death_anim.start()

class ResponsiveAlbumArtLabel(QLabel):
    def __init__(self, radius=15, parent=None):
        super().__init__(parent)
        self._radius = radius; self.setMinimumSize(100, 100); self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._border_color = QColor("transparent"); self._border_width = 4; self._opacity = 1.0  
        self._loading_indicator_opacity = 0.0
        self._loading_indicator_anim = QPropertyAnimation(self, b"loadingIndicatorOpacity"); self._loading_indicator_anim.setDuration(400)
        self._scale = 1.0; self._aspect_ratio = 1.0
        self._cached_scaled_pixmap = None; self._cached_art_rect_size = QSize(0, 0)

    def setPixmap(self, pixmap): self._cached_scaled_pixmap = None; super().setPixmap(pixmap)
    def setAspectRatio(self, ratio):
        if self._aspect_ratio != ratio: self._aspect_ratio = ratio; self._cached_scaled_pixmap = None; self.update()
    def setBorderColor(self, color): self._border_color = color; self.update()
    def setOpacity(self, opacity): self._opacity = opacity; self.update()
    @pyqtProperty(float)
    def scale(self): return self._scale
    @scale.setter
    def scale(self, value): self._scale = value; self.update() 
    @pyqtProperty(float)
    def loadingIndicatorOpacity(self): return self._loading_indicator_opacity
    @loadingIndicatorOpacity.setter
    def loadingIndicatorOpacity(self, opacity): self._loading_indicator_opacity = opacity; self.update()
    def setLoadingState(self, is_loading):
        self._loading_indicator_anim.setEndValue(1.0 if is_loading else 0.0); self._loading_indicator_anim.start()

    def paintEvent(self, event):
        pixmap = self.pixmap()
        if not pixmap or pixmap.isNull(): return
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing); painter.setOpacity(self._opacity)
            widget_rect = self.rect()
            if self._aspect_ratio == 1.0:
                size = min(widget_rect.width(), widget_rect.height()); x_offset = (widget_rect.width() - size) / 2; y_offset = (widget_rect.height() - size) / 2; draw_rect = QRectF(x_offset, y_offset, size, size)
            else:
                widget_aspect = widget_rect.width() / widget_rect.height() if widget_rect.height() > 0 else 1.0
                if widget_aspect > self._aspect_ratio: h = widget_rect.height(); w = h * self._aspect_ratio; x = (widget_rect.width() - w) / 2; y = 0
                else: w = widget_rect.width(); h = w / self._aspect_ratio; x = 0; y = (widget_rect.height() - h) / 2
                draw_rect = QRectF(x, y, w, h)
            painter.translate(draw_rect.center()); painter.scale(self._scale, self._scale); painter.translate(-draw_rect.center())
            if self._border_color.alpha() > 0:
                border_draw_rect = draw_rect.adjusted(self._border_width / 2, self._border_width / 2, -self._border_width / 2, -self._border_width / 2)
                border_path = QPainterPath(); border_path.addRoundedRect(border_draw_rect, self._radius, self._radius)
                pen = painter.pen(); pen.setColor(self._border_color); pen.setWidth(self._border_width); painter.setPen(pen); painter.setBrush(Qt.NoBrush); painter.drawPath(border_path)
            art_rect = draw_rect.adjusted(self._border_width, self._border_width, -self._border_width, -self._border_width)
            path = QPainterPath(); path.addRoundedRect(art_rect, self._radius - self._border_width, self._radius - self._border_width); painter.setClipPath(path)
            if self._cached_art_rect_size != art_rect.size() or self._cached_scaled_pixmap is None:
                if art_rect.width() > 0 and art_rect.height() > 0:
                    self._cached_scaled_pixmap = pixmap.scaled(art_rect.size().toSize(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                    self._cached_art_rect_size = art_rect.size()
            if self._cached_scaled_pixmap:
                scaled_width = self._cached_scaled_pixmap.width()
                scaled_height = self._cached_scaled_pixmap.height()

                px = art_rect.left() + (art_rect.width() - scaled_width) / 2
                py = art_rect.top() + (art_rect.height() - self._cached_scaled_pixmap.height()) / 2
                painter.drawPixmap(QPointF(px, py), self._cached_scaled_pixmap)
            if self._loading_indicator_opacity > 0:
                painter.setOpacity(self._loading_indicator_opacity); indicator_rect = QRectF(art_rect.right() - 40, art_rect.top() + 10, 30, 20)
                indicator_bg_path = QPainterPath(); indicator_bg_path.addRoundedRect(indicator_rect, 5, 5); painter.fillPath(indicator_bg_path, QColor(0, 0, 0, 100))
                painter.setPen(QColor(255, 255, 255, 200)); painter.setFont(QFont("Inter", 10, QFont.Bold)); painter.drawText(indicator_rect, Qt.AlignCenter, "HD")
        finally:
            painter.end()

class ScrollingTextLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._text_color = QColor(255, 255, 255, 0); self._scroll_pos = 0; self._full_text = ""; self._is_scrolling = False
        self._border_enabled = False; self._border_color = QColor("black"); self._border_width = 3; self._opacity = 1.0
        self._anim_offset_y = 0.0; self._anim_offset_x = 0.0; self._use_standard_painting = False
        self._text_scale = 1.0
        self._multiline_enabled = False
        self._max_lines = 1
        self._gradient_enabled = False
        self._gradient_color = QColor(255, 255, 255)
        self._gradient_direction = "Left to Right"
        self._scroll_animation = QPropertyAnimation(self, b"scroll_pos"); self._scroll_animation.setLoopCount(-1); self._scroll_animation.setEasingCurve(QEasingCurve.Linear)

    @pyqtProperty(int)
    def scroll_pos(self): return self._scroll_pos
    @scroll_pos.setter
    def scroll_pos(self, value): self._scroll_pos = value; self.update()
    def setText(self, text): self._full_text = text; self.update_scroll(); super().setText(text) 
    def setTextColor(self, color): self._text_color = color; self.update()
    def setBorder(self, enabled, color=None, width=None):
        self._border_enabled = enabled
        if color: self._border_color = QColor(color)
        if width is not None: self._border_width = width
        self.update()
    def get_opacity(self): return self._opacity
    def set_opacity(self, val): self._opacity = val; self.update()
    opacity = pyqtProperty(float, fget=get_opacity, fset=set_opacity)
    def get_anim_offset_y(self): return self._anim_offset_y
    def set_anim_offset_y(self, val): self._anim_offset_y = val; self.update()
    anim_offset_y = pyqtProperty(float, fget=get_anim_offset_y, fset=set_anim_offset_y)
    def get_anim_offset_x(self): return self._anim_offset_x
    def set_anim_offset_x(self, val): self._anim_offset_x = val; self.update()
    anim_offset_x = pyqtProperty(float, fget=get_anim_offset_x, fset=set_anim_offset_x)
    def get_text_scale(self): return self._text_scale
    def set_text_scale(self, val): self._text_scale = val; self.update()
    textScale = pyqtProperty(float, fget=get_text_scale, fset=set_text_scale)
    def setStandardPainting(self, enabled):
        self._use_standard_painting = enabled
        if enabled: self._scroll_animation.stop(); self._is_scrolling = False
        self.update()
    def setMaxLines(self, max_lines=1):
        self._max_lines = max(1, int(max_lines))
        self._multiline_enabled = self._max_lines > 1
        if self._multiline_enabled:
            self._scroll_animation.stop(); self._is_scrolling = False; self.scroll_pos = 0
        self.update_scroll()
        self.update()
    def setGradient(self, enabled=False, secondary_color=None, direction="Left to Right"):
        self._gradient_enabled = bool(enabled)
        if secondary_color is not None:
            self._gradient_color = QColor(secondary_color)
        self._gradient_direction = direction or "Left to Right"
        self.update()
    def _get_gradient_brush(self, text_bounds):
        if not self._gradient_enabled:
            return QBrush(self._text_color)
        secondary = QColor(self._gradient_color)
        secondary.setAlpha(self._text_color.alpha())
        direction = (self._gradient_direction or "Left to Right").lower()
        if direction == "top to bottom":
            gradient = QLinearGradient(text_bounds.center().x(), text_bounds.top(), text_bounds.center().x(), text_bounds.bottom())
        elif direction == "bottom-left to top-right":
            gradient = QLinearGradient(text_bounds.bottomLeft(), text_bounds.topRight())
        elif direction == "top-left to bottom-right":
            gradient = QLinearGradient(text_bounds.topLeft(), text_bounds.bottomRight())
        else:
            gradient = QLinearGradient(text_bounds.left(), text_bounds.center().y(), text_bounds.right(), text_bounds.center().y())
        gradient.setColorAt(0.0, self._text_color)
        gradient.setColorAt(1.0, secondary)
        return QBrush(gradient)
    def _draw_text_item(self, painter, x, y, text):
        path = QPainterPath(); path.addText(x, y, self.font(), text)
        if self._border_enabled:
            pen = QPen(self._border_color); pen.setWidth(self._border_width); pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen); painter.setBrush(Qt.NoBrush); painter.drawPath(path)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._get_gradient_brush(path.boundingRect()))
        painter.drawPath(path)
    def _wrap_text_lines(self, metrics, max_width):
        words = self._full_text.split()
        if not words:
            return [self._full_text] if self._full_text else []
        lines = []
        current_line = words[0]
        for word in words[1:]:
            candidate = f"{current_line} {word}"
            if metrics.width(candidate) <= max_width:
                current_line = candidate
                continue
            lines.append(current_line)
            current_line = word
            if len(lines) >= self._max_lines - 1:
                break
        if len(lines) < self._max_lines:
            remaining_words = []
            if current_line:
                remaining_words.append(current_line)
            processed_count = len(" ".join(lines + ([current_line] if current_line else [])).split())
            if processed_count < len(words):
                remaining_words.extend(words[processed_count:])
            last_line_text = " ".join(remaining_words).strip()
            if last_line_text:
                lines.append(metrics.elidedText(last_line_text, Qt.ElideRight, max_width))
        return lines[:self._max_lines]
    def paintEvent(self, event):
        if self._use_standard_painting: super().paintEvent(event); return
        if not self._full_text: return
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing); painter.setOpacity(self._opacity)
            metrics = QFontMetrics(self.font())
            rect = self.rect()
            center = rect.center()
            painter.save()
            painter.translate(center.x() + self._anim_offset_x, center.y() + self._anim_offset_y)
            painter.scale(self._text_scale, self._text_scale)
            painter.translate(-center.x(), -center.y())

            if self._multiline_enabled:
                max_width = max(1, rect.width())
                lines = self._wrap_text_lines(metrics, max_width)
                if lines:
                    line_height = metrics.height()
                    total_height = len(lines) * line_height
                    base_y = rect.y() + (rect.height() - total_height) // 2 + metrics.ascent()
                    for index, line in enumerate(lines):
                        line_width = metrics.width(line)
                        if self.alignment() & Qt.AlignLeft: x_pos = rect.x()
                        elif self.alignment() & Qt.AlignRight: x_pos = rect.x() + rect.width() - line_width
                        else: x_pos = rect.x() + (rect.width() - line_width) // 2
                        y_pos = base_y + (index * line_height)
                        self._draw_text_item(painter, x_pos, y_pos, line)
            else:
                text_width = metrics.width(self._full_text)
                if self._is_scrolling: x_pos = self._scroll_pos
                else:
                    if self.alignment() & Qt.AlignLeft: x_pos = 0
                    elif self.alignment() & Qt.AlignRight: x_pos = self.width() - text_width
                    else: x_pos = (self.width() - text_width) // 2
                y_pos = (self.height() - metrics.height()) // 2 + metrics.ascent()
                self._draw_text_item(painter, x_pos, y_pos, self._full_text)
                if self._is_scrolling:
                    self._draw_text_item(painter, int(x_pos + text_width + 60), int(y_pos), self._full_text)
            painter.restore()
        finally:
            painter.end()
    def resizeEvent(self, event): super().resizeEvent(event); self.update_scroll()
    def update_scroll(self):
        if self._use_standard_painting or self._multiline_enabled:
            self._scroll_animation.stop(); self._is_scrolling = False; self.scroll_pos = 0
            self.update()
            return
        if not self.isVisible() or not self._full_text: return
        metrics = QFontMetrics(self.font()); text_width = metrics.width(self._full_text); widget_width = self.width()
        should_scroll = text_width > widget_width
        if should_scroll and not self._is_scrolling:
            self._is_scrolling = True; self.scroll_pos = 0
            self._scroll_animation.setStartValue(0); self._scroll_animation.setEndValue(-(text_width + 60)) 
            self._scroll_animation.setDuration(int(text_width * 15)); self._scroll_animation.start()
        elif not should_scroll and self._is_scrolling:
            self._is_scrolling = False; self._scroll_animation.stop(); self.scroll_pos = 0 
        self.update() 

class SmoothProgressBar(QProgressBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextVisible(False)
        self.setFixedHeight(40)
        self.setStyleSheet("QProgressBar { border: none; background: transparent; }")
        self.setRange(0, 100)
        self.setValue(0)
        self._current_val = 0.0
        self._target_val = 0.0
        self._bar_color = QColor(255, 255, 255, 200)
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0.0)
        self.anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.anim.setDuration(500)
        self.anim.setEasingCurve(QEasingCurve.InOutQuad)
        self.hide()

    def setTargetValue(self, val, snap=False):
        self._target_val = float(val)
        if snap or abs(self._target_val - self._current_val) > 3000:
            self._current_val = self._target_val
        self.update()

    def update_smooth_value(self):
        diff = self._target_val - self._current_val
        if abs(diff) < 0.5:
            self._current_val = self._target_val
        else:
            self._current_val += diff * 0.1
        self.update()

    def paintEvent(self, event):
        if self.window().isMinimized(): return
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing)

            # Retrieve styles dynamically from the main window
            border_enabled = getattr(self.window(), '_current_text_border_enabled', False)
            # Use the specific text border size setting, defaulting to 3 if not set
            border_width = getattr(self.window(), '_current_text_border_size', 3) if border_enabled else 0
            border_color_list = getattr(self.window(), '_current_text_border_color', [0,0,0])
            border_color = QColor(*border_color_list)

            widget_rect = self.rect()
            
            # Define visual properties
            fill_height = 6 # Slightly thicker to look distinct
            total_height = fill_height + border_width
            
            # Calculate Y offset to align to bottom, accounting for border
            y_offset = widget_rect.height() - total_height - 2 # 2px padding from bottom
            
            # QPen draws centered on the path, so we inset by half the border width 
            # to ensure the stroke stays within our intended visual bounds.
            inset = border_width / 2.0
            draw_rect = QRectF(
                inset, 
                y_offset + inset, 
                widget_rect.width() - border_width, 
                fill_height
            )

            bg_color = QColor(self._bar_color)
            bg_color.setAlpha(50)

            # Draw Background Fill
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(bg_color))
            painter.drawRoundedRect(draw_rect, 2, 2)

            # Draw Progress Fill
            if self.maximum() > 0:
                ratio = self._current_val / self.maximum()
                ratio = max(0.0, min(1.0, ratio))
                
                progress_width = draw_rect.width() * ratio
                
                if progress_width > 0:
                    progress_rect = QRectF(draw_rect.x(), draw_rect.y(), progress_width, draw_rect.height())
                    painter.setBrush(QBrush(self._bar_color))
                    painter.drawRoundedRect(progress_rect, 2, 2)

            # Draw Border (Outline) on top
            # This ensures the border crisply outlines the bar without the fill overlapping it
            if border_width > 0:
                pen = QPen(border_color)
                pen.setWidth(border_width)
                pen.setJoinStyle(Qt.RoundJoin) 
                pen.setCapStyle(Qt.RoundCap)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(draw_rect, 2, 2)
        finally:
            painter.end()

    def fade_in(self):
        if self.isVisible() and self.opacity_effect.opacity() == 1.0: return
        self.show(); self.anim.stop()
        try: self.anim.finished.disconnect(self.hide)
        except TypeError: pass
        self.anim.setStartValue(self.opacity_effect.opacity()); self.anim.setEndValue(1.0); self.anim.start()

    def fade_out(self):
        if not self.isVisible() or self.opacity_effect.opacity() == 0.0: return
        self.anim.stop()
        try: self.anim.finished.disconnect(self.hide)
        except TypeError: pass
        self.anim.setStartValue(self.opacity_effect.opacity()); self.anim.setEndValue(0.0); self.anim.finished.connect(self.hide); self.anim.start()

    def set_color(self, color):
        if isinstance(color, (tuple, list)): self._bar_color = QColor(*color)
        else: self._bar_color = QColor(color)
        self.update()

class BorderedLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._border_enabled = False; self._border_color = QColor("black"); self._border_width = 3; self._custom_text_color = None
    def setBorder(self, enabled, color, width): self._border_enabled = enabled; self._border_color = QColor(color); self._border_width = width; self.update()
    def setCustomTextColor(self, color): self._custom_text_color = QColor(color); self.update()
    def paintEvent(self, event):
        if not self.text(): return
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            rect = self.rect(); font = self.font(); metrics = QFontMetrics(font); text = self.text(); align = self.alignment()
            x = 0
            if align & Qt.AlignRight: x = rect.width() - metrics.width(text)
            elif align & Qt.AlignHCenter: x = (rect.width() - metrics.width(text)) // 2
            y = (rect.height() - metrics.height()) / 2 + metrics.ascent()
            path = QPainterPath(); path.addText(x, y, font, text)
            if self._border_enabled:
                pen = QPen(self._border_color); pen.setWidth(self._border_width); pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen); painter.setBrush(Qt.NoBrush); painter.drawPath(path)
            painter.setPen(Qt.NoPen); painter.setBrush(self._custom_text_color if self._custom_text_color else self.palette().text().color()); painter.drawPath(path)
        finally:
            painter.end()

class LabelBorderEventFilter(QObject):
    def __init__(self, border_enabled, border_color, border_width, text_color, parent=None):
        super().__init__(parent)
        self.setSettings(border_enabled, border_color, border_width, text_color)
    def setSettings(self, enabled, color, width, text_color):
        self.border_enabled = enabled; self.border_color = QColor(color); self.border_width = width; self.text_color = QColor(text_color)
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Paint:
            if not obj.isEnabled() or obj.property("no_text_border"): return False
            if isinstance(obj, QLabel) and not isinstance(obj, (BorderedLabel, ColorPreviewLabel)):
                if not obj.text(): return False
                painter = QPainter(obj); painter.setRenderHint(QPainter.Antialiasing)
                font = obj.font(); rect = obj.rect(); text = obj.text().replace("&&", "___AMP___").replace("&", "").replace("___AMP___", "&"); metrics = QFontMetrics(font); align = obj.alignment()
                x = 0
                if align & Qt.AlignRight: x = rect.width() - metrics.width(text)
                elif align & Qt.AlignHCenter: x = (rect.width() - metrics.width(text)) / 2
                y = (rect.height() - metrics.height()) / 2 + metrics.ascent()
                if align & Qt.AlignTop: y = metrics.ascent()
                elif align & Qt.AlignBottom: y = rect.height() - metrics.descent()
                path = QPainterPath(); path.addText(x, y, font, text)
                if self.border_enabled:
                    pen = QPen(self.border_color); pen.setWidth(self.border_width); pen.setJoinStyle(Qt.RoundJoin)
                    painter.setPen(pen); painter.setBrush(Qt.NoBrush); painter.drawPath(path)
                painter.setPen(Qt.NoPen); painter.setBrush(self.text_color); painter.drawPath(path)
                return True
            if self.border_enabled and isinstance(obj, (QAbstractButton, QGroupBox)):
                try: obj.paintEvent(event)
                except: return False
                painter = QPainter(obj); painter.setRenderHint(QPainter.Antialiasing)
                font = obj.font(); text = obj.text() if hasattr(obj, 'text') else obj.title()
                text = text.replace("&&", "___AMP___").replace("&", "").replace("___AMP___", "&")
                if not text: return True
                rect = obj.rect(); metrics = QFontMetrics(font); x, y = 0, 0
                if isinstance(obj, QPushButton): x = (rect.width() - metrics.width(text)) / 2; y = (rect.height() - metrics.height()) / 2 + metrics.ascent()
                elif isinstance(obj, (QCheckBox, QRadioButton)): x = 24; y = (rect.height() - metrics.height()) / 2 + metrics.ascent()
                elif isinstance(obj, QGroupBox): x = 15; y = metrics.ascent()
                path = QPainterPath(); path.addText(x, y, font, text)
                pen = QPen(self.border_color); pen.setWidth(self.border_width); pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen); painter.setBrush(Qt.NoBrush); painter.drawPath(path)
                painter.setPen(Qt.NoPen); painter.setBrush(self.text_color); painter.drawPath(path)
                return True
        return False

class ColorPreviewLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._border_enabled = False; self._border_color = QColor("black"); self._custom_text_color = None; self._border_width = 3; self._custom_font = None
    def setBorder(self, enabled, color): self._border_enabled = enabled; self._border_color = QColor(color); self.update()


    def setCustomTextColor(self, color):
        if isinstance(color, (list, tuple)):
            # If it's a list like [255, 255, 255], unpack it
            self._custom_text_color = QColor(*color)
        elif isinstance(color, QColor):
            self._custom_text_color = color
        else:
            # Fallback for hex strings or other valid QColor args
            self._custom_text_color = QColor(color)
        self.update()
    def setBorderSize(self, width): self._border_width = width; self.update()
    def setCustomFont(self, font): self._custom_font = font; self.update()
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.text():
            font = self._custom_font if self._custom_font else self.font()
            painter = QPainter()
            if not painter.begin(self):
                return
            try:
                painter.setRenderHint(QPainter.Antialiasing)
                rect = self.rect(); metrics = QFontMetrics(font); text = self.text()
                x = (rect.width() - metrics.width(text)) / 2; y = (rect.height() - metrics.height()) / 2 + metrics.ascent()
                path = QPainterPath(); path.addText(x, y, font, text)
                if self._border_enabled:
                    pen = QPen(self._border_color); pen.setWidth(self._border_width); pen.setJoinStyle(Qt.RoundJoin)
                    painter.setPen(pen); painter.setBrush(Qt.NoBrush); painter.drawPath(path)
                painter.setPen(Qt.NoPen); painter.setBrush(self._custom_text_color if self._custom_text_color else self.palette().text().color()); painter.drawPath(path)
            finally:
                painter.end()

class NoScrollComboBox(QComboBox):
    def wheelEvent(self, event): event.ignore()


class LyricsLabel(QLabel):
    """Displays a single time-synced lyric line with a crossfade animation on change."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text_color = QColor(255, 255, 255, 255)
        self._border_enabled = False
        self._border_color = QColor("black")
        self._border_width = 3
        self._opacity = 0.0
        self._full_text = ""
        self._pending_text = None
        self._max_lines = 2

        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("background: transparent;")

        self._anim = QPropertyAnimation(self, b"lyricsOpacity")
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)

    # --- opacity property ---
    def _get_opacity(self): return self._opacity
    def _set_opacity(self, val):
        self._opacity = max(0.0, min(1.0, val))
        self.update()
    lyricsOpacity = pyqtProperty(float, fget=_get_opacity, fset=_set_opacity)

    def setTextColor(self, color):
        self._text_color = QColor(color)
        self.update()

    def setMaxLines(self, lines):
        self._max_lines = max(1, int(lines))
        self.update()

    def setBorder(self, enabled, color=None, width=None):
        self._border_enabled = enabled
        if color is not None:
            self._border_color = QColor(color)
        if width is not None:
            self._border_width = width
        self.update()

    # Gradient stub — accepted but unused (keeps the style propagation loop clean)
    def setGradient(self, enabled=False, secondary_color=None, direction=None):
        pass

    def reset(self):
        """Synchronously stop all animations and clear state.
        Caller is responsible for calling show() or hide() afterwards.
        """
        self._anim.stop()
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self._pending_text = None
        self._full_text = ""
        super().setText("")
        self._opacity = 0.0
        self.update()

    def setLine(self, text):
        """Set a new lyric line, crossfading if the text has changed."""
        if text == self._full_text:
            return
        if self._opacity > 0.01 and self._full_text:
            # Fade out current text, then swap and fade in
            self._pending_text = text
            self._anim.stop()
            self._anim.setDuration(180)
            self._anim.setStartValue(self._opacity)
            self._anim.setEndValue(0.0)
            try:
                self._anim.finished.disconnect()
            except TypeError:
                pass
            self._anim.finished.connect(self._swap_and_fade_in)
            self._anim.start()
        else:
            self._full_text = text
            super().setText(text)
            self._fade_in()

    def _swap_and_fade_in(self):
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        if self._pending_text is not None:
            self._full_text = self._pending_text
            super().setText(self._pending_text)
            self._pending_text = None
        self._fade_in()

    def _fade_in(self):
        self.show()  # Ensure visible (e.g. after hideLine collapsed the widget)
        self._anim.stop()
        self._anim.setDuration(250)
        self._anim.setStartValue(self._opacity)
        self._anim.setEndValue(1.0)
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self._anim.start()

    def showLine(self):
        """Make the widget visible and fade in the current text."""
        self.show()
        self._fade_in()

    def clearLine(self):
        """Fade out the current line for a break in the song (widget stays visible in layout)."""
        if self._opacity < 0.01:
            self._full_text = ""
            super().setText("")
            return
        self._anim.stop()
        self._anim.setDuration(500)
        self._anim.setStartValue(self._opacity)
        self._anim.setEndValue(0.0)
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self._anim.finished.connect(self._on_cleared)
        self._anim.start()

    def _on_cleared(self):
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self._full_text = ""
        super().setText("")

    def hideLine(self):
        """Fade out and hide (collapses layout space — used for no-lyrics / idle)."""
        if not self.isVisible() or self._opacity < 0.01:
            self.hide()
            return
        self._anim.stop()
        self._anim.setDuration(200)
        self._anim.setStartValue(self._opacity)
        self._anim.setEndValue(0.0)
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self._anim.finished.connect(self.hide)
        self._anim.start()

    def _text_width(self, metrics, text):
        if hasattr(metrics, "horizontalAdvance"):
            return metrics.horizontalAdvance(text)
        return metrics.width(text)

    def _wrap_text_lines(self, metrics, text, max_width):
        paragraphs = text.splitlines() or [text]
        lines = []

        for paragraph in paragraphs:
            words = paragraph.split()
            if not words:
                if paragraph.strip() == "":
                    continue
                words = [paragraph]

            current = words[0]
            if self._text_width(metrics, current) > max_width:
                current = metrics.elidedText(current, Qt.ElideRight, max_width)

            for word in words[1:]:
                candidate = f"{current} {word}"
                if self._text_width(metrics, candidate) <= max_width:
                    current = candidate
                else:
                    lines.append(current)
                    current = word
                    if self._text_width(metrics, current) > max_width:
                        current = metrics.elidedText(current, Qt.ElideRight, max_width)

            lines.append(current)

        if not lines:
            return []

        if len(lines) > self._max_lines:
            head = lines[: self._max_lines - 1]
            tail = " ".join(lines[self._max_lines - 1 :])
            tail = metrics.elidedText(tail, Qt.ElideRight, max_width)
            return head + [tail]

        return lines

    def paintEvent(self, event):
        if not self._full_text or self._opacity < 0.01:
            return
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            # Bake local fade opacity into color alphas so QGraphicsDropShadowEffect
            # correctly picks up the transparency when rendering its shadow blur.
            alpha_scale = self._opacity
            text_color = QColor(self._text_color)
            text_color.setAlphaF(text_color.alphaF() * alpha_scale)
            border_color = QColor(self._border_color)
            border_color.setAlphaF(border_color.alphaF() * alpha_scale)
            metrics = QFontMetrics(self.font())
            rect = self.rect()
            max_width = max(24, rect.width() - 10)
            lines = self._wrap_text_lines(metrics, self._full_text, max_width)
            if not lines:
                return

            line_height = metrics.height()
            line_gap = 2
            total_height = (line_height * len(lines)) + (line_gap * max(0, len(lines) - 1))
            y = (rect.height() - total_height) / 2 + metrics.ascent()

            for line in lines:
                x = (rect.width() - self._text_width(metrics, line)) / 2
                path = QPainterPath()
                path.addText(x, y, self.font(), line)

                if self._border_enabled:
                    pen = QPen(border_color)
                    pen.setWidth(self._border_width)
                    pen.setJoinStyle(Qt.RoundJoin)
                    painter.setPen(pen)
                    painter.setBrush(Qt.NoBrush)
                    painter.drawPath(path)

                painter.setPen(Qt.NoPen)
                painter.setBrush(text_color)
                painter.drawPath(path)
                y += line_height + line_gap
        finally:
            painter.end()

class CircularButton(QPushButton):
    def __init__(self, tooltip="", icon_char="", parent=None):
        super().__init__("", parent)
        self.setFixedSize(50, 50)
        self.setToolTip(tooltip)
        
        # Set icon character (emoji or symbol)
        if icon_char:
            self.setText(icon_char)
            font = self.font()
            font.setPointSize(18)
            self.setFont(font)
        
        self.setStyleSheet("""
            QPushButton { 
                background-color: rgba(20, 20, 20, 0.6); 
                border: 1px solid rgba(255, 255, 255, 0.7); 
                border-radius: 25px; 
                color: white; 
                font-weight: bold;
            }
            QPushButton:hover { 
                background-color: rgba(40, 40, 40, 0.8); 
                border: 1px solid white; 
            }
            QPushButton:pressed { 
                background-color: rgba(0, 0, 0, 0.6); 
            }
        """)

# --- NEW ADDITIONS BELOW ---

class FontFamilyDelegate(QStyledItemDelegate):
    """
    Optimized delegate that renders the font name in its own font family.
    Only creates QFont objects for items currently visible on screen.
    """
    def paint(self, painter, option, index):
        font_family = index.data(Qt.DisplayRole)
        if font_family:
            # Create a lightweight font object just for painting this item
            my_font = QFont(font_family)
            my_font.setPointSize(10) # Keep size consistent
            option.font = my_font
        super().paint(painter, option, index)

class FontStyleDelegate(QStyledItemDelegate):
    """
    Optimized delegate that renders the font style (Bold, Italic) 
    using the currently selected family from the parent dropdown.
    """
    def __init__(self, family_getter, parent=None):
        super().__init__(parent)
        self.family_getter = family_getter

    def paint(self, painter, option, index):
        style_name = index.data(Qt.DisplayRole)
        current_family = self.family_getter()
        
        if style_name and current_family:
            # Attempt to find the specific style for the current family
            db = QFontDatabase()
            # 10 is a default point size, we just want the style visual
            styled_font = db.font(current_family, style_name, 10)
            
            # Fallback: if the specific style returns a generic font (meaning it wasn't found),
            # we try to manually apply common styles for visual feedback.
            if db.isSmoothlyScalable(current_family, style_name):
                 option.font = styled_font
            else:
                 # Manually simulate if exact match fails (rare but safe)
                 option.font.setFamily(current_family)
                 if "Bold" in style_name: option.font.setBold(True)
                 if "Italic" in style_name: option.font.setItalic(True)


class PlayerControlsBar(QWidget):
    """A row of optional playback control buttons rendered below the lyrics area.

    Available buttons (all individually configurable via settings):
        • play_pause   – toggle playback
        • shuffle      – toggle shuffle
        • repeat       – cycle repeat mode (off → context → track)
        • add_playlist – add current track to a playlist
        • liked        – toggle liked / heart status

    Signals are emitted so the main window can perform the actual API calls.
    """

    play_pause_clicked   = pyqtSignal()
    shuffle_clicked      = pyqtSignal()
    repeat_clicked       = pyqtSignal()
    add_playlist_clicked = pyqtSignal()
    liked_clicked        = pyqtSignal()

    # Button ids in display order
    BUTTON_ORDER = ["play_pause", "shuffle", "repeat", "add_playlist", "liked"]

    # (normal icon, active icon, tooltip)
    BUTTON_META = {
        "play_pause":   ("▶",  "⏸",  "Play / Pause"),
        "shuffle":      ("⇄",  "⇄",  "Toggle Shuffle"),
        "repeat":       ("↻",  "↻",  "Cycle Repeat"),
        "add_playlist": ("＋", "＋", "Add to Playlist"),
        "liked":        ("♡",  "♥",  "Add to Liked Songs"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(44)

        self._text_color = QColor(255, 255, 255)
        self._active_states: dict = {k: False for k in self.BUTTON_ORDER}
        self._repeat_mode = "off"  # 'off', 'context', 'track'
        self._visible_buttons: set = set(self.BUTTON_ORDER)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._layout.addStretch()

        self._buttons: dict = {}
        for key in self.BUTTON_ORDER:
            btn = QPushButton(self.BUTTON_META[key][0])
            btn.setFixedSize(40, 36)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setToolTip(self.BUTTON_META[key][2])
            btn.setObjectName(f"pcb_{key}")
            self._layout.addWidget(btn)
            self._buttons[key] = btn

        self._layout.addStretch()

        self._buttons["play_pause"].clicked.connect(self.play_pause_clicked)
        self._buttons["shuffle"].clicked.connect(self.shuffle_clicked)
        self._buttons["repeat"].clicked.connect(self.repeat_clicked)
        self._buttons["add_playlist"].clicked.connect(self.add_playlist_clicked)
        self._buttons["liked"].clicked.connect(self.liked_clicked)

        self._apply_styles()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def set_visible_buttons(self, buttons: set):
        """Show only the buttons in *buttons* (subset of BUTTON_ORDER)."""
        self._visible_buttons = set(buttons)
        for key, btn in self._buttons.items():
            btn.setVisible(key in self._visible_buttons)
        # Hide the whole bar if no buttons are enabled
        any_visible = bool(self._visible_buttons)
        self.setVisible(any_visible)

    def set_text_color(self, color: QColor):
        self._text_color = color
        self._apply_styles()

    def set_is_playing(self, playing: bool):
        self._active_states["play_pause"] = playing
        self._update_button_icon("play_pause")
        self._apply_styles()

    def set_shuffle(self, enabled: bool):
        self._active_states["shuffle"] = enabled
        self._apply_styles()

    def set_repeat_mode(self, mode: str):
        """mode: 'off', 'context', or 'track'"""
        self._repeat_mode = mode
        self._active_states["repeat"] = (mode != "off")
        repeat_icons = {"off": "↻", "context": "↻", "track": "↺"}
        icon = repeat_icons.get(mode, "↻")
        self._buttons["repeat"].setText(icon)
        self._apply_styles()

    def set_liked(self, liked: bool):
        self._active_states["liked"] = liked
        self._update_button_icon("liked")
        self._apply_styles()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _update_button_icon(self, key: str):
        is_active = self._active_states.get(key, False)
        icon = self.BUTTON_META[key][1] if is_active else self.BUTTON_META[key][0]
        self._buttons[key].setText(icon)

    def _apply_styles(self):
        base_r = self._text_color.red()
        base_g = self._text_color.green()
        base_b = self._text_color.blue()
        base_a = self._text_color.alpha()
        normal_color   = f"rgba({base_r},{base_g},{base_b},{base_a})"
        # Active: slightly brighter / more opaque
        active_color   = f"rgba({min(255,base_r+30)},{min(255,base_g+30)},{min(255,base_b+30)},255)"
        hover_bg       = f"rgba({base_r},{base_g},{base_b},40)"
        pressed_bg     = f"rgba({base_r},{base_g},{base_b},70)"

        for key, btn in self._buttons.items():
            is_active = self._active_states.get(key, False)
            fg = active_color if is_active else normal_color
            btn.setStyleSheet(
                f"QPushButton#{btn.objectName()} {{"
                f"  background: transparent;"
                f"  border: none;"
                f"  border-radius: 8px;"
                f"  font-size: 18px;"
                f"  color: {fg};"
                f"}}"
                f"QPushButton#{btn.objectName()}:hover {{"
                f"  background: {hover_bg};"
                f"}}"
                f"QPushButton#{btn.objectName()}:pressed {{"
                f"  background: {pressed_bg};"
                f"}}"
            )
        super().paint(painter, option, index)

# [ADD THIS CLASS AT THE END OF widgets.py]
from PyQt5.QtWidgets import QTabBar, QStyle, QStylePainter, QStyleOptionTab

class BorderedTabBar(QTabBar):
    """
    A custom TabBar that draws text borders on tabs based on settings.
    Selected tab uses the saved text color and removes border for clarity.
    Other tabs apply text border if enabled, using the border color.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.text_color = QColor("white")
        self.bg_color = QColor("black")
        self.border_color = QColor("black")
        self.border_width = 2
        self.border_enabled = False

    def setColors(self, text_color, bg_color, border_color=None, border_enabled=False):
        self.text_color = QColor(text_color)
        self.bg_color = QColor(bg_color)
        if border_color:
            self.border_color = QColor(border_color)
        self.border_enabled = border_enabled
        self.update()

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionTab()

        for index in range(self.count()):
            self.initStyleOption(option, index)
            
            # Temporarily clear text so the default style doesn't draw it
            tab_text = option.text
            option.text = ""
            painter.drawControl(QStyle.CE_TabBarTab, option)
            
            # Restore text for manual painting
            option.text = tab_text
            painter.save()
            
            rect = self.tabRect(index)
            painter.setFont(self.font())
            
            if index == self.currentIndex():
                # --- SELECTED TAB: Use text color, no border ---
                metrics = painter.fontMetrics()
                x = rect.center().x() - (metrics.width(tab_text) / 2)
                y = rect.center().y() + (metrics.ascent() / 2) - 1
                
                painter.setPen(self.text_color)
                painter.drawText(int(x), int(y), tab_text)
            else:
                # --- UNSELECTED TABS: Apply border if enabled ---
                if self.border_enabled:
                    # Draw with border outline
                    metrics = painter.fontMetrics()
                    x = rect.center().x() - (metrics.width(tab_text) / 2)
                    y = rect.center().y() + (metrics.ascent() / 2) - 1
                    
                    path = QPainterPath()
                    path.addText(x, y, self.font(), tab_text)
                    
                    # Draw Outline (Border Color)
                    pen = QPen(self.border_color)
                    pen.setWidth(self.border_width)
                    pen.setJoinStyle(Qt.RoundJoin)
                    painter.setPen(pen)
                    painter.setBrush(Qt.NoBrush)
                    painter.drawPath(path)
                    
                    # Draw Fill (Text Color)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(self.text_color)
                    painter.drawPath(path)
                else:
                    # Standard text draw
                    painter.setPen(self.text_color)
                    painter.drawText(rect, Qt.AlignCenter, tab_text)

            painter.restore()