from PyQt5.QtGui import QColor

from config import ENABLE_OPENGL_BACKGROUND, FORCE_RASTER_BACKGROUND, LAVA_LAMP_INTENSITY, LAVA_LAMP_PRESET
from utils import detect_opengl_background_support
from .gl_widget import LavaLampGLWidget


class BackgroundRendererController:
    """Chooses and manages raster or OpenGL background rendering at runtime."""

    def __init__(self, host):
        self.host = host
        self._parent_widget = getattr(host, "container", None) or host
        self._prefer_gl = bool(ENABLE_OPENGL_BACKGROUND)
        self._force_raster = bool(FORCE_RASTER_BACKGROUND)
        self._capture_safe_mode = False
        self._supports_gl, self._support_reason = detect_opengl_background_support()
        self._gl_widget = None
        self._use_gl = False

        if self._prefer_gl and not self._force_raster and self._supports_gl:
            try:
                self._gl_widget = LavaLampGLWidget(self._parent_widget, intensity=LAVA_LAMP_INTENSITY)
                self._gl_widget.set_style_preset(LAVA_LAMP_PRESET)
                self._gl_widget.setObjectName("lavaLampBackground")
                self._gl_widget.setGeometry(self._parent_widget.rect())
                self._gl_widget.hide()
                self._gl_widget.lower()
            except Exception as exc:
                self._gl_widget = None
                self._supports_gl = False
                self._support_reason = f"OpenGL widget init failed: {exc}"

    @property
    def support_reason(self):
        return self._support_reason

    @property
    def supports_gl(self):
        return self._supports_gl and self._gl_widget is not None

    @property
    def uses_opengl(self):
        return self._use_gl and self._gl_widget is not None

    def set_capture_safe_mode(self, enabled):
        self._capture_safe_mode = bool(enabled)

    def update_mode(self, is_wallpaper_mode, is_custom_windowed_mode):
        force_raster = self._force_raster or self._capture_safe_mode
        should_use_gl = self.supports_gl and not force_raster and not is_wallpaper_mode and not is_custom_windowed_mode
        if should_use_gl == self._use_gl:
            return False

        self._use_gl = should_use_gl
        if not self._gl_widget:
            return

        if self._use_gl:
            print("Background renderer mode: OpenGL")
            self._gl_widget.setGeometry(self._parent_widget.rect())
            self._gl_widget.show()
            self._gl_widget.lower()
        else:
            if force_raster:
                reason = "capture-safe/forced-raster"
            elif is_wallpaper_mode or is_custom_windowed_mode:
                reason = "wallpaper/custom-window"
            else:
                reason = self._support_reason
            print(f"Background renderer mode: Raster ({reason})")
            self._gl_widget.hide()
        return True

    def set_palette(self, blob_colors):
        if self._gl_widget:
            self._gl_widget.set_palette(blob_colors)

    def set_background_color(self, color):
        if self._gl_widget:
            self._gl_widget.set_base_color(QColor(color))

    def set_style_preset(self, preset_name):
        if self._gl_widget:
            self._gl_widget.set_style_preset(preset_name)

    def resize(self, rect):
        if self._gl_widget:
            target = self._parent_widget.rect() if self._parent_widget else rect
            self._gl_widget.setGeometry(target)

    def tick(self):
        if self._use_gl and self._gl_widget:
            if getattr(self._gl_widget, "initialization_failed", False):
                self._support_reason = "Lava shader init failed at runtime"
                self._use_gl = False
                self._gl_widget.hide()
                return
            self._gl_widget.advance()

    def set_active(self, is_active):
        if self._gl_widget:
            self._gl_widget.set_animation_paused(not bool(is_active))

    def teardown(self):
        if self._gl_widget:
            self._gl_widget.hide()
            self._gl_widget.deleteLater()
            self._gl_widget = None
            self._use_gl = False
