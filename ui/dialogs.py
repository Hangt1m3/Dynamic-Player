# ui/dialogs.py
import sys
import os
import json
import base64
import io
from PIL import Image
from PyQt5.QtCore import (Qt, pyqtSignal, QTimer, QRectF, QPoint, QSize, QEvent, QBuffer, 
                          QEasingCurve, QPropertyAnimation, QParallelAnimationGroup, 
                          QSettings, QProcess, pyqtSlot, QDir, QThreadPool)
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QWidget, 
                             QSizePolicy, QScrollArea, QCheckBox, QGroupBox, QFormLayout, 
                             QComboBox, QSlider, QTableWidget, QTableWidgetItem, QAbstractItemView, 
                             QTextBrowser, QFrame, QColorDialog, QFileDialog, QTabWidget, 
                             QSizeGrip, QGraphicsDropShadowEffect, QRadioButton, QLineEdit, 
                             QApplication, QAbstractButton)
from PyQt5.QtGui import (QPainter, QPainterPath, QPen, QColor, QFont, QFontDatabase, 
                         QGuiApplication, QPixmap, QImage)

from ui.styles import get_common_stylesheet
from ui.widgets import (BorderedLabel, LabelBorderEventFilter, ColorPreviewLabel, 
                        NoScrollComboBox, FontFamilyDelegate, FontStyleDelegate)
from ui.overlays import NotificationWidget
from services import ColorCache
from workers import GitHubUpdatesWorker, GoveeDeviceFinderWorker
from utils import get_contrast_ratio, get_best_text_color, get_best_border_color, extract_palette_from_image
from config import SPOTIPY_REDIRECT_URI, GITHUB_TOKEN

class ThemedDialog(QDialog):
    # Copy the ThemedDialog implementation from original code
    def __init__(self, parent=None, title="", bg_color=None, text_color=None, accent_color=None, border_enabled=False, border_color=None, border_width=3):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowSystemMenuHint)
        self.setObjectName("ThemedDialog"); self.setAttribute(Qt.WA_TranslucentBackground)
        self.bg_color = bg_color or QColor(30, 30, 30); self.text_color = text_color or QColor(255, 255, 255)
        self.accent_color = accent_color or QColor(100, 100, 100); self.border_enabled = border_enabled
        self.border_color = border_color or QColor("black"); self.border_width = border_width; self.drag_pos = None
        self._main_layout = QVBoxLayout(self); self._main_layout.setContentsMargins(0, 0, 0, 0); self._main_layout.setSpacing(0)

        self.title_bar = QWidget(); self.title_bar.setFixedHeight(40); title_layout = QHBoxLayout(self.title_bar); title_layout.setContentsMargins(15, 0, 10, 0)
        self.title_label = BorderedLabel(title); self.title_label.setBorder(self.border_enabled, self.border_color, self.border_width)
        self.title_label.setCustomTextColor(self.text_color); self.title_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.close_btn = QPushButton("×"); self.close_btn.setFixedSize(30, 30); self.close_btn.setCursor(Qt.PointingHandCursor); self.close_btn.clicked.connect(self.reject)
        self.close_btn.setStyleSheet(f"QPushButton {{ border: none; background: transparent; font-size: 20px; color: {self.text_color.name()}; }} QPushButton:hover {{ color: #ff5555; background: transparent; border: none; }}")
        title_layout.addWidget(self.title_label); title_layout.addStretch(); title_layout.addWidget(self.close_btn)
        self._main_layout.addWidget(self.title_bar); self.content_widget = QWidget(); self.content_layout = QVBoxLayout(self.content_widget); self.content_layout.setContentsMargins(20, 10, 20, 20); self._main_layout.addWidget(self.content_widget)
        self.apply_theme()
    def apply_theme(self): self.setStyleSheet(get_common_stylesheet(self.bg_color, self.text_color, self.accent_color)); self.update()
    def paintEvent(self, event):
        if self.isMinimized(): return
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing); path = QPainterPath(); path.addRoundedRect(QRectF(self.rect()), 12, 12)
        painter.fillPath(path, self.bg_color); painter.setPen(QPen(self.accent_color, 1)); painter.drawPath(path)
    def mousePressEvent(self, event):

        if event.button() == Qt.LeftButton and event.y() < 50: self.drag_pos = event.globalPos() - self.frameGeometry().topLeft(); event.accept()
    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_pos: self.move(event.globalPos() - self.drag_pos); event.accept()
    def mouseReleaseEvent(self, event): self.drag_pos = None

class ThemedMessageBox(ThemedDialog):
    # Copy ThemedMessageBox implementation...
    def __init__(self, title, message, buttons=None, parent=None, bg_color=None, text_color=None, accent_color=None, border_enabled=False, border_color=None, border_width=3):
        super().__init__(parent, title, bg_color, text_color, accent_color, border_enabled, border_color, border_width)
        msg_label = BorderedLabel(message); msg_label.setBorder(border_enabled, self.border_color, border_width); msg_label.setCustomTextColor(self.text_color); msg_label.setWordWrap(True); self.content_layout.addWidget(msg_label)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        if not buttons: buttons = [("OK", QDialog.Accepted)]
        for btn_text, role in buttons:
            btn = QPushButton(btn_text); btn.clicked.connect(lambda checked, r=role: self.finish(r)); btn_layout.addWidget(btn)
        self.content_layout.addLayout(btn_layout)
    def finish(self, result): self.done(result)

# ... [Include SaveConfirmationDialog, FramelessColorDialog, FramelessFileDialog here] ...

class SpotifySetupDialog(ThemedDialog):
    def __init__(self, parent=None, bg_color=None, text_color=None, accent_color=None, border_enabled=False, border_color=None, border_width=3):
        super().__init__(parent, "Spotify API Setup", bg_color, text_color, accent_color, border_enabled, border_color, border_width)
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        id_label = QLabel("Client ID:"); secret_label = QLabel("Client Secret:")
        self.id_input = QLineEdit(); self.secret_input = QLineEdit()
        self.id_input.setEchoMode(QLineEdit.Password);self.secret_input.setEchoMode(QLineEdit.Password)
        
        # Load existing credentials
        settings = QSettings("SpotifySync", "App")
        self.id_input.setText(settings.value("spotify_client_id", ""))
        self.secret_input.setText(settings.value("spotify_client_secret", ""))
        
        form_layout = QFormLayout(); form_layout.addRow(id_label, self.id_input); form_layout.addRow(secret_label, self.secret_input)
        layout.addLayout(form_layout);
        
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save"); save_btn.setDefault(True); save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel"); cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch();btn_layout.addWidget(cancel_btn);btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)
        self.content_layout.addLayout(layout)

    def accept(self):
        settings = QSettings("SpotifySync", "App")
        settings.setValue("spotify_client_id", self.id_input.text().strip())
        settings.setValue("spotify_client_secret", self.secret_input.text().strip())
        super().accept()

# Important: FramelessColorDialog and FramelessFileDialog need to inherit similar painting logic as ThemedDialog.
# Copy them from the original code exactly.

class SaveConfirmationDialog(ThemedDialog):
    def __init__(self, settings_list, bg_color, accent_color, text_color, parent=None):
        super().__init__(parent, "Confirm Settings to Save", bg_color, text_color, accent_color)
        self.settings_list = settings_list
        self.selected_keys = []
        
        # We use self.content_layout from ThemedDialog
        layout = self.content_layout
        
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget(); self.form_layout = QVBoxLayout(content); scroll.setWidget(content)
        layout.addWidget(scroll)

        self.checkboxes = {}
        for item in settings_list:
            cb = QCheckBox(item['label']); cb.setChecked(item['changed']); self.checkboxes[item['key']] = cb; self.form_layout.addWidget(cb)
            
        btn_layout = QHBoxLayout()
        select_all_btn = QPushButton("Select All"); select_all_btn.clicked.connect(self.select_all)
        save_btn = QPushButton("Save Selected"); save_btn.setDefault(True); save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel");cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(select_all_btn); btn_layout.addStretch(); btn_layout.addWidget(cancel_btn); btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def select_all(self):
        for cb in self.checkboxes.values():
            cb.setChecked(True)
        
    def accept(self, *args):
        self.selected_keys = [k for k, cb in self.checkboxes.items() if cb.isChecked()]
        super().accept()

class FramelessColorDialog(QColorDialog):
    def __init__(self, parent=None, bg_color=None, accent_color=None, text_color=None, border_enabled=False, border_color=None, border_width=3):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.bg_color = bg_color or QColor(30, 30, 30)
        self.accent_color = accent_color or QColor(100, 100, 100)
        self.text_color = text_color or QColor(255, 255, 255)
        self.border_enabled = border_enabled
        self.border_color = border_color or QColor("black")
        self.border_width = border_width
        self.drag_pos = None

        self.border_filter = LabelBorderEventFilter(self.border_enabled, self.border_color, self.border_width, self.text_color, self)
        self._install_filter_recursive(self)

        # FIX: Apply specific stylesheet to ensure buttons are readable and UI matches theme
        btn_bg = self.bg_color.lighter(130).name()
        btn_hover = self.accent_color.name()
        txt_col = self.text_color.name()
        
        self.setStyleSheet(f"""
            QDialog {{ background: transparent; }}
            QLabel {{ color: {txt_col}; }}
            
            /* Target both standard push buttons and those inside a button box */
            QPushButton {{
                background-color: {btn_bg};
                color: {txt_col};
                border: 1px solid {self.border_color.name() if self.border_enabled else '#555'};
                border-radius: 4px;
                padding: 4px 12px;
                min-width: 60px;
                min-height: 20px;
            }}
            QPushButton:hover {{
                background-color: {btn_hover};
                color: {self.bg_color.name()};
            }}
            /* Specific fix for standard QColorDialog input fields if visible */
            QLineEdit {{
                color: {txt_col};
                background-color: {self.bg_color.darker(120).name()};
                border: 1px solid #555;
            }}
            /* Ensure the abstract color picker widgets don't get messed up */
            QAbstractSpinBox {{
                 color: {txt_col};
                 background-color: {self.bg_color.darker(120).name()};
            }}
        """)

    def showEvent(self, event):
        super().showEvent(event)
        # FIX: Rename "Custom colors" to "Recent colors"
        # We search specifically for the Label that holds this text
        for label in self.findChildren(QLabel):
            if "Custom colors" in label.text():
                label.setText(label.text().replace("Custom colors", "Recent colors"))

    def _install_filter_recursive(self, widget):
        for child in widget.children():
            if isinstance(child, QLabel):
                child.installEventFilter(self.border_filter)
            if isinstance(child, QWidget):
                self._install_filter_recursive(child)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 12, 12)
        painter.fillPath(path, self.bg_color)
        painter.setPen(QPen(self.accent_color, 1))
        painter.drawPath(path)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_pos:
            self.move(event.globalPos() - self.drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_pos = None
        super().mouseReleaseEvent(event)

class FramelessFileDialog(QFileDialog):
    def __init__(self, parent=None, caption="", directory="", filter="", bg_color=None, accent_color=None, text_color=None, border_enabled=False, border_color=None, border_width=3):
        super().__init__(parent, caption, directory, filter)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setOptions(QFileDialog.DontUseNativeDialog)
        self.bg_color = bg_color or QColor(30, 30, 30)
        self.accent_color = accent_color or QColor(100, 100, 100)
        self.text_color = text_color or QColor(255, 255, 255)
        self.border_enabled = border_enabled
        self.border_color = border_color or QColor("black")
        self.border_width = border_width
        self.drag_pos = None

        self.border_filter = LabelBorderEventFilter(self.border_enabled, self.border_color, self.border_width, self.text_color, self)
        self._install_filter_recursive(self)

    def _install_filter_recursive(self, widget):
        for child in widget.children():
            if isinstance(child, QLabel):
                child.installEventFilter(self.border_filter)
            if isinstance(child, QWidget):
                self._install_filter_recursive(child)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 12, 12)
        painter.fillPath(path, self.bg_color)
        painter.setPen(QPen(self.accent_color, 1))
        painter.drawPath(path)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_pos:
            self.move(event.globalPos() - self.drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_pos = None
        super().mouseReleaseEvent(event)

class ColorEditorDialog(QDialog):
    """A dialog for viewing and manually setting an album's color."""
    config_saved = pyqtSignal(str, dict) # album_id, {"palette": ..., "text_color": ...}
    art_changed = pyqtSignal(str, str, str) # album_id, track_id, image_path

    def __init__(self, album_art_pixmap, album_id, track_id, color_cache, parent = None, media_source = 'spotify'):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Tool)
        self.setObjectName("ThemedDialog") 
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

        # Animation for content updates when the track changes
        self.content_update_animation = QPropertyAnimation(self, b"windowOpacity")
        self.content_update_animation.setDuration(300) # Quick fade
        self.content_update_animation.setEasingCurve(QEasingCurve.InOutQuad)

        self.album_id = album_id
        self.track_id = track_id
        self.media_source = media_source
        self.color_cache = color_cache
        self.govee_devices = parent.govee_devices
        self.threadpool = QThreadPool()        
        self.drag_pos = QPoint()
        self._last_stylesheet_params = None
        self.blob_picker_widgets = []
        self._current_styles_family = None
        self.ui_labels = []
        self._loading_state = False

        # Event filter for applying borders to all standard widgets
        self.ui_event_filter = LabelBorderEventFilter(False, "black", 3, "white", self)

        self._font_list_populated = False

        track_cache = self.color_cache.get_album_data(self.track_id) or {}
        cached_data = track_cache or self.color_cache.get_album_data(self.album_id) or {}
        main_window_state = self.parent()

        # Ensure cached_data is a dict (handle legacy list format)
        if isinstance(cached_data, list):
            ui_palette = [cached_data] if not isinstance(cached_data[0], list) else cached_data
            cached_data = {"ui_palette": ui_palette}
        self.cached_data = cached_data
        self.commits_data = []
        
        # --- 1. LOAD INITIAL STATE ---
        ui_palette = cached_data.get("ui_palette", main_window_state._current_ui_palette or [[30, 30, 30], [100, 100, 100]])
        player_bg_color_rgb = cached_data.get("player_bg_color")

        # Initialize UI Colors first to calculate dependent auto colors correctly
        self.ui_bg_color = QColor(*player_bg_color_rgb) if player_bg_color_rgb else QColor(*ui_palette[0])
        self.ui_accent_color = QColor(*ui_palette[1]) if len(ui_palette) > 1 else self.ui_bg_color.lighter(150)

        text_color_rgb = cached_data.get("text_color") # Get raw value
        self.is_text_color_auto = text_color_rgb is None

        if self.is_text_color_auto:
            # Use current player text color if available to match auto-generated state
            if hasattr(main_window_state, '_current_text_color') and main_window_state._current_text_color:
                text_color = main_window_state._current_text_color
            else:
                text_color = get_best_text_color(self.ui_bg_color.getRgb()[:3], self.ui_accent_color.getRgb()[:3])
        else:
            text_color = text_color_rgb

        blob_palette = cached_data.get("blob_palette", main_window_state._current_blob_palette)
        self.blob_density = main_window_state.blob_density
        
        settings = QSettings("SpotifySync", "App")
        self.initial_default_progress_bar_enabled = settings.value("default_progress_bar_enabled", "false") == "true"
        self.initial_default_text_border_size = int(settings.value("default_text_border_size", 3))
        
        progress_bar_val = cached_data.get("progress_bar_enabled")
        self.is_progress_bar_overridden = progress_bar_val is not None
        progress_bar_enabled = progress_bar_val if self.is_progress_bar_overridden else self.initial_default_progress_bar_enabled
        
        shadow_enabled = cached_data.get("shadow_enabled", main_window_state._current_shadow_enabled)
        lights_config = cached_data.get("lights_config", {})
        db = QFontDatabase()
        title_case = cached_data.get("title_case", "default")
        artist_case = cached_data.get("artist_case", "default")
        
        cached_font_family = cached_data.get("font_family")
        self.is_font_family_overridden = cached_font_family is not None
        font_family = cached_font_family if self.is_font_family_overridden else main_window_state._current_font_family
        
        cached_font_style = cached_data.get("font_style")
        font_style = cached_font_style if self.is_font_family_overridden else main_window_state._current_font_style
        
        cached_font_size = cached_data.get("font_size_scale")
        self.is_font_size_overridden = cached_font_size is not None
        font_size_scale = cached_font_size if self.is_font_size_overridden else main_window_state._current_font_size_scale
        
        text_border_enabled = cached_data.get("text_border_enabled", main_window_state._current_text_border_enabled)
        text_border_color_rgb = cached_data.get("text_border_color")
        self.is_text_border_color_auto = text_border_color_rgb is None
        self.is_text_border_auto = "text_border_enabled" not in cached_data

        if text_border_color_rgb:
            self.text_border_color = QColor(*text_border_color_rgb)
        elif hasattr(main_window_state, '_current_text_border_color') and main_window_state._current_text_border_color:
            self.text_border_color = QColor(*main_window_state._current_text_border_color)
        else:
            self.text_border_color = QColor(0, 0, 0)

        cached_border_size = cached_data.get("text_border_size")
        self.is_border_size_overridden = cached_border_size is not None
        text_border_size = cached_border_size if self.is_border_size_overridden else main_window_state._current_text_border_size
        
        self.initial_font_family = font_family
        self.initial_font_style = font_style
        self.custom_art_b64 = track_cache.get("custom_art_b64")

        # Store initial credentials to check for changes on save
        self.initial_spotify_id = settings.value("spotify_client_id", "")
        self.initial_spotify_secret = settings.value("spotify_client_secret", "")
        self.initial_govee_key = settings.value("govee_api_key", "")
        self.initial_govee_devices = json.loads(settings.value("govee_devices", "[]"))
        
        self.initial_default_govee_brightness = int(main_window_state.default_govee_brightness * 100)
        
        cached_brightness = cached_data.get("govee_brightness")
        self.is_brightness_overridden = cached_brightness is not None
        self.initial_is_brightness_overridden = self.is_brightness_overridden
        
        if self.is_brightness_overridden:
            self.initial_track_brightness = int(cached_brightness * 100)
        else:
            self.initial_track_brightness = self.initial_default_govee_brightness

        self.current_art_pixmap = album_art_pixmap
        # --- Initialize Auto Flags ---
        self.is_bg_auto = "ui_palette" not in cached_data and "player_bg_color" not in cached_data
        self.is_accent_auto = "ui_palette" not in cached_data
        self.is_blob_auto = "blob_palette" not in cached_data
        self.is_lights_auto = "lights_config" not in cached_data

        # --- Initialize UI Colors and State ---
        self.ui_text_color = QColor(*text_color)
        self.blob_colors = [QColor(*c) for c in blob_palette]
        if not self.blob_colors:
            self.blob_colors = [
                self.ui_accent_color,
                self.ui_accent_color.lighter(120),
                self.ui_accent_color.darker(120)
            ]

        # --- STORE INITIAL STATE FOR 'SAVE ONLY CHANGES' LOGIC ---
        self.initial_ui_bg_color = QColor(self.ui_bg_color)
        self.initial_ui_accent_color = QColor(self.ui_accent_color)
        self.initial_ui_text_color = QColor(self.ui_text_color)
        self.initial_is_text_color_auto = self.is_text_color_auto
        self.initial_blob_colors = [QColor(c) for c in self.blob_colors]
        self.initial_shadow_enabled = shadow_enabled
        self.initial_title_case = title_case
        self.initial_artist_case = artist_case
        self.initial_text_border_enabled = text_border_enabled
        self.initial_is_text_border_auto = self.is_text_border_auto
        self.initial_text_border_color = QColor(self.text_border_color)
        self.initial_is_border_size_overridden = self.is_border_size_overridden
        self.initial_text_border_size = text_border_size
        self.initial_is_font_size_overridden = self.is_font_size_overridden
        self.initial_font_size_scale = font_size_scale
        self.initial_is_progress_bar_overridden = self.is_progress_bar_overridden
        self.initial_progress_bar_enabled = progress_bar_enabled
        
        # Determine initial lights palette
        if lights_config.get("mode") == "custom" and lights_config.get("palette"): 
            initial_lights_palette = lights_config.get("palette")
        else:
            initial_lights_palette = main_window_state._current_lights_palette

        # Convert initial Govee RGB lists to QColor for comparison
        self.initial_lights_palette = [QColor(*c) for c in initial_lights_palette]

        self.update_stylesheet()

        # --- 2. DEFERRED UI BUILD SETUP ---
        self._is_ui_built = False
        self._pending_load_state = None
        self._build_generator = None

        layout = QVBoxLayout(self)
        self.main_layout = QHBoxLayout() 
        layout.addLayout(self.main_layout)
        layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(20)

        # Loading Indicator (Visible initially)
        self.loading_container = QWidget()
        loading_layout = QVBoxLayout(self.loading_container)
        self.loading_label = QLabel("Loading Settings...")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet(f"color: {self.ui_text_color.name()}; font-size: 18px; font-weight: bold;")
        loading_layout.addWidget(self.loading_label)
        self.main_layout.addWidget(self.loading_container)

        # Settings Container (Hidden initially)
        self.settings_container = QWidget()
        self.settings_container.setObjectName("settingsContainer") 
        self.settings_container.setVisible(False)
        self.main_layout.addWidget(self.settings_container, 2)

        # Start Build Sequence
        self._build_generator = self._ui_build_steps()
        QTimer.singleShot(10, self._process_build_step)

    def _process_build_step(self):
        if not self._build_generator: return
        try:
            next(self._build_generator)
            # Process the next UI build step with a small delay to keep the app responsive.
            QTimer.singleShot(50, self._process_build_step)
        except StopIteration:
            self._build_generator = None

    def _install_filter_recursive(self, widget):
        """Installs the border event filter on the widget and all its children."""
        if isinstance(widget, (QLabel, QAbstractButton, QGroupBox)):
            widget.installEventFilter(self.ui_event_filter)
        
        for child in widget.children():
            if isinstance(child, QWidget):
                self._install_filter_recursive(child)

    def _create_label(self, text):
        lbl = BorderedLabel(text)
        lbl.setCustomTextColor(self.ui_text_color)
        self.ui_labels.append(lbl)
        return lbl

    def _update_combo_display_font(self, combo, family):
        """Updates the font of the combobox button itself to match the selected family."""
        if family:
            f = QFont(family)
            f.setPointSize(9) # Keep size reasonable for the UI
            combo.setFont(f)

    def _create_dynamic_label(self, text, is_html_or_wrapped=False):
        # Use BorderedLabel for simple text to get the effect, standard QLabel for HTML/Wrap to avoid broken rendering
        lbl = QLabel(text) if is_html_or_wrapped else BorderedLabel(text)
        if not is_html_or_wrapped: self.ui_labels.append(lbl); lbl.setCustomTextColor(self.ui_text_color)
        return lbl

    def _ui_build_steps(self):
        settings = QSettings("SpotifySync", "App")
        lights_config = self.cached_data.get("lights_config", {})

        # --- Right Column (Tabbed Settings) ---
        settings_container_layout = QVBoxLayout(self.settings_container)
        settings_container_layout.setContentsMargins(0,0,0,0)

        self.tab_widget = QTabWidget()
        # Create a placeholder for the disabled info label, to be managed by load_track_state
        self.disabled_info_label = QLabel("Theme and color editing is only available for tracks played via Spotify.")
        self.disabled_info_label.setWordWrap(True)
        self.disabled_info_label.setStyleSheet("font-style: italic; color: #999; padding-bottom: 10px;")
        self.disabled_info_label.hide()
        settings_container_layout.addWidget(self.tab_widget)

        yield # Yield after basic container setup

        # --- Tab 1: Current Theme (Visuals for this album) ---
        theme_tab = QWidget()
        theme_tab_layout = QVBoxLayout(theme_tab)
        theme_tab_layout.setContentsMargins(0, 0, 5, 0) # Add padding for the scrollbar

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        scroll_content_widget = QWidget()
        scroll_content_widget.setObjectName("scrollAreaContent") # For styling
        scroll_area.setWidget(scroll_content_widget)

        self.settings_grid_layout = QHBoxLayout(scroll_content_widget)
        self.settings_grid_layout.setContentsMargins(10, 10, 10, 10)
        self.settings_grid_layout.setSpacing(15)
        
        theme_tab_layout.addWidget(scroll_area)
        self.tab_widget.addTab(theme_tab, "Current Theme")

        self.settings_col_1 = QVBoxLayout(); self.settings_col_1.setAlignment(Qt.AlignTop)
        self.settings_col_2 = QVBoxLayout(); self.settings_col_2.setAlignment(Qt.AlignTop)
        self.settings_grid_layout.addLayout(self.settings_col_1, 2) # Give left column a stretch factor of 2
        self.settings_grid_layout.addLayout(self.settings_col_2, 3) # Give right column more space with a stretch factor of 3
        self.settings_col_1.insertWidget(0, self.disabled_info_label)

        theme_actions_layout = QHBoxLayout()
        regenerate_btn = QPushButton("Regenerate Theme from Art")
        regenerate_btn.setToolTip("Re-detect colors for auto-set fields based on current art.")
        regenerate_btn.clicked.connect(self.regenerate_theme)
        
        reset_theme_btn = QPushButton("Reset Theme")
        reset_theme_btn.setToolTip("Reset all colors to auto-detected defaults.")
        reset_theme_btn.clicked.connect(self.reset_theme_to_auto)
        
        theme_actions_layout.addWidget(regenerate_btn)
        theme_actions_layout.addWidget(reset_theme_btn)
        self.settings_col_1.addLayout(theme_actions_layout)

        yield # Yield after Tab 1 setup

        # --- Tab 2: Notifications ---
        notif_tab = QWidget()
        notif_tab_layout = QVBoxLayout(notif_tab)
        notif_tab_layout.setContentsMargins(0, 0, 5, 0)

        notif_scroll = QScrollArea()
        notif_scroll.setWidgetResizable(True)
        notif_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        notif_content = QWidget()
        notif_content.setObjectName("scrollAreaContent")
        notif_scroll.setWidget(notif_content)

        notif_layout = QVBoxLayout(notif_content)
        notif_layout.setContentsMargins(15, 15, 15, 15)
        notif_layout.setSpacing(12)
        notif_tab_layout.addWidget(notif_scroll)
        self.tab_widget.addTab(notif_tab, "Notifications")

        # Enable Switch
        self.notification_enabled_checkbox = QCheckBox("Enable Track Change Notifications")
        self.notification_enabled_checkbox.setChecked(settings.value("notification_enabled", "false") == "true")
        notif_layout.addWidget(self.notification_enabled_checkbox)

        # Behavior Group
        notification_group = QGroupBox("Behavior & Position")
        notification_layout = QFormLayout(notification_group)
        notification_layout.setSpacing(12)
        notif_layout.addWidget(notification_group)

        self.notification_monitor_combo = NoScrollComboBox()
        screens = QApplication.screens()
        monitor_names = ["Primary Monitor"]
        for screen in screens:
            name = screen.model() if screen.model() else screen.name()
            size = screen.size()
            monitor_names.append(f"{name} ({size.width()}x{size.height()})")
        self.notification_monitor_combo.addItems(monitor_names)
        self.notification_monitor_combo.setCurrentIndex(int(settings.value("notification_monitor_index", 0)))

        self.notification_corner_combo = NoScrollComboBox()
        self.notification_corner_combo.addItems(["Top-Left", "Top-Center", "Top-Right", "Bottom-Left", "Bottom-Center", "Bottom-Right"])
        self.notification_corner_combo.setCurrentText(settings.value("notification_corner", "Top-Right"))

        self.notif_smart_hide_checkbox = QCheckBox("Smart Hide")
        self.notif_smart_hide_checkbox.setToolTip("Hides notification if player is visible on the same screen.")
        self.notif_smart_hide_checkbox.setChecked(settings.value("notification_smart_hide", "false") == "true")
        
        self.notif_ignore_taskbar_checkbox = QCheckBox("Ignore Taskbar (Position at Screen Edge)")
        self.notif_ignore_taskbar_checkbox.setChecked(settings.value("notification_ignore_taskbar", "true") == "true")

        notification_layout.addRow(self._create_label("Monitor:"), self.notification_monitor_combo)
        notification_layout.addRow(self._create_label("Corner:"), self.notification_corner_combo)
        notification_layout.addRow(self.notif_smart_hide_checkbox)
        notification_layout.addRow(self.notif_ignore_taskbar_checkbox)

        # Appearance Group
        notif_style_group = QGroupBox("Appearance & Animation")
        notif_style_layout = QFormLayout(notif_style_group)
        notif_layout.addWidget(notif_style_group)

        # Size Slider
        self.notif_size_slider = QSlider(Qt.Horizontal)
        self.notif_size_slider.setRange(0, 4)
        self.notif_size_slider.setValue(int(settings.value("notification_size", 1)))
        size_labels = ["Tiny", "Small", "Normal", "Large", "Huge"]
        self.notif_size_label = self._create_dynamic_label(size_labels[self.notif_size_slider.value()])
        self.notif_size_slider.valueChanged.connect(lambda v, l=size_labels: self.notif_size_label.setText(l[v]))
        notif_size_layout = QHBoxLayout(); notif_size_layout.addWidget(self.notif_size_slider); notif_size_layout.addWidget(self.notif_size_label)

        # Opacity Slider
        self.notif_opacity_slider = QSlider(Qt.Horizontal)
        self.notif_opacity_slider.setRange(0, 255)
        self.notif_opacity_slider.setValue(int(settings.value("notification_bg_opacity", 230)))
        self.notif_opacity_label = self._create_dynamic_label(f"{int(self.notif_opacity_slider.value()/2.55)}%")
        self.notif_opacity_slider.valueChanged.connect(lambda v: self.notif_opacity_label.setText(f"{int(v/2.55)}%"))
        opacity_layout = QHBoxLayout(); opacity_layout.addWidget(self.notif_opacity_slider); opacity_layout.addWidget(self.notif_opacity_label)

        self.notif_border_checkbox = QCheckBox("Show Border")
        self.notif_border_checkbox.setChecked(settings.value("notification_border_enabled", "false") == "true")

        self.notification_anim_combo = NoScrollComboBox()
        self.notification_anim_combo.addItems(["Fade", "Slide", "Fade Slide", "Bounce"])
        self.notification_anim_combo.setCurrentText(settings.value("notification_anim", "Fade"))

        self.notification_dir_combo = NoScrollComboBox()
        self.notification_dir_combo.addItems(["From Top", "From Bottom", "From Left", "From Right"])
        self.notification_dir_combo.setCurrentText(settings.value("notification_dir", "From Top"))
        
        self.notification_anim_combo.currentTextChanged.connect(self._update_notification_options)

        self.notif_permanent_checkbox = QCheckBox("Stay for Song Duration")
        self.notif_permanent_checkbox.setToolTip("If checked, the notification will stay visible for the entire song and transition when the track changes.")
        self.notif_permanent_checkbox.setChecked(settings.value("notification_permanent", "false") == "true")

        # Duration Slider
        self.notif_duration_slider = QSlider(Qt.Horizontal)
        self.notif_duration_slider.setRange(1000, 10000)
        self.notif_duration_slider.setValue(int(settings.value("notification_duration", 4000)))
        self.notif_duration_label = self._create_dynamic_label(f"{self.notif_duration_slider.value() / 1000:.1f}s")
        self.notif_duration_slider.valueChanged.connect(lambda v: self.notif_duration_label.setText(f"{v / 1000:.1f}s"))
        duration_layout = QHBoxLayout(); duration_layout.addWidget(self.notif_duration_slider); duration_layout.addWidget(self.notif_duration_label)
        
        # Connect permanent checkbox to duration slider
        self.notif_duration_slider.setEnabled(not self.notif_permanent_checkbox.isChecked())
        self.notif_duration_label.setEnabled(not self.notif_permanent_checkbox.isChecked())
        self.notif_permanent_checkbox.toggled.connect(lambda c: (self.notif_duration_slider.setDisabled(c), self.notif_duration_label.setDisabled(c)))

        # Animation Speed Slider
        self.notif_anim_speed_slider = QSlider(Qt.Horizontal)
        self.notif_anim_speed_slider.setRange(200, 2000)
        self.notif_anim_speed_slider.setValue(int(settings.value("notification_anim_duration", 500)))
        self.notif_anim_speed_label = self._create_dynamic_label(f"{self.notif_anim_speed_slider.value() / 1000:.1f}s")
        self.notif_anim_speed_slider.valueChanged.connect(lambda v: self.notif_anim_speed_label.setText(f"{v / 1000:.1f}s"))
        anim_speed_layout = QHBoxLayout(); anim_speed_layout.addWidget(self.notif_anim_speed_slider); anim_speed_layout.addWidget(self.notif_anim_speed_label)

        notif_style_layout.addRow(self._create_label("Size:"), notif_size_layout)
        notif_style_layout.addRow(self._create_label("BG Opacity:"), opacity_layout)
        notif_style_layout.addRow(self.notif_border_checkbox)
        notif_style_layout.addRow(self._create_label("Animation:"), self.notification_anim_combo)
        notif_style_layout.addRow(self._create_label("Direction:"), self.notification_dir_combo)
        notif_style_layout.addRow(self.notif_permanent_checkbox)
        notif_style_layout.addRow(self._create_label("Duration:"), duration_layout)
        notif_style_layout.addRow(self._create_label("Anim Speed:"), anim_speed_layout)
        
        notif_layout.addStretch()

        self._update_notification_options(self.notification_anim_combo.currentText())

        yield # Yield after Tab 2 setup

        # --- Tab 3: Global Settings ---
        global_tab = QWidget()
        global_tab_layout = QVBoxLayout(global_tab)
        global_tab_layout.setContentsMargins(0, 0, 5, 0)

        global_scroll = QScrollArea()
        global_scroll.setWidgetResizable(True)
        global_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        global_content = QWidget()
        global_content.setObjectName("scrollAreaContent")
        global_scroll.setWidget(global_content)

        global_layout = QVBoxLayout(global_content)
        global_layout.setContentsMargins(15, 15, 15, 15)
        global_layout.setSpacing(12)
        global_tab_layout.addWidget(global_scroll)
        self.tab_widget.addTab(global_tab, "Global Settings")

        # Default Typography Group
        default_text_group = QGroupBox("Default Typography (Fallback)")
        default_text_layout = QFormLayout(default_text_group)
        default_text_layout.setSpacing(12)
        global_layout.addWidget(default_text_group)

        # Load defaults from QSettings
        self.initial_default_font_family = settings.value("default_font_family", "Trebuchet MS")
        self.initial_default_font_style = settings.value("default_font_style", "Bold")
        self.initial_default_font_size_scale = int(settings.value("default_font_size_scale", 100))
        self.initial_default_text_border_enabled = settings.value("default_text_border_enabled", "false") == "true"
        
        self.default_font_family_combo = NoScrollComboBox()
        self.default_font_style_combo = NoScrollComboBox()

        # --- Apply Delegates for Global Settings ---
        self.default_font_family_combo.setItemDelegate(FontFamilyDelegate(self.default_font_family_combo))
        # Pass a lambda function so the style delegate can always find the CURRENT text of the family combo
        self.default_font_style_combo.setItemDelegate(
            FontStyleDelegate(lambda: self.default_font_family_combo.currentText(), self.default_font_style_combo)
        )
        
        self.default_font_size_slider = QSlider(Qt.Horizontal); self.default_font_size_slider.setRange(50, 200); self.default_font_size_slider.setValue(self.initial_default_font_size_scale)
        self.default_font_size_label = self._create_dynamic_label(f"{self.initial_default_font_size_scale}%")
        self.default_font_size_slider.valueChanged.connect(lambda v: self.default_font_size_label.setText(f"{v}%"))
        default_size_layout = QHBoxLayout(); default_size_layout.addWidget(self.default_font_size_slider); default_size_layout.addWidget(self.default_font_size_label)

        default_text_layout.addRow(self._create_label("Font:"), self.default_font_family_combo); default_text_layout.addRow(self._create_label("Style:"), self.default_font_style_combo)
        default_text_layout.addRow(self._create_label("Size:"), default_size_layout)
        
        self.default_text_border_checkbox = QCheckBox("Always Show Text Border by Default")
        self.default_text_border_checkbox.setToolTip("If checked, borders will be shown on all tracks unless manually disabled.\nIf unchecked, borders will only appear when text contrast is low (Auto).")
        self.default_text_border_checkbox.setChecked(self.initial_default_text_border_enabled)
        default_text_layout.addRow(self.default_text_border_checkbox)

        self.default_text_border_size_slider = QSlider(Qt.Horizontal); self.default_text_border_size_slider.setRange(1, 10); self.default_text_border_size_slider.setValue(self.initial_default_text_border_size)
        self.default_text_border_size_label = self._create_dynamic_label(f"{self.initial_default_text_border_size}px")
        self.default_text_border_size_slider.valueChanged.connect(lambda v: (self.default_text_border_size_label.setText(f"{v}px"), self.update_previews()))
        default_border_size_layout = QHBoxLayout(); default_border_size_layout.addWidget(self.default_text_border_size_slider); default_border_size_layout.addWidget(self.default_text_border_size_label)
        
        default_text_layout.addRow(self._create_label("Border Size:"), default_border_size_layout)

        # Global Visuals Group
        global_visuals_group = QGroupBox("Global Visuals")
        global_visuals_layout = QFormLayout(global_visuals_group)
        global_visuals_layout.setSpacing(12)
        global_layout.addWidget(global_visuals_group)

        self.blob_amount_slider = QSlider(Qt.Horizontal)
        self.blob_amount_slider.setRange(1, 10)
        self.blob_amount_slider.setToolTip("Controls the number of animated blobs. More to the right means more blobs.")
        initial_slider_value = round(400000 / self.blob_density) if self.blob_density > 0 else 2
        self.blob_amount_slider.setValue(initial_slider_value)
        self.blob_amount_slider.valueChanged.connect(self._update_blob_density)

        amount_widget = QWidget()
        amount_layout = QHBoxLayout(amount_widget)
        amount_layout.setContentsMargins(0,0,0,0)
        amount_layout.addWidget(self._create_dynamic_label("Less"))
        amount_layout.addWidget(self.blob_amount_slider)
        amount_layout.addWidget(self._create_dynamic_label("More"))
        global_visuals_layout.addRow(self._create_label("Blob Density:"), amount_widget)

        self.default_progress_bar_checkbox = QCheckBox("Enable Progress Bar by Default")
        self.default_progress_bar_checkbox.setChecked(self.initial_default_progress_bar_enabled)
        global_visuals_layout.addRow(self.default_progress_bar_checkbox)
        
        self.default_brightness_slider = QSlider(Qt.Horizontal)
        self.default_brightness_slider.setRange(0, 100)
        self.default_brightness_slider.setValue(self.initial_default_govee_brightness)
        self.default_brightness_label = self._create_dynamic_label(f"{self.initial_default_govee_brightness}%")
        self.default_brightness_slider.valueChanged.connect(self._on_default_brightness_changed)
        def_bright_layout = QHBoxLayout()
        def_bright_layout.addWidget(self.default_brightness_slider); def_bright_layout.addWidget(self.default_brightness_label)
        global_visuals_layout.addRow(self._create_label("Default Brightness:"), def_bright_layout)

        # Data Management Group
        data_group = QGroupBox("Maintenance")
        data_layout = QVBoxLayout(data_group)
        data_layout.setContentsMargins(15, 15, 15, 15)
        self.clear_cache_btn = QPushButton("Clear Album Cache")
        self.clear_cache_btn.clicked.connect(self.confirm_clear_cache)
        data_layout.addWidget(self.clear_cache_btn)
        global_layout.addWidget(data_group)
        
        global_layout.addStretch()

        yield # Yield after Tab 3 setup

        # --- Tab 4: API & Devices ---
        credentials_tab = QWidget()
        credentials_tab_layout = QVBoxLayout(credentials_tab)
        credentials_tab_layout.setContentsMargins(0, 0, 5, 0)

        credentials_scroll = QScrollArea()
        credentials_scroll.setWidgetResizable(True)
        credentials_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        credentials_content = QWidget()
        credentials_content.setObjectName("scrollAreaContent")
        credentials_scroll.setWidget(credentials_content)

        credentials_layout = QVBoxLayout(credentials_content)
        credentials_layout.setContentsMargins(15, 15, 15, 15)
        credentials_layout.setSpacing(12)
        credentials_tab_layout.addWidget(credentials_scroll)
        self.tab_widget.addTab(credentials_tab, "API & Devices")

        spotify_group = QGroupBox("Spotify API")
        spotify_layout = QFormLayout(spotify_group)
        spotify_layout.setSpacing(12)
        self.spotify_id_input = QLineEdit(self.initial_spotify_id)
        self.spotify_secret_input = QLineEdit(self.initial_spotify_secret)
        self.spotify_id_input.setEchoMode(QLineEdit.Password)
        self.spotify_secret_input.setEchoMode(QLineEdit.Password)
        spotify_layout.addRow(self._create_label("Client ID:"), self.spotify_id_input)
        spotify_layout.addRow(self._create_label("Client Secret:"), self.spotify_secret_input)
        credentials_layout.addWidget(spotify_group)

        govee_cred_group = QGroupBox("Govee API & Devices")
        govee_cred_layout = QVBoxLayout(govee_cred_group)
        govee_api_layout = QHBoxLayout()
        self.govee_key_input = QLineEdit(self.initial_govee_key)
        self.govee_key_input.setEchoMode(QLineEdit.Password)
        self.find_govee_button = QPushButton("Find Devices")
        govee_api_layout.addWidget(self._create_dynamic_label("API Key:"))
        govee_api_layout.addWidget(self.govee_key_input)
        govee_api_layout.addWidget(self.find_govee_button)
        govee_cred_layout.addLayout(govee_api_layout)

        self.govee_status_label = self._create_dynamic_label("Enter your API key and click 'Find Devices' to manage your lights.", is_html_or_wrapped=True)
        self.govee_status_label.setWordWrap(True)
        govee_cred_layout.addWidget(self.govee_status_label)

        self.govee_device_table = QTableWidget()
        self.govee_device_table.setColumnCount(4)
        self.govee_device_table.setHorizontalHeaderLabels(["Enabled", "Device ID", "Model", "Light Name"])
        self.govee_device_table.horizontalHeader().setStretchLastSection(True)
        self.govee_device_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        govee_cred_layout.addWidget(self.govee_device_table)
        credentials_layout.addWidget(govee_cred_group)

        show_hide_button = QPushButton("Show Credentials")
        show_hide_button.setCheckable(True)
        show_hide_button.setToolTip("Toggle the visibility of your API keys.")
        show_hide_button.toggled.connect(self.toggle_credential_visibility)
        credentials_layout.addWidget(show_hide_button, 0, Qt.AlignRight)
        credentials_layout.addStretch()

        yield # Yield after Tab 4 setup

        # --- Tab 5: Shortcuts ---
        controls_tab = QWidget()
        controls_tab_layout = QVBoxLayout(controls_tab)
        controls_tab_layout.setContentsMargins(0, 0, 5, 0)

        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        controls_content = QWidget()
        controls_content.setObjectName("scrollAreaContent")
        controls_scroll.setWidget(controls_content)

        controls_layout = QFormLayout(controls_content)
        controls_layout.setContentsMargins(15, 15, 15, 15)
        controls_layout.setSpacing(12)
        controls_tab_layout.addWidget(controls_scroll)
        self.tab_widget.addTab(controls_tab, "Shortcuts")

        controls = {
            "F": "Toggle fullscreen mode.",
            "F11": "Toggle multi-monitor spanning mode.",
            "F12": "Toggle wallpaper mode (places behind icons).",
            "L": "Toggle Govee light synchronization.",
            "C": "Open this settings panel.",
            "← / →": "Shift player to adjacent monitor.",
            "Esc": "Close the application."
        }

        for key, desc in controls.items():
            key_label = self._create_dynamic_label(f"<b>{key}</b>", is_html_or_wrapped=True)
            desc_label = self._create_dynamic_label(desc, is_html_or_wrapped=True)
            desc_label.setWordWrap(True)
            controls_layout.addRow(key_label, desc_label)

        yield # Yield after Tab 5 setup

        # --- Tab 6: Updates ---
        updates_tab = QWidget()
        updates_layout = QVBoxLayout(updates_tab)
        updates_layout.setContentsMargins(0, 0, 0, 0)
        
        self.updates_browser = QTextBrowser()
        self.updates_browser.setObjectName("updatesBrowser")
        self.updates_browser.setOpenExternalLinks(True)
        updates_layout.addWidget(self.updates_browser)
        self.tab_widget.addTab(updates_tab, "Updates")

        yield # Yield after Tab 6 setup

        # --- Typography Group (Current Theme) ---
        text_group = QGroupBox("Typography")
        text_layout = QFormLayout(text_group)
        text_layout.setSpacing(12)
        self.text_preview, self.pick_text_btn, self.reset_text_btn = self._create_color_picker(self.ui_text_color, self.pick_text_color, self.reset_text_color, is_text=True)
        text_layout.addRow(self._create_label("Text Color:"), self.create_color_row(self.text_preview, self.pick_text_btn, self.reset_text_btn))
        self.text_preview_shadow = QGraphicsDropShadowEffect()
        self.text_preview.setGraphicsEffect(self.text_preview_shadow)

        self.override_font_checkbox = QCheckBox("Override Default Font")
        self.override_font_checkbox.setChecked(self.is_font_family_overridden)
        self.override_font_checkbox.toggled.connect(self._on_override_font_toggled)

        self.font_family_combo = NoScrollComboBox()
        self.font_family_combo.setToolTip("Select the font family for the track title and artist.")
        self.font_family_combo.setEnabled(self.is_font_family_overridden)
        self.font_style_combo = NoScrollComboBox()
        self.font_style_combo.setToolTip("Select the style for the chosen font family.")
        self.font_style_combo.setEnabled(self.is_font_family_overridden)
        
        # --- Apply Delegate to Theme Font Family ---
        self.font_family_combo.setItemDelegate(FontFamilyDelegate(self.font_family_combo))
        
        self.font_style_combo = NoScrollComboBox()
        self.font_style_combo.setToolTip("Select the style for the chosen font family.")
        self.font_style_combo.setEnabled(self.is_font_family_overridden)
        
        # --- Apply Delegate to Theme Font Style ---
        self.font_style_combo.setItemDelegate(FontStyleDelegate(lambda: self.font_family_combo.currentText(), self.font_style_combo))

        self.font_search_input = QLineEdit()
        self.font_search_input.setPlaceholderText("Search fonts...")
        self.font_search_input.setEnabled(self.is_font_family_overridden)

        self.override_size_checkbox = QCheckBox("Override Default Size")
        self.override_size_checkbox.setChecked(self.is_font_size_overridden)
        self.override_size_checkbox.toggled.connect(self._on_override_size_toggled)

        self.font_size_slider = QSlider(Qt.Horizontal); self.font_size_slider.setRange(50, 200); self.font_size_slider.setValue(self.initial_font_size_scale)
        self.font_size_slider.setEnabled(self.is_font_size_overridden)
        self.font_size_label = self._create_dynamic_label(f"{self.initial_font_size_scale}%")
        self.font_size_slider.valueChanged.connect(lambda v: (self.font_size_label.setText(f"{v}%"), self.update_previews()))
        size_layout = QHBoxLayout(); size_layout.addWidget(self.font_size_slider); size_layout.addWidget(self.font_size_label)

        self.shadow_checkbox = QCheckBox("Enable Text Shadow")
        self.title_case_radios, title_case_widget = self._create_case_controls(self.initial_title_case)
        self.artist_case_radios, artist_case_widget = self._create_case_controls(self.initial_artist_case)

        # Add Separator for Border Settings
        border_line = QFrame()
        border_line.setFrameShape(QFrame.HLine)
        border_line.setFrameShadow(QFrame.Sunken)
        border_line.setStyleSheet("background-color: #555;")

        self.text_border_checkbox = QCheckBox("Show Text Border")
        self.text_border_checkbox.setChecked(self.initial_text_border_enabled)
        self.text_border_checkbox.toggled.connect(self._on_text_border_toggled)
        
        self.reset_text_border_enable_btn = QPushButton("Auto")
        self.reset_text_border_enable_btn.setToolTip("Reset to automatic border detection based on contrast")
        self.reset_text_border_enable_btn.clicked.connect(self.reset_text_border_enable)

        self.force_off_border_btn = QPushButton("Off")
        self.force_off_border_btn.setToolTip("Force text border OFF for this album")
        self.force_off_border_btn.clicked.connect(lambda: self.text_border_checkbox.setChecked(False))
        
        border_enable_widget = QWidget()
        border_enable_layout = QHBoxLayout(border_enable_widget)
        border_enable_layout.setContentsMargins(0,0,0,0)
        border_enable_layout.addWidget(self.text_border_checkbox)
        border_enable_layout.addWidget(self.force_off_border_btn)
        border_enable_layout.addWidget(self.reset_text_border_enable_btn)
        border_enable_layout.addStretch()

        self.text_border_preview, self.pick_text_border_btn, self.reset_text_border_btn = self._create_color_picker(self.text_border_color, self.pick_text_border_color, self.reset_text_border_color)

        self.override_border_size_checkbox = QCheckBox("Override Border Size")
        self.override_border_size_checkbox.setChecked(self.is_border_size_overridden)
        self.override_border_size_checkbox.toggled.connect(self._on_override_border_size_toggled)

        self.text_border_size_slider = QSlider(Qt.Horizontal); self.text_border_size_slider.setRange(1, 10); self.text_border_size_slider.setValue(self.initial_text_border_size)
        self.text_border_size_slider.setEnabled(self.is_border_size_overridden)
        self.text_border_size_label = self._create_dynamic_label(f"{self.initial_text_border_size}px")
        self.text_border_size_slider.valueChanged.connect(lambda v: (self.text_border_size_label.setText(f"{v}px"), self.update_previews()))
        border_size_layout = QHBoxLayout(); border_size_layout.addWidget(self.text_border_size_slider); border_size_layout.addWidget(self.text_border_size_label)

        text_layout.addRow(self.override_font_checkbox)
        text_layout.addRow(self._create_label("Search:"), self.font_search_input)
        text_layout.addRow(self._create_label("Font:"), self.font_family_combo)
        text_layout.addRow(self._create_label("Style:"), self.font_style_combo)
        text_layout.addRow(self.override_size_checkbox)
        text_layout.addRow(self._create_label("Size:"), size_layout)
        text_layout.addRow(self.shadow_checkbox)
        text_layout.addRow(border_line)
        text_layout.addRow(border_enable_widget)
        text_layout.addRow(self._create_label("Border Color:"), self.create_color_row(self.text_border_preview, self.pick_text_border_btn, self.reset_text_border_btn))
        text_layout.addRow(self.override_border_size_checkbox)
        text_layout.addRow(self._create_label("Border Size:"), border_size_layout)
        text_layout.addRow(self._create_label("Title Case:"), title_case_widget)
        text_layout.addRow(self._create_label("Artist Case:"), artist_case_widget)
        self.settings_col_2.addWidget(text_group) 

        yield # Yield after Typography Group

        # --- Background & Atmosphere Group (Current Theme) ---
        self.ui_group = QGroupBox("Background & Atmosphere")
        ui_group_layout = QVBoxLayout(self.ui_group)
        ui_group_layout.setSpacing(15)

        # 1. Main Colors
        ui_colors_widget = QWidget()
        ui_colors_layout = QFormLayout(ui_colors_widget)
        ui_colors_layout.setContentsMargins(0,0,0,0)
        ui_colors_layout.setSpacing(12)
        
        self.ui_bg_preview, pick_ui_bg_btn, self.reset_ui_bg_btn = self._create_color_picker(self.ui_bg_color, self.pick_ui_bg_color, self.reset_ui_bg_color)
        ui_colors_layout.addRow(self._create_label("Player Background:"), self.create_color_row(self.ui_bg_preview, pick_ui_bg_btn, self.reset_ui_bg_btn))
        self.ui_accent_preview, pick_ui_accent_btn, self.reset_ui_accent_btn = self._create_color_picker(self.ui_accent_color, self.pick_ui_accent_color, self.reset_ui_accent_color)
        ui_colors_layout.addRow(self._create_label("Art Border:"), self.create_color_row(self.ui_accent_preview, pick_ui_accent_btn, self.reset_ui_accent_btn))
        ui_group_layout.addWidget(ui_colors_widget)

        # 2. Blobs Section
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet(f"background-color: #555;") 
        ui_group_layout.addWidget(line)

        # Blob Controls
        blob_controls_widget = QWidget()
        self.blob_layout = QFormLayout(blob_controls_widget)
        self.blob_layout.setContentsMargins(0,0,0,0)
        self.blob_layout.setSpacing(12)
        
        self.add_blob_color_btn = QPushButton("+")
        self.add_blob_color_btn.setFixedSize(40, 40)
        self.add_blob_color_btn.setProperty("no_text_border", True)
        self.add_blob_color_btn.setToolTip("Add a new blob color")
        self.add_blob_color_btn.clicked.connect(self.add_blob_color_picker)
        
        reset_blobs_btn = QPushButton("Reset Blobs")
        reset_blobs_btn.setToolTip("Reset blobs to auto-generated colors")
        reset_blobs_btn.clicked.connect(self.reset_blobs_to_auto)
        
        blob_button_widget = QWidget()
        blob_button_layout = QHBoxLayout(blob_button_widget)
        blob_button_layout.setContentsMargins(0,0,0,0)
        blob_label = self._create_dynamic_label("Blobs:", is_html_or_wrapped=False)
        blob_font = blob_label.font()
        blob_font.setBold(True)
        blob_label.setFont(blob_font)
        blob_button_layout.addWidget(blob_label)
        blob_button_layout.addStretch()
        blob_button_layout.addWidget(self.add_blob_color_btn)
        blob_button_layout.addWidget(reset_blobs_btn)
        
        ui_group_layout.addWidget(blob_button_widget)
        ui_group_layout.addWidget(blob_controls_widget)

        self.settings_col_1.addWidget(self.ui_group)

        yield # Yield after UI Group

        # --- Album Art Group ---
        self.art_group = QGroupBox("Album Art")
        art_layout = QVBoxLayout(self.art_group)
        art_button_layout = QHBoxLayout()
        set_art_button = QPushButton("Set Custom Art...")
        reset_art_button = QPushButton("Reset to Default")
        art_button_layout.addWidget(set_art_button)
        art_button_layout.addWidget(reset_art_button)
        art_layout.addLayout(art_button_layout)
        self.settings_col_1.addWidget(self.art_group)
        
        for i, color in enumerate(self.blob_colors):
            self._add_blob_color_row(color, i)
        self._update_blob_buttons_style()

        yield # Yield after Art Group

        # --- Interface Group (Current Theme) ---
        interface_group = QGroupBox("Interface")
        interface_layout = QFormLayout(interface_group)
        
        self.override_progress_bar_checkbox = QCheckBox("Override Progress Bar")
        self.override_progress_bar_checkbox.setChecked(self.is_progress_bar_overridden)
        self.override_progress_bar_checkbox.toggled.connect(self._on_override_progress_bar_toggled)
        
        self.progress_bar_checkbox = QCheckBox("Enable Progress Bar")
        self.progress_bar_checkbox.setChecked(self.initial_progress_bar_enabled)
        self.progress_bar_checkbox.setEnabled(self.is_progress_bar_overridden)
        interface_layout.addRow(self.override_progress_bar_checkbox)
        interface_layout.addRow("", self.progress_bar_checkbox)
        self.settings_col_2.addWidget(interface_group)

        yield # Yield after Interface Group

        # --- Light Synchronization Group (Current Theme) ---
        self.govee_group = QGroupBox("Light Synchronization")
        govee_group_main_layout = QVBoxLayout(self.govee_group)
        govee_group_main_layout.setContentsMargins(10, 10, 10, 10)
        govee_group_main_layout.setSpacing(12)
        
        # Status row using a QHBoxLayout for horizontal alignment
        status_widget = QWidget()
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(0,0,0,0)
        status_layout.setSpacing(6)
        lights_status = "Enabled" if self.parent().lights_enabled else "Disabled"
        status_layout.addWidget(self._create_dynamic_label("Global Status:"))
        status_value_label = self._create_dynamic_label(lights_status)
        status_value_label.setStyleSheet("font-weight: normal;") # Counteract bold from GroupBox
        status_layout.addWidget(status_value_label)
        status_layout.addStretch()
        reset_lights_btn = QPushButton("Reset")
        reset_lights_btn.setToolTip("Reset lights to auto-generated colors")
        reset_lights_btn.clicked.connect(self.reset_lights_to_auto)
        status_layout.addWidget(reset_lights_btn)
        govee_group_main_layout.addWidget(status_widget)

        # Brightness Slider
        brightness_widget = QWidget()
        brightness_layout = QHBoxLayout(brightness_widget)
        brightness_layout.setContentsMargins(0,0,0,0)
        
        self.override_brightness_checkbox = QCheckBox("Override")
        self.override_brightness_checkbox.setChecked(self.is_brightness_overridden)
        self.override_brightness_checkbox.toggled.connect(self._on_override_brightness_toggled)
        
        self.govee_brightness_slider = QSlider(Qt.Horizontal)
        self.govee_brightness_slider.setRange(0, 100)
        self.govee_brightness_slider.setValue(self.initial_track_brightness)
        self.govee_brightness_slider.setEnabled(self.is_brightness_overridden)
        self.govee_brightness_slider.valueChanged.connect(self._on_govee_brightness_changed)
        self.govee_brightness_label = self._create_dynamic_label(f"{self.govee_brightness_slider.value()}%")
        brightness_layout.addWidget(self.override_brightness_checkbox); brightness_layout.addWidget(self._create_dynamic_label("Brightness:")); brightness_layout.addWidget(self.govee_brightness_slider); brightness_layout.addWidget(self.govee_brightness_label)
        govee_group_main_layout.addWidget(brightness_widget)

        # Form layout for the color pickers that need wrapping
        govee_picker_layout = QFormLayout()
        govee_picker_layout.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        govee_picker_layout.setRowWrapPolicy(QFormLayout.WrapAllRows)
        govee_group_main_layout.addLayout(govee_picker_layout)

        self.govee_color_pickers = [] 

        if lights_config.get("mode") == "custom" and lights_config.get("palette"): 
            initial_lights_palette = lights_config.get("palette")
        else:
            initial_lights_palette = self.parent()._current_lights_palette

        for i, device in enumerate(self.govee_devices):
            if i < len(initial_lights_palette):
                initial_color = QColor(*initial_lights_palette[i])
            else:
                initial_color = self.ui_accent_color.lighter(110 + i*10)

            device_name = device.get('name', f'Light {i+1}')
            label = self._create_label(f"{device_name}:")
            label.setToolTip(device_name)
            picker_callback = lambda checked, index=i: self.pick_govee_color(index)
            preview, button, _ = self._create_color_picker(initial_color, picker_callback)
            self.govee_color_pickers.append({"preview": preview, "color": initial_color})
            govee_picker_layout.addRow(label, self.create_color_row(preview, button))
        self.effective_initial_lights_palette = [QColor(p["color"]) for p in self.govee_color_pickers]
        self.settings_col_1.addWidget(self.govee_group)
        self.settings_col_2.addStretch()
        self.settings_col_1.addStretch() 

        yield # Yield after Govee Group

        # Add SizeGrip for manual resizing
        self.sizegrip = QSizeGrip(self)

        # --- Action Buttons ---
        action_layout = QHBoxLayout() # Note: self.main_layout is the top-level HBox, we need to add this to the dialog's VBox
        action_layout.setSpacing(10)
        action_layout.addStretch() 
        
        self.quick_save_btn = QPushButton("Quick Save")
        self.quick_save_btn.setToolTip("Save changed settings immediately.")
        self.quick_save_btn.clicked.connect(lambda: self.save_and_close(quick=True))
        
        self.save_button = QPushButton("Save...")
        self.save_button.setDefault(True)
        self.save_button.setToolTip("Choose which settings to save.")
        self.save_button.clicked.connect(lambda: self.save_and_close(quick=False))
        
        self.cancel_button = QPushButton("Cancel")
        action_layout.addWidget(self.quick_save_btn)
        action_layout.addWidget(self.save_button)
        action_layout.addWidget(self.cancel_button)
        self.layout().addLayout(action_layout)

        # --- 3. CONNECT SIGNALS ---
        self.font_search_input.textChanged.connect(self._filter_font_list)
        self.font_family_combo.currentTextChanged.connect(self._update_font_styles)
        self.font_style_combo.currentTextChanged.connect(self.update_previews)
        self.shadow_checkbox.toggled.connect(self.update_previews)
        for radio in self.title_case_radios.values():
            radio.toggled.connect(self.update_previews)
        for radio in self.artist_case_radios.values():
            radio.toggled.connect(self.update_previews)

        self.default_font_family_combo.currentTextChanged.connect(self._update_default_font_styles)
        
        set_art_button.clicked.connect(self.set_custom_art)
        reset_art_button.clicked.connect(self.reset_custom_art)

        self.cancel_button.clicked.connect(self.reject)
        self.find_govee_button.clicked.connect(self.find_govee_devices)
        self._populate_govee_table()

        self.font_styles_cache = {}
        self.base_font_families = []

        # Finalize Build
        self.loading_container.hide()
        self.settings_container.setVisible(True)
        self._is_ui_built = True
        
        # Install event filter on all created widgets
        self._install_filter_recursive(self)
        self.tab_widget.installEventFilter(self.ui_event_filter)

        # --- 4. POPULATE DATA & SET INITIAL STATES ---
        self.shadow_checkbox.setChecked(self.initial_shadow_enabled)

        # Check if fonts have been pre-loaded by the main window or updated while building
        if self.base_font_families:
             self._on_fonts_loaded({ "font_styles_cache": self.font_styles_cache, "base_font_families": self.base_font_families })
        elif self.parent()._fonts_loaded:
            self.font_styles_cache = self.parent().font_styles_cache
            self.base_font_families = self.parent().base_font_families
            self._on_fonts_loaded({ "font_styles_cache": self.font_styles_cache, "base_font_families": self.base_font_families })
        else:
            # Fonts are still loading in the background, show a placeholder
            self._font_list_populated = False
            self.font_family_combo.addItem("Loading fonts...")
            self.default_font_family_combo.addItem("Loading fonts...")
            for w in [self.font_family_combo, self.font_style_combo, self.font_search_input, self.default_font_family_combo, self.default_font_style_combo]:
                w.setEnabled(False)

        # --- 5. Set initial states from loaded data ---
        self.fetch_updates()
        
        self._on_auto_text_toggled(self.is_text_color_auto, recalculate=False)
        self._on_auto_text_border_toggled(self.is_text_border_color_auto, recalculate=False)
        self._update_bg_accent_buttons()
        self._update_text_border_auto_state()

        self.update_previews()
        self._adjust_window_size()

        # Apply any pending state that came in while we were building
        if self._pending_load_state:
            self.load_track_state(*self._pending_load_state)
            self._pending_load_state = None

    def _adjust_window_size(self):
        max_w = 800
        max_h = 600
        
        # Iterate tabs to find max content size
        for i in range(self.tab_widget.count()):
            page = self.tab_widget.widget(i)
            scroll_area = page.findChild(QScrollArea)
            if scroll_area:
                content = scroll_area.widget()
                if content:
                    content.adjustSize()
                    size = content.sizeHint()
                    max_w = max(max_w, size.width() + 50)
                    max_h = max(max_h, size.height() + 50)

        # Add chrome margins (tabs, window frame, buttons)
        max_w += 40 
        max_h += 120 

        # Clamp to screen
        screen = QApplication.primaryScreen()
        if self.parent() and self.parent().windowHandle():
            screen = self.parent().windowHandle().screen()
        avail = screen.availableGeometry()
        
        final_w = min(max_w, int(avail.width() * 0.95))
        final_h = min(max_h, int(avail.height() * 0.95))
        
        self.resize(final_w, final_h)
        self.setMinimumSize(800, 600)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'sizegrip'):
            self.sizegrip.move(self.width() - self.sizegrip.width(), self.height() - self.sizegrip.height())

    def showEvent(self, event):
        self._closing = False
        super().showEvent(event)
        self.animate_entry()

    def animate_entry(self):
        anim_type = "Fade"
        anim_dir = "From Top"
        duration = 400
        
        start_pos = self.pos()
        end_pos = self.pos()
        offset = 50 # Slide distance

        if not duration: return
        elif anim_dir == "From Top": start_pos.setY(start_pos.y() - offset)
        elif anim_dir == "From Bottom": start_pos.setY(start_pos.y() + offset)
        elif anim_dir == "From Left": start_pos.setX(start_pos.x() - offset)
        elif anim_dir == "From Right": start_pos.setX(start_pos.x() + offset)

        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.pos_anim = QPropertyAnimation(self, b"pos")
        
        if anim_type == "Fade":
            self.setWindowOpacity(0.0)
            self.opacity_anim.setStartValue(0.0); self.opacity_anim.setEndValue(1.0)
            self.opacity_anim.setDuration(duration); self.opacity_anim.setEasingCurve(QEasingCurve.OutQuad)
            self.opacity_anim.start()
        elif anim_type in ["Slide", "Bounce"]:
            self.pos_anim.setStartValue(start_pos); self.pos_anim.setEndValue(end_pos)
            self.pos_anim.setDuration(duration)
            self.pos_anim.setEasingCurve(QEasingCurve.OutBounce if anim_type == "Bounce" else QEasingCurve.OutExpo)
            self.pos_anim.start()
        elif anim_type == "Fade Slide":
            self.setWindowOpacity(0.0)
            self.opacity_anim.setStartValue(0.0); self.opacity_anim.setEndValue(1.0)
            self.opacity_anim.setDuration(duration); self.opacity_anim.setEasingCurve(QEasingCurve.OutQuad)
            self.pos_anim.setStartValue(start_pos); self.pos_anim.setEndValue(end_pos)
            self.pos_anim.setDuration(duration); self.pos_anim.setEasingCurve(QEasingCurve.OutExpo)
            self.opacity_anim.start(); self.pos_anim.start()

    def done(self, r):
        # Prevent double-closing/animation if triggered multiple times
        if getattr(self, '_closing', False):
            super().done(r)
            return
        
        self._closing = True
        self._result_code = r
        self.animate_exit()

    def _on_exit_anim_finished(self):
        super(ColorEditorDialog, self).done(self._result_code)

    def animate_exit(self):
        anim_type = "Fade"
        anim_dir = "From Top"
        duration = 400
        
        current_pos = self.pos()
        target_pos = QPoint(current_pos)
        offset = 50

        if not duration: return
        elif anim_dir == "From Top": target_pos.setY(target_pos.y() - offset)
        elif anim_dir == "From Bottom": target_pos.setY(target_pos.y() + offset)
        elif anim_dir == "From Left": target_pos.setX(target_pos.x() - offset)
        elif anim_dir == "From Right": target_pos.setX(target_pos.x() + offset)

        self.exit_anim_group = QParallelAnimationGroup(self)
        
        opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        opacity_anim.setDuration(duration); opacity_anim.setStartValue(self.windowOpacity()); opacity_anim.setEndValue(0.0); opacity_anim.setEasingCurve(QEasingCurve.OutQuad)
        
        pos_anim = QPropertyAnimation(self, b"pos")
        pos_anim.setDuration(duration); pos_anim.setStartValue(current_pos); pos_anim.setEndValue(target_pos); pos_anim.setEasingCurve(QEasingCurve.InExpo)

        if anim_type == "Fade":
            self.exit_anim_group.addAnimation(opacity_anim)
        else: # Slide, Bounce, Fade Slide - all use pos + opacity for clean exit
            self.exit_anim_group.addAnimation(pos_anim)
            self.exit_anim_group.addAnimation(opacity_anim)

        self.exit_anim_group.finished.connect(lambda: super(ColorEditorDialog, self).done(self._result_code))
        self.exit_anim_group.start()

    def fetch_updates(self):
        self.updates_browser.setHtml("<p style='color: #aaa;'>Loading updates from GitHub...</p>")
        # Fixed definition of worker - assumed Hang1m3 with token is correct per context
        worker = GitHubUpdatesWorker("Hang1m3", "Dynamic-Player", token=GITHUB_TOKEN)
        worker.signals.result.connect(self.display_updates)
        worker.signals.error.connect(lambda e: self.display_updates(str(e))) 
        self.threadpool.start(worker)

    def display_updates(self, data):
        if isinstance(data, list):
            self.commits_data = data
            self.render_updates()
        else:
            self.updates_browser.setHtml(str(data))

    def render_updates(self):
        if not self.commits_data: return
        text_color = self.ui_text_color
        text_hex = text_color.name()
        
        dim_color = QColor(text_color)
        dim_color.setAlpha(180)
        dim_rgba = f"rgba({dim_color.red()}, {dim_color.green()}, {dim_color.blue()}, {dim_color.alpha()/255:.2f})"
        
        border_color = QColor(text_color)
        border_color.setAlpha(50)
        border_rgba = f"rgba({border_color.red()}, {border_color.green()}, {border_color.blue()}, {border_color.alpha()/255:.2f})"

        html = f"""
        <html>
        <head>
        <style>
            body {{ font-family: 'Segoe UI', sans-serif; margin: 20px; }}
            h2 {{ color: {text_hex}; margin-bottom: 25px; }}
            .commit {{ margin-bottom: 25px; border-bottom: 1px solid {border_rgba}; padding-bottom: 20px; }}
            .title {{ font-size: 15px; font-weight: bold; color: {text_hex}; margin-bottom: 5px; }}
            .meta {{ font-size: 12px; color: {dim_rgba}; margin-bottom: 10px; }}
            .desc {{ font-size: 13px; color: {text_hex}; margin-top: 8px; }}
        </style>
        </head>
        <body>
        <h2>Latest Changes</h2>
        """
        for commit in self.commits_data:
            desc_text = commit['desc'].replace('\n', '<br>')
            desc_html = f"<div class='desc'>{desc_text}</div>" if commit['desc'] else ""
            html += f"""
            <div class='commit'>
                <div class='title'>{commit['title']}</div>
                <div class='meta'>{commit['date']} • {commit['author']}</div>
                {desc_html}
            </div>
            """
        html += "</body></html>"
        self.updates_browser.setHtml(html)

    def _update_blob_density(self, value):
        """Updates the blob density in the parent window based on the slider."""
        if value > 0:
            self.parent().blob_density = 400000 / value
            if self.parent().blob_manager:
                self.parent().blob_manager.density = self.parent().blob_density
                self.parent().blob_manager.adjust_blob_count()

    def _update_notification_options(self, anim_type):
        """Disables direction selection if the animation type doesn't support it."""
        self.notification_dir_combo.setEnabled(anim_type != "Fade")

    def _update_default_font_styles(self, family):
        """Populates the style combo box for the default font."""
        if not family: return
        self.default_font_style_combo.blockSignals(True)
        self.default_font_style_combo.clear()

        sorted_styles = self.font_styles_cache.get(family, [])
        self.default_font_style_combo.addItems(sorted_styles)
        
        if self.initial_default_font_style in sorted_styles:
            self.default_font_style_combo.setCurrentText(self.initial_default_font_style)

        self.default_font_style_combo.blockSignals(False)

    @pyqtSlot(dict)
    def _on_fonts_loaded(self, result):
        self.font_styles_cache = result["font_styles_cache"]
        self.base_font_families = result["base_font_families"]
        self._populate_font_list()
        self._font_list_populated = True
        
        if self.initial_font_family in self.base_font_families:
            self.font_family_combo.setCurrentText(self.initial_font_family)
            self._update_font_styles(self.initial_font_family, restore_style=self.initial_font_style)
        else:
            # Fallback if font not found, just update styles for whatever is selected
            self._update_font_styles(self.font_family_combo.currentText())

        if self.initial_default_font_family in self.base_font_families:
            self.default_font_family_combo.setCurrentText(self.initial_default_font_family)
            self._update_default_font_styles(self.initial_default_font_family)
        else:
            self._update_default_font_styles(self.default_font_family_combo.currentText())

        # Final update to render text previews correctly now that fonts are loaded
        self.update_previews()

    def _on_override_brightness_toggled(self, checked):
        self.govee_brightness_slider.setEnabled(checked)

    def _on_govee_brightness_changed(self, value):
        self.govee_brightness_label.setText(f"{value}%")

    def _on_default_brightness_changed(self, value):
        self.default_brightness_label.setText(f"{value}%")

    def _load_custom_fonts(self):
        loaded_families = set()
        font_dir = QDir(":/fonts/")
        for filename in font_dir.entryList(["*.ttf", "*.otf"], QDir.Files):
            font_path = f":/fonts/{filename}"
            font_id = QFontDatabase.addApplicationFont(font_path)
        return loaded_families

    def _populate_font_list(self):
        self.font_family_combo.clear()
        self.font_family_combo.addItems(self.base_font_families)
        self.default_font_family_combo.clear()
        self.default_font_family_combo.addItems(self.base_font_families)
            
    def _filter_font_list(self, search_text):
        current_selection = self.font_family_combo.currentText()
        self.font_family_combo.clear()
        
        if not search_text:
            filtered_families = self.base_font_families
        else:
            search_lower = search_text.lower()
            filtered_families = [
                base_family for base_family in self.base_font_families 
                if search_lower in base_family.lower()
            ]
        
        self.font_family_combo.addItems(filtered_families)
        if current_selection in filtered_families:
            self.font_family_combo.setCurrentText(current_selection)

    def update_stylesheet(self):
        # Optimization: Only update stylesheet if colors have changed
        if self._loading_state: return
        
        if hasattr(self, 'text_border_checkbox'):
            border_enabled = self.text_border_checkbox.isChecked()
        else:
            border_enabled = getattr(self, 'initial_text_border_enabled', False)
        
        current_params = (self.ui_bg_color.name(), self.ui_text_color.name(), self.ui_accent_color.name(), border_enabled)
        
        if getattr(self, '_last_stylesheet_params', None) == current_params:
            return
        self._last_stylesheet_params = current_params
        
        sheet = get_common_stylesheet(self.ui_bg_color, self.ui_text_color, self.ui_accent_color)
        if border_enabled:
            sheet += f"""
                QPushButton, QCheckBox, QRadioButton, QGroupBox {{
                    color: transparent;
                }}
                QComboBox {{
                    color: {self.ui_text_color.name()};
                }}
            """
        self.setStyleSheet(sheet)
        self._update_blob_buttons_style()

    def _update_blob_buttons_style(self):
        # High contrast style for blob buttons to ensure they are visible
        btn_style = f"""
            QPushButton {{
                background-color: {self.ui_accent_color.name()};
                color: {self.ui_bg_color.name()};
                border: 1px solid {self.ui_text_color.name()};
                border-radius: 4px;
                font-weight: bold;
                font-size: 16px;
            }}
            QPushButton:hover {{
                background-color: {self.ui_text_color.name()};
                color: {self.ui_bg_color.name()};
            }}
        """
        if hasattr(self, 'add_blob_color_btn'):
            self.add_blob_color_btn.setStyleSheet(btn_style)
        
        for widget_info in self.blob_picker_widgets:
            # The remove button is the last widget in the row layout
            row_layout = widget_info["row"].layout()
            if row_layout.count() > 0:
                item = row_layout.itemAt(row_layout.count() - 1)
                widget = item.widget()
                if widget and isinstance(widget, QPushButton) and widget.text() == "×":
                    widget.setStyleSheet(btn_style)

    def _create_case_controls(self, initial_case):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(15)
        
        radios = {
            "default": QRadioButton("Default"),
            "upper": QRadioButton("UPPER"),
            "lower": QRadioButton("lower")
        }
        radios[initial_case].setChecked(True)

        layout.addWidget(radios["default"])
        layout.addWidget(radios["upper"])
        layout.addWidget(radios["lower"])
        return radios, widget

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 12, 12)
        
        preview_bg = QColor(self.ui_bg_color)
        preview_bg.setAlpha(240) 
        painter.fillPath(path, preview_bg)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.y() < 220: 
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and not self.drag_pos.isNull():
            self.move(event.globalPos() - self.drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_pos = QPoint()

    def create_color_row(self, preview_widget, pick_button, reset_button=None):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)
        row_layout.addWidget(preview_widget)
        row_layout.addWidget(pick_button)
        if reset_button:
            row_layout.addWidget(reset_button)
        row_layout.addStretch()
        return row_widget

    def _create_color_picker(self, initial_color, pick_callback, reset_callback=None, is_text=False):
        preview = ColorPreviewLabel("Aa" if is_text else "")
        preview.setFixedSize(80, 32)
        preview.setAlignment(Qt.AlignCenter)
        preview.setFont(QFont("Inter", 12, QFont.Bold))
        preview.setStyleSheet(f"background-color: {initial_color.name()}; color: {self.ui_text_color.name() if is_text else 'transparent'}; border-radius: 5px; border: 1px solid #555;")

        pick_button = QPushButton("Pick...")
        pick_button.clicked.connect(pick_callback)

        reset_button = None
        if reset_callback:
            reset_button = QPushButton("Auto")
            reset_button.setToolTip("Reset to automatic color detection")
            reset_button.clicked.connect(reset_callback)

        return preview, pick_button, reset_button

    def _update_font_styles(self, family, restore_style=None):
        if not family: return
        
        # Optimization: If family hasn't changed, just try to restore style if provided
        if getattr(self, '_current_styles_family', None) == family:
            if restore_style:
                index = self.font_style_combo.findText(restore_style)
                if index != -1:
                    self.font_style_combo.setCurrentIndex(index)
            return

        self._current_styles_family = family
        self.font_style_combo.blockSignals(True) 
        self.font_style_combo.clear()

        sorted_styles = self.font_styles_cache.get(family, [])
        self.font_style_combo.addItems(sorted_styles)

        preferred_defaults = [restore_style] if restore_style else []
        preferred_defaults.extend(["Regular", "Normal", "Book", "Roman", "Medium"])

        for style in preferred_defaults:
            if style and style in sorted_styles:
                index = self.font_style_combo.findText(style)
                if index != -1:
                    self.font_style_combo.setCurrentIndex(index)
                    break

        self.font_style_combo.blockSignals(False)

    def _on_override_font_toggled(self, checked):
        self.font_search_input.setEnabled(checked)
        self.font_family_combo.setEnabled(checked)
        self.font_style_combo.setEnabled(checked)
        self.font_size_label.setEnabled(checked) # Ensure label is disabled too
        if not checked:
            default_family = self.parent().default_font_family
            default_style = self.parent().default_font_style
            self.font_family_combo.setCurrentText(default_family)
            self._update_font_styles(default_family, restore_style=default_style)
        self.update_previews()

    def _on_override_size_toggled(self, checked):
        self.font_size_slider.setEnabled(checked)
        if not checked:
            # Reset to default for preview if unchecked
            self.font_size_slider.setValue(self.parent().default_font_size_scale)
        self.update_previews()


    def _on_override_progress_bar_toggled(self, checked):
        self.progress_bar_checkbox.setEnabled(checked)
        if not checked:
            self.progress_bar_checkbox.setChecked(self.default_progress_bar_checkbox.isChecked())


    def _on_override_border_size_toggled(self, checked):
        self.text_border_size_slider.setEnabled(checked)
        if not checked:
            # Reset to default for preview if unchecked
            self.text_border_size_slider.setValue(self.initial_default_text_border_size)
        self.update_previews()

    def _on_auto_text_toggled(self, checked, recalculate=True):
        self.is_text_color_auto = checked
        is_manual_mode = not checked
        self.pick_text_btn.setEnabled(True) # Always allow picking to switch to manual
        self.reset_text_btn.setEnabled(is_manual_mode)
        
        if checked and recalculate:
            # If we just switched to auto, recalculate the color
            self._update_auto_text_color()
        
        self.update_previews()

    def _update_auto_text_color(self):
        """Recalculates and sets the text color if in auto mode."""
        if self.is_text_color_auto:
            auto_color_rgb = get_best_text_color(self.ui_bg_color.getRgb()[:3], self.ui_accent_color.getRgb()[:3])
            self.ui_text_color = QColor(*auto_color_rgb)
            self.update_previews()
            self.update_stylesheet()
        self._update_auto_text_border_color()

    def _on_auto_text_border_toggled(self, checked, recalculate=True):
        self.is_text_border_color_auto = checked
        self.pick_text_border_btn.setEnabled(True)
        self.reset_text_border_btn.setEnabled(not checked)
        if checked and recalculate:
            self._update_auto_text_border_color()

    def _update_auto_text_border_color(self):
        if self.is_text_border_color_auto:
            candidates = [self.ui_accent_color.getRgb()[:3]]
            candidates.extend([c.getRgb()[:3] for c in self.blob_colors])
            
            auto_border = get_best_border_color(self.ui_bg_color.getRgb()[:3], self.ui_text_color.getRgb()[:3], candidates)
            self.text_border_color = QColor(*auto_border)
            self.update_previews()

    def _update_bg_accent_buttons(self):
        self.reset_ui_bg_btn.setEnabled(not self.is_bg_auto)
        self.reset_ui_accent_btn.setEnabled(not self.is_accent_auto)

    def update_previews(self):
        if self._loading_state: return
        self.ui_bg_preview.setStyleSheet(f"background-color: {self.ui_bg_color.name()};")
        self.ui_accent_preview.setStyleSheet(f"background-color: {self.ui_accent_color.name()};")
        
        # Update text preview
        self.text_preview.setBorder(self.text_border_checkbox.isChecked(), self.text_border_color)
        self.text_preview.setBorderSize(self.text_border_size_slider.value())
        
        # Update border color controls enabled state based on border enabled state
        is_border_on = self.text_border_checkbox.isChecked()
        self.text_border_preview.setEnabled(is_border_on)
        self.pick_text_border_btn.setEnabled(is_border_on)
        self.reset_text_border_btn.setEnabled(is_border_on and not self.is_text_border_color_auto)
        self.text_border_preview.setStyleSheet(f"background-color: {self.text_border_color.name()};")
        
        self.text_preview.setStyleSheet(f"background-color: {self.ui_bg_color.name()}; color: transparent;")
        self.text_preview.setCustomTextColor(self.ui_text_color)
        
        # Update the global event filter for buttons, checkboxes, etc.
        self.ui_event_filter.setSettings(self.text_border_checkbox.isChecked(), self.text_border_color, self.text_border_size_slider.value(), self.ui_text_color)
        self.update() # Trigger repaint for filtered widgets

        for lbl in self.ui_labels:
            lbl.setBorder(self.text_border_checkbox.isChecked(), self.text_border_color, self.text_border_size_slider.value())
            lbl.setCustomTextColor(self.ui_text_color)

        db = QFontDatabase()
        font = db.font(self.font_family_combo.currentText(), self.font_style_combo.currentText(), -1)
        preview_scale = self.font_size_slider.value() / 100.0
        font.setPixelSize(int(18 * preview_scale))
        self.text_preview.setCustomFont(font)
        self.text_preview_shadow.setEnabled(self.shadow_checkbox.isChecked())

        title_case = self._get_selected_case(self.title_case_radios)
        artist_case = self._get_selected_case(self.artist_case_radios)
        title_preview_char = self._apply_case_transform("A", title_case)
        artist_preview_char = self._apply_case_transform("a", artist_case)
        self.text_preview.setText(title_preview_char + artist_preview_char)

        self.text_preview_shadow.setColor(QColor(0,0,0,100)); self.text_preview_shadow.setBlurRadius(8); self.text_preview_shadow.setOffset(2,2)

        for picker in self.govee_color_pickers:
            picker["preview"].setStyleSheet(f"background-color: {picker['color'].name()};")
        for i, widget_info in enumerate(self.blob_picker_widgets):
            if i < len(self.blob_colors):
                widget_info["preview"].setStyleSheet(f"background-color: {self.blob_colors[i].name()};")
        palette = self.palette()
        palette.setColor(self.foregroundRole(), self.ui_text_color)
        self.setPalette(palette)
        self.render_updates()
        self.update_stylesheet()
        self.update() 

    def pick_ui_bg_color(self):
        new_color = self._get_themed_color(self.ui_bg_color, "Select Player Background")
        if new_color.isValid():
            self.ui_bg_color = new_color
            self.is_bg_auto = False
            self._update_bg_accent_buttons()
            self._update_auto_text_color()
            self.update_previews()
            self.update_stylesheet()

    def reset_ui_bg_color(self):
        self.is_bg_auto = True
        self.regenerate_theme()
    
    def pick_ui_accent_color(self):
        new_color = self._get_themed_color(self.ui_accent_color, "Select Art Border Color")
        if new_color.isValid():
            self.ui_accent_color = new_color
            self.is_accent_auto = False
            self._update_bg_accent_buttons()
            self._update_auto_text_border_color()
            self.update_previews()

    def reset_ui_accent_color(self):
        self.is_accent_auto = True
        self.regenerate_theme()

    def pick_text_color(self):
        new_color = self._get_themed_color(self.ui_text_color, "Select Text Color")
        if new_color.isValid():
            # Picking a color always puts us in manual mode
            self.is_text_color_auto = False
            self.ui_text_color = new_color
            self._on_auto_text_toggled(False)
            
            # FIX: Manually picking text color should NOT auto-enable the border.
            # We assume if the user is picking text, they want full manual control.
            # We disable the auto-border logic so it doesn't force the outline on.
            self.is_text_border_auto = False
            self._update_text_border_auto_state()
            
            self.update_previews()
            self.update_stylesheet()
    
    def reset_text_color(self):
        self._on_auto_text_toggled(True)

    def pick_text_border_color(self):
        new_color = self._get_themed_color(self.text_border_color, "Select Text Border Color")
        if new_color.isValid():
            self.is_text_border_color_auto = False
            self._on_auto_text_border_toggled(False)
            self.text_border_color = new_color
            self.update_previews()

    def reset_text_border_color(self):
        self._on_auto_text_border_toggled(True)

    def _on_text_border_toggled(self, checked):
        # If the user manually toggles, we leave auto mode
        self.is_text_border_auto = False
        self._update_text_border_auto_state()
        self.update_previews()

    def reset_text_border_enable(self):
        self.is_text_border_auto = True
        self._update_auto_text_border_enable()
        self._update_text_border_auto_state()
        self.update_previews()

    def _update_text_border_auto_state(self):
        self.reset_text_border_enable_btn.setEnabled(not self.is_text_border_auto)

    def _update_auto_text_border_enable(self):
        if self.is_text_border_auto:
            # Calculate contrast to decide if border is needed
            contrast = get_contrast_ratio(self.ui_text_color.getRgb()[:3], self.ui_bg_color.getRgb()[:3])
            border_needed = contrast < 3.5
            self.text_border_checkbox.setChecked(border_needed)

    def pick_govee_color(self, index):
        current_picker = self.govee_color_pickers[index]
        device_name = self.govee_devices[index].get('name', f'Light {index + 1}')
        new_color = self._get_themed_color(current_picker["color"], f"Select Color for {device_name}")
        if new_color.isValid():
            current_picker["color"] = new_color
            self.is_lights_auto = False
            self.update_previews() 

    def _add_blob_color_row(self, color, index):
        callback = lambda checked, i=index: self.pick_blob_color(i)
        preview, button, _ = self._create_color_picker(color, callback)
        row_widget = self.create_color_row(preview, button)
        
        # Add per-blob remove button
        remove_btn = QPushButton("×")
        remove_btn.setFixedSize(35, 35)
        remove_btn.setProperty("no_text_border", True)
        remove_btn.setToolTip("Remove this blob")
        remove_btn.clicked.connect(lambda checked, i=index: self.remove_blob_color(i))
        # Note: Style will be applied by _update_blob_buttons_style called in update_stylesheet
        # Add to the end of the row layout (after the stretch)
        row_widget.layout().addWidget(remove_btn)

        label_text = self._create_label(f"Blob {index + 1}:")
        self.blob_layout.addRow(label_text, row_widget)
        
        self.blob_picker_widgets.append({"preview": preview, "button": button, "row": row_widget, "label": label_text})
        # Install filter on new widgets
        self._install_filter_recursive(row_widget)

    def add_blob_color_picker(self):
        if len(self.blob_colors) >= 8: return
        last_color = self.blob_colors[-1] if self.blob_colors else QColor("blue")
        new_color = last_color.lighter(110)
        self.blob_colors.append(new_color)
        self.is_blob_auto = False
        self.refresh_blob_rows()
        self._update_blob_buttons_style() # Ensure new button is styled
        self.update_previews()

    def remove_blob_color(self, index):
        if len(self.blob_colors) <= 1: return
        self.blob_colors.pop(index)
        self.is_blob_auto = False; QApplication.processEvents()
        self.refresh_blob_rows()
        self._update_blob_buttons_style()
        self.update_previews()

    def refresh_blob_rows(self):
        """Rebuilds the blob color rows to ensure indices and labels are correct."""
        # Remove all rows from the layout. 
        # Note: removeRow(0) automatically deletes the widgets in that row.
        while self.blob_layout.rowCount() > 0:
            self.blob_layout.removeRow(0)
            
        # Clean up references in ui_labels
        # Since widgets are already deleted by removeRow, we MUST NOT call deleteLater().
        # We simply remove the invalid python wrappers from our list.
        for widget_info in self.blob_picker_widgets:
            if widget_info["label"] in self.ui_labels:
                self.ui_labels.remove(widget_info["label"])
            
        self.blob_picker_widgets = []

        # Rebuild rows with fresh indices based on current blob_colors list
        for i, color in enumerate(self.blob_colors):
            self._add_blob_color_row(color, i)
        
        # Re-apply styles to the newly created buttons
        self._update_blob_buttons_style()

    def pick_blob_color(self, index):
        if index >= len(self.blob_colors): return
        new_color = self._get_themed_color(self.blob_colors[index], f"Select Blob {index + 1} Color")
        if new_color.isValid():
            self.blob_colors[index] = new_color
            self.is_blob_auto = False
            self.update_previews()

    def reset_blobs_to_auto(self):
        self.is_blob_auto = True
        self.regenerate_theme()

    def reset_lights_to_auto(self):
        self.is_lights_auto = True
        self.regenerate_theme()

    def set_custom_art(self):
        dialog = FramelessFileDialog(self, "Select Custom Album Art", "", "Images (*.png *.jpg *.jpeg)", self.ui_bg_color, self.ui_accent_color, self.ui_text_color, self.text_border_checkbox.isChecked(), self.text_border_color, self.text_border_size_slider.value())
        if dialog.exec_() == QDialog.Accepted:
            files = dialog.selectedFiles()
            if files:
                file_path = files[0]
                try:
                    with open(file_path, "rb") as image_file:
                        self.custom_art_b64 = base64.b64encode(image_file.read()).decode('utf-8')
                    new_pixmap = QPixmap(file_path)
                    self.current_art_pixmap = new_pixmap
                except Exception as e:
                    print(f"Error loading custom art: {e}")
                    self.custom_art_b64 = None

    def reset_custom_art(self):
        self.custom_art_b64 = None
        original_pixmap = self.parent().art.pixmap()
        self.current_art_pixmap = original_pixmap

    def reset_theme_to_auto(self):
        """Resets all color overrides to auto and regenerates."""
        self.is_bg_auto = True
        self.is_accent_auto = True
        self.is_blob_auto = True
        self.is_lights_auto = True
        self.is_text_border_auto = True
        self.regenerate_theme()

    def update_font_data(self, font_styles_cache, base_font_families):
        """Receives font data from the main window when it's loaded."""
        self.font_styles_cache = font_styles_cache
        self.base_font_families = base_font_families

        if not self._is_ui_built: return

        if self._font_list_populated:
            return
        
        self.font_family_combo.clear()
        self.default_font_family_combo.clear()
        
        # Re-enable widgets
        self.font_family_combo.setEnabled(self.override_font_checkbox.isChecked())
        self.font_style_combo.setEnabled(self.override_font_checkbox.isChecked())
        self.font_search_input.setEnabled(self.override_font_checkbox.isChecked())
        self.default_font_family_combo.setEnabled(True)
        self.default_font_style_combo.setEnabled(True)

        self.font_styles_cache = font_styles_cache
        self.base_font_families = base_font_families
        self._on_fonts_loaded({
            "font_styles_cache": self.font_styles_cache,
            "base_font_families": self.base_font_families
        })

    def start_content_fade_and_reload(self, album_id, track_id, album_art_pixmap):
        """Fades the dialog out, reloads the content for the new track, and fades it back in."""
        self._pending_reload_data = {
            "album_id": album_id,
            "track_id": track_id,
            "album_art_pixmap": album_art_pixmap
        }
        
        # Stop any current fade and start a new fade-out from the current opacity.
        self.content_update_animation.stop()
        try: self.content_update_animation.finished.disconnect()
        except TypeError: pass

        self.content_update_animation.setStartValue(self.windowOpacity())
        self.content_update_animation.setEndValue(0.0)
        self.content_update_animation.finished.connect(self._on_content_fade_out_finished)
        self.content_update_animation.start()

    def _on_content_fade_out_finished(self):
        """Called after the fade-out. Reloads content and starts fade-in."""
        # Disconnect to prevent loops
        try: self.content_update_animation.finished.disconnect()
        except TypeError: pass

        # Reload content while invisible
        data = self._pending_reload_data
        self.load_track_state(
            data["album_id"],
            data["track_id"],
            data["album_art_pixmap"],
            animate=False # We are handling our own animation
        )

        # Fade back in
        self.content_update_animation.setStartValue(0.0)
        self.content_update_animation.setEndValue(1.0)
        self.content_update_animation.start()

    def regenerate_theme(self):
        pixmap = self.current_art_pixmap
        if not pixmap: return
        
        img = pixmap.toImage()
        buffer = QBuffer()
        buffer.open(QBuffer.ReadWrite)
        img.save(buffer, "PNG")
        pil_img = Image.open(io.BytesIO(buffer.data()))
        
        ui_palette, lights_palette, blob_palette, text_color, _ = extract_palette_from_image(pil_img)
        
        if self.is_bg_auto: self.ui_bg_color = QColor(*ui_palette[0])
        if self.is_accent_auto: self.ui_accent_color = QColor(*ui_palette[1])
        
        if self.is_blob_auto:
            self.blob_colors = [QColor(*c) for c in blob_palette]
            self.refresh_blob_rows()
        
        if self.is_lights_auto:
            for i, picker in enumerate(self.govee_color_pickers):
                picker["color"] = QColor(*lights_palette[i]) if i < len(lights_palette) else self.ui_accent_color
        
        if self.is_text_color_auto: self.ui_text_color = QColor(*text_color)
        if self.is_text_border_color_auto: self._update_auto_text_border_color()
        if self.is_text_border_auto: self._update_auto_text_border_enable()
             
        self._update_bg_accent_buttons()
        self.update_previews()
        self.update_stylesheet()

    def load_track_state(self, album_id, track_id, album_art_pixmap, animate=True):
        self._loading_state = True
        
        # Block signals to prevent unnecessary updates during load
        self.font_family_combo.blockSignals(True)
        self.font_style_combo.blockSignals(True)
        self.shadow_checkbox.blockSignals(True)
        self.text_border_checkbox.blockSignals(True)
        self.override_font_checkbox.blockSignals(True)
        self.override_size_checkbox.blockSignals(True)
        
        try:
            self.album_id = album_id
            self.track_id = track_id
            self.current_art_pixmap = album_art_pixmap
            
            # Reload cache data
            track_cache = self.color_cache.get_album_data(self.track_id) or {}
            cached_data = track_cache or self.color_cache.get_album_data(self.album_id) or {}
            if isinstance(cached_data, list): cached_data = {"ui_palette": cached_data}
            self.cached_data = cached_data
            
            main_window_state = self.parent()
            
            # --- Update Internal State ---
            ui_palette = self.cached_data.get("ui_palette", main_window_state._current_ui_palette or [[30, 30, 30], [100, 100, 100]])
            player_bg_rgb = self.cached_data.get("player_bg_color")
            
            self.ui_bg_color = QColor(*player_bg_rgb) if player_bg_rgb else QColor(*ui_palette[0])
            self.ui_accent_color = QColor(*ui_palette[1]) if len(ui_palette) > 1 else self.ui_bg_color.lighter(150)
            
            text_color_rgb = self.cached_data.get("text_color")
            self.is_text_color_auto = text_color_rgb is None
            
            if self.is_text_color_auto:
                if hasattr(main_window_state, '_current_text_color') and main_window_state._current_text_color:
                    self.ui_text_color = QColor(*main_window_state._current_text_color)
                else:
                    auto_text = get_best_text_color(self.ui_bg_color.getRgb()[:3], self.ui_accent_color.getRgb()[:3])
                    self.ui_text_color = QColor(*auto_text)
            else:
                self.ui_text_color = QColor(*text_color_rgb)
                
            blob_palette = self.cached_data.get("blob_palette", main_window_state._current_blob_palette)
            self.blob_colors = [QColor(*c) for c in blob_palette]
            if not self.blob_colors:
                self.blob_colors = [self.ui_accent_color, self.ui_accent_color.lighter(120), self.ui_accent_color.darker(120)]
                
            # Update Lights
            lights_config = self.cached_data.get("lights_config", {})
            if lights_config.get("mode") == "custom" and lights_config.get("palette"):
                current_lights = lights_config.get("palette")
            else:
                current_lights = main_window_state._current_lights_palette
            
            # Update Govee pickers
            for i, picker in enumerate(self.govee_color_pickers):
                if i < len(current_lights):
                    picker["color"] = QColor(*current_lights[i])
                else:
                    picker["color"] = self.ui_accent_color.lighter(110 + i*10)
            
            # Update Initial State for Change Detection
            self.initial_ui_bg_color = QColor(self.ui_bg_color)
            self.initial_ui_accent_color = QColor(self.ui_accent_color)
            self.initial_ui_text_color = QColor(self.ui_text_color)
            self.initial_is_text_color_auto = self.is_text_color_auto
            self.initial_blob_colors = [QColor(c) for c in self.blob_colors]
            self.effective_initial_lights_palette = [QColor(p["color"]) for p in self.govee_color_pickers]
            
            # --- Update Widgets ---
            self.ui_bg_preview.setStyleSheet(f"background-color: {self.ui_bg_color.name()};")
            self.ui_accent_preview.setStyleSheet(f"background-color: {self.ui_accent_color.name()};")
            
            self.refresh_blob_rows()
            
            # Text Settings
            self.shadow_checkbox.setChecked(self.cached_data.get("shadow_enabled", main_window_state._current_shadow_enabled))
            self.initial_shadow_enabled = self.shadow_checkbox.isChecked()
            
            font_family = self.cached_data.get("font_family")
            
            # FIX: Override defaults logic. If no specific font saved, default to Overridden=True
            if font_family is None:
                self.is_font_family_overridden = True
                target_font = main_window_state._current_font_family
                target_style = main_window_state._current_font_style
            else:
                self.is_font_family_overridden = True # Always True if we have data or default
                target_font = font_family
                target_style = self.cached_data.get("font_style")

            self.override_font_checkbox.setChecked(self.is_font_family_overridden)
            self.font_family_combo.setEnabled(self.is_font_family_overridden)
            self.font_style_combo.setEnabled(self.is_font_family_overridden)
            self.font_search_input.setEnabled(self.is_font_family_overridden)
            
            self.initial_font_family = target_font
            self.initial_font_style = target_style
            
            if self._font_list_populated:
                self.font_family_combo.setCurrentText(target_font)
                self._update_font_styles(target_font, restore_style=target_style)
            
            # Font Size
            font_size = self.cached_data.get("font_size_scale")
            self.is_font_size_overridden = font_size is not None
            self.override_size_checkbox.setChecked(self.is_font_size_overridden)
            self.font_size_slider.setValue(font_size if self.is_font_size_overridden else main_window_state._current_font_size_scale)
            
            # FIX: Explicitly disable slider if unchecked
            self.font_size_slider.setEnabled(self.is_font_size_overridden)
            
            self.initial_font_size_scale = self.font_size_slider.value()
            
            # Text Border
            text_border_enabled = self.cached_data.get("text_border_enabled", main_window_state._current_text_border_enabled)
            self.text_border_checkbox.setChecked(text_border_enabled)
            self.initial_text_border_enabled = text_border_enabled
            self.is_text_border_auto = "text_border_enabled" not in self.cached_data
            
            text_border_color_rgb = self.cached_data.get("text_border_color")
            self.is_text_border_color_auto = text_border_color_rgb is None
            if text_border_color_rgb:
                self.text_border_color = QColor(*text_border_color_rgb)
            elif hasattr(main_window_state, '_current_text_border_color') and main_window_state._current_text_border_color:
                self.text_border_color = QColor(*main_window_state._current_text_border_color)
            else:
                self.text_border_color = QColor(0, 0, 0)
            self.initial_text_border_color = QColor(self.text_border_color)
            
            text_border_size = self.cached_data.get("text_border_size")
            self.is_border_size_overridden = text_border_size is not None
            self.override_border_size_checkbox.setChecked(self.is_border_size_overridden)
            self.text_border_size_slider.setValue(text_border_size if self.is_border_size_overridden else main_window_state._current_text_border_size)
            
            # FIX: Explicitly disable slider if unchecked
            self.text_border_size_slider.setEnabled(self.is_border_size_overridden)
            
            self.initial_text_border_size = self.text_border_size_slider.value()
            
            # Case
            t_case = self.cached_data.get("title_case", "default")
            a_case = self.cached_data.get("artist_case", "default")
            for k, r in self.title_case_radios.items(): r.setChecked(k == t_case)
            for k, r in self.artist_case_radios.items(): r.setChecked(k == a_case)
            self.initial_title_case = t_case
            self.initial_artist_case = a_case
            
            # Progress Bar
            pb_enabled = self.cached_data.get("progress_bar_enabled")
            self.is_progress_bar_overridden = pb_enabled is not None
            self.override_progress_bar_checkbox.setChecked(self.is_progress_bar_overridden)
            self.progress_bar_checkbox.setChecked(pb_enabled if self.is_progress_bar_overridden else main_window_state.default_progress_bar_enabled)
            
            # FIX: Explicitly disable checkbox if unchecked
            self.progress_bar_checkbox.setEnabled(self.is_progress_bar_overridden)
            
            self.initial_progress_bar_enabled = self.progress_bar_checkbox.isChecked()
            
            # Brightness
            cached_brightness = self.cached_data.get("govee_brightness")
            self.is_brightness_overridden = cached_brightness is not None
            self.override_brightness_checkbox.setChecked(self.is_brightness_overridden)
            
            # FIX: Explicitly disable slider if unchecked
            self.govee_brightness_slider.setEnabled(self.is_brightness_overridden)
            
            if self.is_brightness_overridden:
                self.govee_brightness_slider.setValue(int(cached_brightness * 100))
            else:
                self.govee_brightness_slider.setValue(int(main_window_state.default_govee_brightness * 100))
            self.initial_track_brightness = self.govee_brightness_slider.value()
            self.initial_is_brightness_overridden = self.is_brightness_overridden

            # Custom Art
            self.custom_art_b64 = track_cache.get("custom_art_b64")
            
            # --- Handle non-Spotify source ---
            is_spotify_source = (self.media_source == 'spotify')
            self.ui_group.setEnabled(is_spotify_source)
            self.govee_group.setEnabled(is_spotify_source)
            self.art_group.setEnabled(is_spotify_source)
            self.save_button.setEnabled(True)
            self.pick_text_btn.setEnabled(is_spotify_source)
            self.reset_text_btn.setEnabled(is_spotify_source and not self.is_text_color_auto)
            self.pick_text_border_btn.setEnabled(is_spotify_source and self.text_border_checkbox.isChecked())
            self.reset_text_border_btn.setEnabled(is_spotify_source and self.text_border_checkbox.isChecked() and not self.is_text_border_color_auto)

            if not is_spotify_source:
                self.cancel_button.setText("Close")
                self.disabled_info_label.show()
            else:
                self.cancel_button.setText("Cancel")
                self.disabled_info_label.hide()

            # Reset Auto Flags
            self.is_bg_auto = "ui_palette" not in self.cached_data and "player_bg_color" not in self.cached_data
            self.is_accent_auto = "ui_palette" not in self.cached_data
            self.is_blob_auto = "blob_palette" not in self.cached_data
            self.is_lights_auto = "lights_config" not in self.cached_data
            self.is_text_border_auto = "text_border_enabled" not in self.cached_data

            if not self._is_ui_built:
                self._pending_load_state = (album_id, track_id, album_art_pixmap, animate)
                # Update loading screen appearance to match new theme
                self.loading_label.setStyleSheet(f"color: {self.ui_text_color.name()}; font-size: 18px; font-weight: bold;")
                self.setStyleSheet(get_common_stylesheet(self.ui_bg_color, self.ui_text_color, self.ui_accent_color))
                if animate: self.animate_entry()
                elif not self.isVisible(): self.show(); self.raise_(); self.activateWindow()
                return
            
            self._update_bg_accent_buttons()
            self._on_auto_text_toggled(self.is_text_color_auto, recalculate=False)
            self._on_auto_text_border_toggled(self.is_text_border_color_auto, recalculate=False)
            
        finally:
            self._loading_state = False
            self.font_family_combo.blockSignals(False)
            self.font_style_combo.blockSignals(False)
            self.shadow_checkbox.blockSignals(False)
            self.text_border_checkbox.blockSignals(False)
            self.override_font_checkbox.blockSignals(False)
            self.override_size_checkbox.blockSignals(False)

        self.update_previews()
        self.update_stylesheet()
        
        if animate:
            self.animate_entry()
        elif not self.isVisible():
            self.show()
            self.raise_()
            self.activateWindow()

    def _get_selected_case(self, radio_group):
        for case, radio in radio_group.items():
            if radio.isChecked():
                return case
        return "default"

    def _apply_case_transform(self, text, case_mode):
        if case_mode == "upper": return text.upper()
        if case_mode == "lower": return text.lower()
        return text

    def _get_global_changes(self):
        """Collects all changed global settings."""
        settings = QSettings("SpotifySync", "App")
        changes = []
        
        def check(key, label, current_val, default_val=None, type_cast=str):
            stored_val = settings.value(key)
            
            if type_cast == bool:
                stored_val = (str(stored_val).lower() == 'true')
            elif type_cast == int:
                stored_val = int(stored_val) if stored_val is not None else default_val
            elif type_cast == float:
                stored_val = float(stored_val) if stored_val is not None else default_val
            else:
                stored_val = str(stored_val) if stored_val is not None else default_val

            # Comparison with tolerance for floats
            is_diff = False
            if type_cast == float:
                is_diff = abs(current_val - stored_val) > 0.001
            else:
                is_diff = current_val != stored_val

            if is_diff:
                changes.append({"key": key, "label": label, "value": current_val, "changed": True, "type": "global"})

        # Typography
        check("default_font_family", "Default Font Family", self.default_font_family_combo.currentText(), "Trebuchet MS")
        check("default_font_style", "Default Font Style", self.default_font_style_combo.currentText(), "Bold")
        check("default_font_size_scale", "Default Font Size", self.default_font_size_slider.value(), 100, int)
        check("default_progress_bar_enabled", "Default Progress Bar", self.default_progress_bar_checkbox.isChecked(), False, bool)
        check("default_text_border_enabled", "Default Text Border", self.default_text_border_checkbox.isChecked(), False, bool)
        check("default_text_border_size", "Default Border Size", self.default_text_border_size_slider.value(), 3, int)

        # Notifications
        check("notification_enabled", "Notifications Enabled", self.notification_enabled_checkbox.isChecked(), False, bool)
        check("notification_monitor_index", "Notification Monitor", self.notification_monitor_combo.currentIndex(), 0, int)
        check("notification_size", "Notification Size", self.notif_size_slider.value(), 1, int)
        check("notification_corner", "Notification Corner", self.notification_corner_combo.currentText(), "Top-Right")
        check("notification_anim", "Notification Animation", self.notification_anim_combo.currentText(), "Fade")
        check("notification_dir", "Notification Direction", self.notification_dir_combo.currentText(), "From Top")
        check("notification_permanent", "Notification Permanent", self.notif_permanent_checkbox.isChecked(), False, bool)
        check("notification_duration", "Notification Duration", self.notif_duration_slider.value(), 4000, int)
        check("notification_anim_duration", "Notification Anim Speed", self.notif_anim_speed_slider.value(), 500, int)
        check("notification_bg_opacity", "Notification Opacity", self.notif_opacity_slider.value(), 230, int)
        check("notification_border_enabled", "Notification Border", self.notif_border_checkbox.isChecked(), False, bool)
        check("notification_smart_hide", "Notification Smart Hide", self.notif_smart_hide_checkbox.isChecked(), False, bool)
        check("notification_ignore_taskbar", "Notification Ignore Taskbar", self.notif_ignore_taskbar_checkbox.isChecked(), True, bool)

        # Govee
        check("default_govee_brightness", "Default Brightness", self.default_brightness_slider.value() / 100.0, 1.0, float)

        return changes

    def _collect_theme_changes(self):
        """Collects all non-credential theme settings from the dialog."""
        potential_saves = []

        def check_auto(key, label, is_auto, current_val, initial_val):
            in_cache = key in self.cached_data
            if is_auto:
                if in_cache:
                    # It was manual, now auto -> Remove it
                    potential_saves.append({"key": key, "label": f"{label} (Reset to Auto)", "value": "__REMOVE__", "changed": True, "type": "theme"})
            else:
                # Manual mode
                changed = current_val != initial_val
                if in_cache or changed or (key == "text_border_enabled" and not current_val):
                     potential_saves.append({"key": key, "label": label, "value": current_val, "changed": changed or in_cache, "type": "theme"})

        def check_manual(key, label, current_val, initial_val, always_save=False):
            in_cache = key in self.cached_data
            changed = current_val != initial_val
            if in_cache or changed or always_save:
                potential_saves.append({"key": key, "label": label, "value": current_val, "changed": changed or in_cache or always_save, "type": "theme"})

        # Gather all potential settings
        check_auto("ui_palette", "Theme Colors", self.is_bg_auto and self.is_accent_auto, [list(self.ui_bg_color.getRgb()[:3]), list(self.ui_accent_color.getRgb()[:3])], [list(self.initial_ui_bg_color.getRgb()[:3]), list(self.initial_ui_accent_color.getRgb()[:3])])
        check_auto("player_bg_color", "Player Background", self.is_bg_auto, list(self.ui_bg_color.getRgb()[:3]), list(self.initial_ui_bg_color.getRgb()[:3]))
        check_auto("blob_palette", "Background Blob Colors", self.is_blob_auto, [list(c.getRgb()[:3]) for c in self.blob_colors], [list(c.getRgb()[:3]) for c in self.initial_blob_colors])
        check_manual("shadow_enabled", "Text Shadow", self.shadow_checkbox.isChecked(), self.initial_shadow_enabled)
        
        if self.override_font_checkbox.isChecked():
            check_manual("font_family", "Font Family", self.font_family_combo.currentText(), self.initial_font_family, always_save=True)
            check_manual("font_style", "Font Style", self.font_style_combo.currentText(), self.initial_font_style, always_save=True)
        else:
            if "font_family" in self.cached_data: potential_saves.append({"key": "font_family", "label": "Font Family (Reset)", "value": "__REMOVE__", "changed": True, "type": "theme"})
            if "font_style" in self.cached_data: potential_saves.append({"key": "font_style", "label": "Font Style (Reset)", "value": "__REMOVE__", "changed": True, "type": "theme"})
        
        t_case = self._get_selected_case(self.title_case_radios)
        if t_case != "default": check_manual("title_case", "Title Casing", t_case, self.initial_title_case, always_save=True)
        elif "title_case" in self.cached_data: potential_saves.append({"key": "title_case", "label": "Title Casing (Reset)", "value": "__REMOVE__", "changed": True, "type": "theme"})

        a_case = self._get_selected_case(self.artist_case_radios)
        if a_case != "default": check_manual("artist_case", "Artist Casing", a_case, self.initial_artist_case, always_save=True)
        elif "artist_case" in self.cached_data: potential_saves.append({"key": "artist_case", "label": "Artist Casing (Reset)", "value": "__REMOVE__", "changed": True, "type": "theme"})
        
        check_auto("text_border_enabled", "Text Border Enable", self.is_text_border_auto, self.text_border_checkbox.isChecked(), self.initial_text_border_enabled)
        check_auto("text_border_color", "Text Border Color", self.is_text_border_color_auto, list(self.text_border_color.getRgb()[:3]), list(self.initial_text_border_color.getRgb()[:3]))
        
        if self.override_border_size_checkbox.isChecked():
            check_manual("text_border_size", "Text Border Size", self.text_border_size_slider.value(), self.initial_text_border_size, always_save=True)
        elif "text_border_size" in self.cached_data:
            potential_saves.append({"key": "text_border_size", "label": "Text Border Size (Reset)", "value": "__REMOVE__", "changed": True, "type": "theme"})
            
        current_lights_palette = [list(p["color"].getRgb()[:3]) for p in self.govee_color_pickers]
        initial_lights_palette_list = [list(c.getRgb()[:3]) for c in self.effective_initial_lights_palette]
        check_auto("lights_config", "Govee Light Colors", self.is_lights_auto, {"mode": "custom", "palette": current_lights_palette}, {"mode": "custom", "palette": initial_lights_palette_list})

        if self.override_progress_bar_checkbox.isChecked():
            check_manual("progress_bar_enabled", "Progress Bar", self.progress_bar_checkbox.isChecked(), self.initial_progress_bar_enabled, always_save=True)
        elif "progress_bar_enabled" in self.cached_data:
            potential_saves.append({"key": "progress_bar_enabled", "label": "Progress Bar (Reset)", "value": "__REMOVE__", "changed": True, "type": "theme"})

        if self.override_size_checkbox.isChecked():
            check_manual("font_size_scale", "Font Size", self.font_size_slider.value(), self.initial_font_size_scale, always_save=True)
        elif "font_size_scale" in self.cached_data:
            potential_saves.append({"key": "font_size_scale", "label": "Font Size (Reset)", "value": "__REMOVE__", "changed": True, "type": "theme"})

        current_val = self.govee_brightness_slider.value() / 100.0 if self.override_brightness_checkbox.isChecked() else None
        initial_val = self.initial_track_brightness / 100.0 if self.initial_is_brightness_overridden else None
        if current_val != initial_val:
            check_manual("govee_brightness", "Brightness Override", current_val, initial_val, always_save=True)

        check_auto("text_color", "Text Color", self.is_text_color_auto, list(self.ui_text_color.getRgb()[:3]), list(self.initial_ui_text_color.getRgb()[:3]))

        return potential_saves
    
    def _populate_govee_table(self):
        self.govee_device_table.setRowCount(len(self.initial_govee_devices))
        for row, device_config in enumerate(self.initial_govee_devices):
            chk_box_item = QTableWidgetItem(); chk_box_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled); chk_box_item.setCheckState(Qt.Checked)
            self.govee_device_table.setItem(row, 0, chk_box_item)
            self.govee_device_table.setItem(row, 1, QTableWidgetItem(device_config.get("device", ""))); self.govee_device_table.setItem(row, 2, QTableWidgetItem(device_config.get("model", ""))); self.govee_device_table.setItem(row, 3, QTableWidgetItem(device_config.get("name", "")))
        self.govee_device_table.resizeColumnsToContents()

    def save_and_close(self, quick=False):
        # 1. Collect all changes from UI controls
        global_changes = self._get_global_changes()        
        theme_changes = []
        if self.media_source == 'spotify':
            theme_changes = self._collect_theme_changes()
        
        all_changes = global_changes + theme_changes
        
        # 2. Determine exactly which keys to save
        keys_to_save = []
        if quick:
            # Quick Save: Automatically select all items that have changed
            keys_to_save = [item['key'] for item in all_changes if item['changed']]
        else:
            # Standard Save: Prompt user if there are changes
            if not all_changes:
                self.accept()
                return

            dialog = SaveConfirmationDialog(all_changes, self.ui_bg_color, self.ui_accent_color, self.ui_text_color, self)
            if dialog.exec_() == QDialog.Accepted:
                keys_to_save = dialog.selected_keys
            else:
                return # Cancelled by user, keep dialog open

        # 3. Save Global Settings to Registry/Config
        settings = QSettings("SpotifySync", "App")
        for item in global_changes:
            if item['key'] in keys_to_save:
                val = item['value']
                if isinstance(val, bool):
                    settings.setValue(item['key'], "true" if val else "false")
                else:
                    settings.setValue(item['key'], val)

        # 4. Save Theme Settings to Cache
        if self.media_source == 'spotify':
            # Start with existing cache to preserve settings we aren't touching
            album_config = self.cached_data.copy()
            theme_keys_processed = False
            
            for item in theme_changes:
                if item['key'] in keys_to_save:
                    theme_keys_processed = True
                    # If value is the special remove marker, delete from cache (reverting to auto)
                    if item['value'] == "__REMOVE__":
                        album_config.pop(item['key'], None)
                    else:
                        album_config[item['key']] = item['value']
            
            # Apply updates to cache
            if theme_keys_processed:        
                self.color_cache.set_album_data(self.album_id, album_config)
                
                # Update parent window blob density immediately
                slider_value = self.blob_amount_slider.value()
                if self.parent():
                    self.parent().blob_density = 400000 / slider_value if slider_value > 0 else 200000

            # Handle Custom Art persistence
            if self.custom_art_b64:
                track_config = self.color_cache.get_album_data(self.track_id) or {}
                track_config["custom_art_b64"] = self.custom_art_b64
                self.color_cache.set_album_data(self.track_id, track_config)

        # 5. Notify Main Window to Refresh
        if keys_to_save or quick:
            self.config_saved.emit(self.album_id, self.color_cache.get_album_data(self.album_id) or {})

        # 6. Check for Credential Changes (Requires Restart)
        new_spotify_id = self.spotify_id_input.text().strip()
        new_spotify_secret = self.spotify_secret_input.text().strip()
        new_govee_key = self.govee_key_input.text().strip()

        new_govee_devices = []
        for row in range(self.govee_device_table.rowCount()):
            if self.govee_device_table.item(row, 0).checkState() == Qt.Checked:
                new_govee_devices.append({
                    "device": self.govee_device_table.item(row, 1).text(), 
                    "model": self.govee_device_table.item(row, 2).text(), 
                    "name": self.govee_device_table.item(row, 3).text()
                })
        
        new_govee_devices_json = json.dumps(sorted(new_govee_devices, key=lambda x: x['device']))
        initial_govee_devices_json = json.dumps(sorted(self.initial_govee_devices, key=lambda x: x['device']))

        credentials_changed = (new_spotify_id != self.initial_spotify_id or 
                               new_spotify_secret != self.initial_spotify_secret or 
                               new_govee_key != self.initial_govee_key or 
                               new_govee_devices_json != initial_govee_devices_json)

        if credentials_changed:
            msg = ThemedMessageBox("Restart Required", "Changing credentials requires an application restart. Save all changes and restart now?", 
                                   [("Yes", QDialog.Accepted), ("No", QDialog.Rejected)], self, self.ui_bg_color, self.ui_text_color, self.ui_accent_color, self.text_border_checkbox.isChecked(), self.text_border_color, self.text_border_size_slider.value())
            
            if msg.exec_() == QDialog.Accepted:
                settings.setValue("spotify_client_id", new_spotify_id.strip())
                settings.setValue("spotify_client_secret", new_spotify_secret.strip())
                settings.setValue("govee_api_key", new_govee_key.strip())
                settings.setValue("govee_devices", json.dumps(new_govee_devices))
                
                if os.path.exists(".cache"): os.remove(".cache")
                self.parent().restart_app()
            else:
                # User chose not to restart, but we still close the dialog as requested
                self.accept()
        else:
            # No credential changes, just close        
            self.accept()

    def find_govee_devices(self):
        api_key = self.govee_key_input.text().strip()
        if not api_key:
            self.govee_status_label.setText("Please enter a Govee API Key.")
            return

        self.find_govee_button.setEnabled(False)
        self.govee_status_label.setText("Searching for devices...")
        worker = GoveeDeviceFinderWorker(api_key)
        worker.signals.result.connect(self.on_govee_devices_found)
        worker.signals.error.connect(self.on_govee_find_error)
        worker.signals.finished.connect(lambda: self.find_govee_button.setEnabled(True))
        self.threadpool.start(worker)

    def on_govee_devices_found(self, devices):
        self.govee_status_label.setText(f"Success! Found {len(devices)} devices. Enable the ones you want to use.")
        
        existing_devices = {}
        for row in range(self.govee_device_table.rowCount()):
            device_id_item = self.govee_device_table.item(row, 1)
            if device_id_item:
                existing_devices[device_id_item.text()] = {"name": self.govee_device_table.item(row, 3).text(), "checked": self.govee_device_table.item(row, 0).checkState() == Qt.Checked}

        self.govee_device_table.setRowCount(len(devices))
        for row, device in enumerate(devices):
            device_id = device["device"]
            existing_config = existing_devices.get(device_id, {})
            chk_box_item = QTableWidgetItem(); chk_box_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_box_item.setCheckState(Qt.Checked if existing_config.get("checked", False) else Qt.Unchecked)
            self.govee_device_table.setItem(row, 0, chk_box_item)
            name = existing_config.get("name", device["deviceName"])
            name_item = QTableWidgetItem(name)
            name_item.setToolTip(name)
            id_item = QTableWidgetItem(device_id); id_item.setFlags(id_item.flags() & ~Qt.ItemIsEditable); self.govee_device_table.setItem(row, 1, id_item)
            model_item = QTableWidgetItem(device["model"]); model_item.setFlags(model_item.flags() & ~Qt.ItemIsEditable); self.govee_device_table.setItem(row, 2, model_item)
            self.govee_device_table.setItem(row, 3, name_item)
        self.govee_device_table.resizeColumnToContents(0)
        self.govee_device_table.resizeColumnToContents(1)
        self.govee_device_table.resizeColumnToContents(2)

    def on_govee_find_error(self, error_msg):
        self.govee_status_label.setText(f"Error: {error_msg}")

    def _get_themed_color(self, initial_color, title):
        """Opens the standard Windows/OS color picker."""
        main_window = self.parent()
        recent_colors = main_window.recent_colors if hasattr(main_window, 'recent_colors') else []

        dialog = FramelessColorDialog(self, self.ui_bg_color, self.ui_accent_color, self.ui_text_color, self.text_border_checkbox.isChecked(), self.text_border_color, self.text_border_size_slider.value())
        dialog.setWindowTitle(title)
        # Use the non-native dialog to allow for theming and custom colors.
        dialog.setOptions(QColorDialog.ShowAlphaChannel | QColorDialog.DontUseNativeDialog)
        dialog.setCurrentColor(initial_color)

        for i in range(16): # Set recent colors
            if i < len(recent_colors):
                dialog.setCustomColor(i, recent_colors[i])

        if dialog.exec_() == QDialog.Accepted:
            new_color = dialog.currentColor()
            if new_color.isValid() and hasattr(main_window, 'recent_colors'):
                # Update recent colors list
                main_window.recent_colors = [c for c in main_window.recent_colors if c.rgb() != new_color.rgb()]
                main_window.recent_colors.insert(0, new_color)
                main_window.recent_colors = main_window.recent_colors[:16]
            return new_color
        return initial_color

    def toggle_credential_visibility(self, checked):
        """Shows or hides the API credential fields."""
        button = self.sender()
        if checked:
            self.spotify_id_input.setEchoMode(QLineEdit.Normal)
            self.spotify_secret_input.setEchoMode(QLineEdit.Normal)
            self.govee_key_input.setEchoMode(QLineEdit.Normal)
            button.setText("Hide Credentials")
        else:
            self.spotify_id_input.setEchoMode(QLineEdit.Password)
            self.spotify_secret_input.setEchoMode(QLineEdit.Password)
            self.govee_key_input.setEchoMode(QLineEdit.Password)
            button.setText("Show Credentials")

    def confirm_clear_cache(self):
        warning_msg = (
            "Are you sure you want to delete the entire album color cache?\n\n"
            "This will permanently remove:\n"
            "- All auto-detected color palettes\n"
            "- All manually customized album themes\n"
            "- All custom album art overrides\n\n"
            "This action cannot be undone."
        )
        msg = ThemedMessageBox("Critical Warning", warning_msg, [("Yes", QDialog.Accepted), ("No", QDialog.Rejected)], self, self.ui_bg_color, self.ui_text_color, self.ui_accent_color, self.text_border_checkbox.isChecked(), self.text_border_color, self.text_border_size_slider.value())
        
        if msg.exec_() == QDialog.Accepted:
             # Second confirmation for safety
            confirm_msg = "Please confirm one last time: Do you really want to wipe all cached data?"
            msg2 = ThemedMessageBox("Final Confirmation", confirm_msg, [("Yes", QDialog.Accepted), ("No", QDialog.Rejected)], self, self.ui_bg_color, self.ui_text_color, self.ui_accent_color, self.text_border_checkbox.isChecked(), self.text_border_color, self.text_border_size_slider.value())
            
            if msg2.exec_() == QDialog.Accepted:
                self.color_cache.clear()
                ThemedMessageBox("Success", "Album cache has been cleared.", [("OK", QDialog.Accepted)], self, self.ui_bg_color, self.ui_text_color, self.ui_accent_color, self.text_border_checkbox.isChecked(), self.text_border_color, self.text_border_size_slider.value()).exec_()