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
                             QGridLayout,
                             QApplication, QAbstractButton, QStyle, QStyleOptionSlider)
from PyQt5.QtGui import (QPainter, QPainterPath, QPen, QColor, QFont, QFontDatabase, 
                         QGuiApplication, QPixmap, QImage, QKeySequence)

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
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        self._TITLE_BAR_HEIGHT = 50
        self.title_bar = QWidget()
        self.title_bar.setFixedHeight(self._TITLE_BAR_HEIGHT)
        self.title_bar.setStyleSheet("background: transparent;")
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(16, 0, 10, 0)
        title_layout.setSpacing(8)

        self.title_label = BorderedLabel(title)
        self.title_label.setBorder(self.border_enabled, self.border_color, self.border_width)
        self.title_label.setCustomTextColor(self.text_color)
        self.title_label.setFont(QFont("Segoe UI", 11, QFont.DemiBold))

        self.close_btn = QPushButton("×")
        self.close_btn.setFixedSize(32, 32)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(self.reject)

        title_layout.addWidget(self.title_label)
        title_layout.addStretch()
        title_layout.addWidget(self.close_btn)
        self._main_layout.addWidget(self.title_bar)

        self._title_separator = QWidget()
        self._title_separator.setFixedHeight(1)
        self._main_layout.addWidget(self._title_separator)

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(20, 14, 20, 20)
        self._main_layout.addWidget(self.content_widget)
        self.apply_theme()
    def _apply_button_focus_policy(self):
        # Prevent Tab key from cycling to buttons in modal menus.
        for btn in self.findChildren(QPushButton):
            btn.setFocusPolicy(Qt.ClickFocus)

    def showEvent(self, event):
        self._apply_button_focus_policy()
        super().showEvent(event)

    def apply_theme(self):
        self.setStyleSheet(get_common_stylesheet(self.bg_color, self.text_color, self.accent_color))
        ar, ag, ab = self.accent_color.red(), self.accent_color.green(), self.accent_color.blue()
        if hasattr(self, '_title_separator'):
            self._title_separator.setStyleSheet(f"background: rgba({ar}, {ag}, {ab}, 55);")
        if hasattr(self, 'close_btn'):
            tc = self.text_color.name()
            self.close_btn.setStyleSheet(
                f"QPushButton {{ border: none; background: transparent; font-size: 20px; color: {tc}; border-radius: 16px; font-weight: 300; }}"
                f" QPushButton:hover {{ color: #ffffff; background: #e0454a; border: none; }}"
                f" QPushButton:pressed {{ background: #c03030; color: #ffffff; }}"
            )
        self.update()
    def paintEvent(self, event):
        if self.isMinimized():
            return
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            outer_path = QPainterPath()
            outer_path.addRoundedRect(QRectF(self.rect()), 14, 14)

            painter.setClipPath(outer_path)
            painter.fillRect(self.rect(), self.bg_color)

            title_h = getattr(self, '_TITLE_BAR_HEIGHT', 50)
            header_color = QColor(self.bg_color)
            if header_color.lightnessF() > 0.5:
                header_color = header_color.darker(108)
            else:
                header_color = header_color.lighter(112)
            painter.fillRect(0, 0, self.width(), title_h, header_color)

            painter.setClipping(False)
            painter.setPen(QPen(self.accent_color, 1))
            painter.drawPath(outer_path)
        finally:
            painter.end()
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.y() < 58:
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_pos: self.move(event.globalPos() - self.drag_pos); event.accept()
    def mouseReleaseEvent(self, event): self.drag_pos = None

class ThemedMessageBox(ThemedDialog):
    # Copy ThemedMessageBox implementation...
    def __init__(self, title, message, buttons=None, parent=None, bg_color=None, text_color=None, accent_color=None, border_enabled=False, border_color=None, border_width=3):
        super().__init__(parent, title, bg_color, text_color, accent_color, border_enabled, border_color, border_width)
        
        # Use QTextBrowser for proper HTML and word wrapping support
        msg_browser = QTextBrowser()
        msg_browser.setHtml(message)
        msg_browser.setReadOnly(True)
        msg_browser.setFrameShape(QFrame.NoFrame)
        msg_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        msg_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Apply styling to match theme
        msg_browser.setStyleSheet(f"""
            QTextBrowser {{
                background-color: transparent;
                color: {self.text_color.name()};
                border: none;
                padding: 5px;
            }}
            QScrollBar:vertical {{
                background-color: {self.bg_color.name()};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background-color: {self.accent_color.name()};
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {self.accent_color.lighter(120).name()};
            }}
        """)
        
        self.content_layout.addWidget(msg_browser)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        if not buttons: buttons = [("OK", QDialog.Accepted)]
        for btn_text, role in buttons:
            btn = QPushButton(btn_text); btn.clicked.connect(lambda checked, r=role: self.finish(r)); btn_layout.addWidget(btn)
        self.content_layout.addLayout(btn_layout)
        
        # Auto-fit dialog size to content - delay slightly to allow layout to calculate
        QTimer.singleShot(0, self._auto_fit_size)
    
    def _auto_fit_size(self):
        """Auto-fit the dialog size based on the content."""
        # Let the layout recalculate first
        self.content_widget.adjustSize()
        self.adjustSize()
        
        # Constrain to reasonable bounds
        desktop_geo = QApplication.primaryScreen().geometry()
        max_width = int(desktop_geo.width() * 0.7)  # 70% of screen width for better text display
        max_height = int(desktop_geo.height() * 0.75)  # 75% of screen height
        
        current_width = self.width()
        current_height = self.height()
        
        new_width = min(current_width, max_width)
        new_width = max(new_width, 500)  # Increased minimum width for better text wrapping
        new_height = min(current_height, max_height)
        new_height = max(new_height, 250)  # Increased minimum height for better content display
        
        self.resize(new_width, new_height)
        # Center the dialog on its parent
        if self.parent():
            parent_geo = self.parent().geometry()
            self.move(
                parent_geo.center().x() - new_width // 2,
                parent_geo.center().y() - new_height // 2
            )
    
    def finish(self, result): self.done(result)

# ... [Include SaveConfirmationDialog, FramelessColorDialog, FramelessFileDialog here] ...

class SpotifySetupDialog(ThemedDialog):
    SKIP_CODE = 2  # Custom code for skip action
    
    def __init__(self, parent=None, bg_color=None, text_color=None, accent_color=None, border_enabled=False, border_color=None, border_width=3):
        super().__init__(parent, "Spotify API Setup (Optional)", bg_color, text_color, accent_color, border_enabled, border_color, border_width)
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(14)

        # Info card
        info_frame = QFrame()
        info_frame.setObjectName("InfoCard")
        info_frame_layout = QVBoxLayout(info_frame)
        info_frame_layout.setContentsMargins(14, 12, 14, 12)
        info_label = QLabel(
            "<b>Set Up Spotify (Optional):</b><br><br>"
            "To use Spotify playback, enter your API credentials below.<br>"
            "If you don't have credentials yet, you can skip this and use Windows Media Player "
            "or other media sources instead."
        )
        info_label.setWordWrap(True)
        info_frame_layout.addWidget(info_label)
        layout.addWidget(info_frame)
        
        id_label = QLabel("Client ID:"); secret_label = QLabel("Client Secret:")
        self.id_input = QLineEdit(); self.secret_input = QLineEdit()
        self.id_input.setEchoMode(QLineEdit.Normal); self.secret_input.setEchoMode(QLineEdit.Password)
        
        # Load existing credentials
        settings = QSettings("SpotifySync", "App")
        self.id_input.setText(settings.value("spotify_client_id", ""))
        self.secret_input.setText(settings.value("spotify_client_secret", ""))
        
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        form_layout.addRow(id_label, self.id_input)
        form_layout.addRow(secret_label, self.secret_input)
        layout.addLayout(form_layout)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        skip_btn = QPushButton("Skip & Use Media Player")
        skip_btn.clicked.connect(self.skip)
        skip_btn.setMinimumWidth(150)
        save_btn = QPushButton("Save Credentials")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(skip_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)
        self.content_layout.addLayout(layout)

    def accept(self):
        settings = QSettings("SpotifySync", "App")
        settings.setValue("spotify_client_id", self.id_input.text().strip())
        settings.setValue("spotify_client_secret", self.secret_input.text().strip())
        super().accept()
    
    def skip(self):
        """Skip Spotify setup and continue without it."""
        self.done(self.SKIP_CODE)


class AppleMusicSetupDialog(ThemedDialog):
    SKIP_CODE = 2  # Custom code for skip action
    
    def __init__(self, parent=None, bg_color=None, text_color=None, accent_color=None, border_enabled=False, border_color=None, border_width=3):
        super().__init__(parent, "Apple Music API Setup (Optional)", bg_color, text_color, accent_color, border_enabled, border_color, border_width)
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(14)

        # Info card
        info_frame = QFrame()
        info_frame.setObjectName("InfoCard")
        info_frame_layout = QVBoxLayout(info_frame)
        info_frame_layout.setContentsMargins(14, 12, 14, 12)
        info_label = QLabel(
            "<b>Set Up Apple Music (Optional):</b><br><br>"
            "To use Apple Music with enhanced features, you'll need MusicKit API credentials.<br>"
            "Apple Music playback detection will work via Windows Media Player without these credentials, "
            "but album art and metadata will be limited.<br><br>"
            "<b>To get credentials:</b><br>"
            "1. Go to <a href='https://developer.apple.com/account'>developer.apple.com/account</a><br>"
            "2. Create a MusicKit Key (under Certificates, IDs & Profiles)<br>"
            "3. Download the .p8 private key file<br>"
            "4. Find your Team ID and Key ID in the Apple Developer portal<br><br>"
            "If you don't have these yet, skip this step and use basic media player integration."
        )
        info_label.setWordWrap(True)
        info_label.setOpenExternalLinks(True)
        info_frame_layout.addWidget(info_label)
        layout.addWidget(info_frame)
        
        # Input fields
        team_id_label = QLabel("Team ID:")
        key_id_label = QLabel("Key ID:")
        private_key_label = QLabel("Private Key (.p8 contents):")
        
        self.team_id_input = QLineEdit()
        self.key_id_input = QLineEdit()
        self.private_key_input = QLineEdit()
        self.private_key_input.setEchoMode(QLineEdit.Password)
        
        # Load P8 file button
        load_p8_btn = QPushButton("Load from .p8 file...")
        load_p8_btn.clicked.connect(self._load_p8_file)
        
        # User token (optional)
        user_token_label = QLabel("User Token (Optional):")
        self.user_token_input = QLineEdit()
        self.user_token_input.setPlaceholderText("For personalized features like playlists")
        
        # Load existing credentials
        settings = QSettings("SpotifySync", "App")
        self.team_id_input.setText(settings.value("apple_music_team_id", ""))
        self.key_id_input.setText(settings.value("apple_music_key_id", ""))
        self.private_key_input.setText(settings.value("apple_music_private_key", ""))
        self.user_token_input.setText(settings.value("apple_music_user_token", ""))
        
        form_layout = QFormLayout()
        form_layout.addRow(team_id_label, self.team_id_input)
        form_layout.addRow(key_id_label, self.key_id_input)
        form_layout.addRow(private_key_label, self.private_key_input)
        form_layout.addRow("", load_p8_btn)
        form_layout.addRow(user_token_label, self.user_token_input)
        layout.addLayout(form_layout)
        
        # Button layout
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        skip_btn = QPushButton("Skip & Use Basic Integration")
        skip_btn.clicked.connect(self.skip)
        skip_btn.setMinimumWidth(180)
        save_btn = QPushButton("Save Credentials")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(skip_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)
        self.content_layout.addLayout(layout)
    
    def _load_p8_file(self):
        """Load private key from .p8 file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Apple Music Private Key",
            "",
            "P8 Files (*.p8);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    key_content = f.read().strip()
                    self.private_key_input.setText(key_content)
            except Exception as e:
                print(f"Error loading .p8 file: {e}")
    
    def accept(self):
        settings = QSettings("SpotifySync", "App")
        settings.setValue("apple_music_team_id", self.team_id_input.text().strip())
        settings.setValue("apple_music_key_id", self.key_id_input.text().strip())
        settings.setValue("apple_music_private_key", self.private_key_input.text().strip())
        settings.setValue("apple_music_user_token", self.user_token_input.text().strip())
        super().accept()
    
    def skip(self):
        """Skip Apple Music API setup and continue without it."""
        self.done(self.SKIP_CODE)


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
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), 12, 12)
            painter.fillPath(path, self.bg_color)
            painter.setPen(QPen(self.accent_color, 1))
            painter.drawPath(path)
        finally:
            painter.end()

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

    GRADIENT_DIRECTION_OPTIONS = [
        "0° East",
        "45° NE",
        "90° North",
        "135° NW",
        "180° West",
        "225° SW",
        "270° South",
        "315° SE",
    ]
    TRACK_TRANSITION_EASING_OPTIONS = [
        "Out Cubic",
        "In Out Cubic",
        "Out Quad",
        "In Out Quad",
        "Linear",
    ]

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
        self._is_closing_via_save = False
        self._handling_close_credentials = False

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
        self._auto_save_enabled = settings.value("auto_save_enabled", "false") == "true"
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.timeout.connect(self._flush_auto_save)
        self._auto_save_connections_ready = False
        self._auto_save_on_change = False
        self._auto_save_suspended = False
        self.theme_library_dialog = None
        self.theme_library_grid = None
        self.theme_library_content = None
        self.initial_default_progress_bar_enabled = settings.value("default_progress_bar_enabled", "false") == "true"
        self.initial_default_show_player_controls = settings.value("default_show_player_controls", "false") == "true"
        self.initial_default_controls_play_pause  = settings.value("default_controls_play_pause",  "true") == "true"
        self.initial_default_controls_shuffle     = settings.value("default_controls_shuffle",     "true") == "true"
        self.initial_default_controls_repeat      = settings.value("default_controls_repeat",      "true") == "true"
        self.initial_default_controls_add_playlist= settings.value("default_controls_add_playlist","true") == "true"
        self.initial_default_controls_liked       = settings.value("default_controls_liked",       "true") == "true"
        self.initial_default_text_border_size = int(settings.value("default_text_border_size", 3))
        self.initial_track_transition_duration_ms = int(settings.value("track_transition_duration_ms", 800))
        self.initial_track_transition_duration_ms = max(250, min(2200, self.initial_track_transition_duration_ms))
        self.initial_track_transition_easing = str(settings.value("track_transition_easing", "Out Cubic") or "Out Cubic")
        if self.initial_track_transition_easing not in self.TRACK_TRANSITION_EASING_OPTIONS:
            self.initial_track_transition_easing = "Out Cubic"
        
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
        album_art_border_enabled = cached_data.get("album_art_border_enabled", True)
        self.title_gradient_enabled = bool(cached_data.get("title_gradient_enabled", False))
        title_gradient_color_rgb = cached_data.get("title_gradient_color", [255, 255, 255])
        self.title_gradient_color = QColor(*title_gradient_color_rgb)
        self.title_gradient_direction = self._normalize_gradient_direction_label(
            cached_data.get("title_gradient_direction", "Left to Right")
        )
        
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
        self.custom_art_scope = "track"
        self.custom_art_b64 = track_cache.get("custom_art_b64")
        if not self.custom_art_b64:
            self.custom_art_b64 = (self.color_cache.get_album_data(self.album_id) or {}).get("custom_art_b64")
            if self.custom_art_b64:
                self.custom_art_scope = "album"
        self.initial_custom_art_scope = self.custom_art_scope
        self._custom_art_changed = False

        # Store initial credentials to check for changes on save
        self.initial_spotify_id = settings.value("spotify_client_id", "")
        self.initial_spotify_secret = settings.value("spotify_client_secret", "")
        self.initial_govee_key = settings.value("govee_api_key", "")
        self.initial_apple_music_team_id = settings.value("apple_music_team_id", "")
        self.initial_apple_music_key_id = settings.value("apple_music_key_id", "")
        self.initial_apple_music_private_key = settings.value("apple_music_private_key", "")
        self.initial_apple_music_user_token = settings.value("apple_music_user_token", "")
        self.initial_govee_devices = json.loads(settings.value("govee_devices", "[]"))

        if hasattr(main_window_state, 'get_shortcut_definitions'):
            self.shortcut_definitions = main_window_state.get_shortcut_definitions()
        else:
            self.shortcut_definitions = []

        if hasattr(main_window_state, 'get_shortcut_bindings'):
            parent_shortcuts = main_window_state.get_shortcut_bindings()
        else:
            parent_shortcuts = {}

        self.shortcut_bindings = self._normalize_shortcut_bindings(parent_shortcuts)
        self.initial_shortcut_bindings = dict(self.shortcut_bindings)
        self._shortcut_capture_action_id = None
        self._shortcut_capture_button = None
        self.shortcut_buttons = {}
        self.shortcut_status_label = None
        
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
        self.initial_album_art_border_enabled = album_art_border_enabled
        self.initial_title_gradient_enabled = self.title_gradient_enabled
        self.initial_title_gradient_color = QColor(self.title_gradient_color)
        self.initial_title_gradient_direction = self.title_gradient_direction
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

        # --- FIX: Bulletproof combobox text styling ---
        self.setStyleSheet("""
            QComboBox { 
                background-color: #333; 
                color: white; 
                border: 1px solid #555; 
                border-radius: 4px; 
                padding: 4px; 
            }
            QComboBox:disabled { 
                background-color: #222; 
                color: #777; 
                border-color: #333; 
            }
            QComboBox QAbstractItemView { 
                background-color: #222; 
                color: white; 
                selection-background-color: #555; 
                outline: none; 
                border: 1px solid #444; 
            }
            /* Specifically target the QListView used by Font Dropdowns */
            QListView { 
                color: white; 
                background-color: #222; 
            }
            QListView::item { 
                color: white; 
            }
            QListView::item:selected { 
                background-color: #555; 
            }
        """)
        
        self.update_stylesheet()

        # --- 2. DEFERRED UI BUILD SETUP ---
        self._is_ui_built = False
        self._pending_load_state = None
        self._build_generator = None

        # Root layout (no margins — title bar goes edge-to-edge)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Title Bar ---
        self._SETTINGS_TITLE_BAR_HEIGHT = 50
        self._settings_title_bar = QWidget()
        self._settings_title_bar.setFixedHeight(self._SETTINGS_TITLE_BAR_HEIGHT)
        self._settings_title_bar.setStyleSheet("background: transparent;")
        tb_layout = QHBoxLayout(self._settings_title_bar)
        tb_layout.setContentsMargins(16, 0, 10, 0)
        tb_layout.setSpacing(8)
        self._settings_title_label = QLabel("Settings")
        self._settings_title_label.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
        self._settings_close_btn = QPushButton("×")
        self._settings_close_btn.setFixedSize(32, 32)
        self._settings_close_btn.setCursor(Qt.PointingHandCursor)
        self._settings_close_btn.clicked.connect(self.reject)
        self._settings_close_btn.hide()
        tb_layout.addWidget(self._settings_title_label)
        tb_layout.addStretch()
        tb_layout.addWidget(self._settings_close_btn)
        layout.addWidget(self._settings_title_bar)

        # Separator
        self._settings_title_sep = QWidget()
        self._settings_title_sep.setFixedHeight(1)
        layout.addWidget(self._settings_title_sep)

        # Content area
        content_area = QWidget()
        content_area_layout = QVBoxLayout(content_area)
        content_area_layout.setContentsMargins(20, 10, 20, 0)
        content_area_layout.setSpacing(0)
        self.main_layout = QHBoxLayout()
        self.main_layout.setSpacing(20)
        content_area_layout.addLayout(self.main_layout)
        layout.addWidget(content_area)

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

    def _sync_primary_tone_from_blobs(self):
        """Background color is controlled separately from blob colors."""
        return

    def _process_build_step(self):
        if not self._build_generator: return
        try:
            next(self._build_generator)
            # Process the next UI build step with a small delay to keep the app responsive.
            QTimer.singleShot(50, self._process_build_step)
        except StopIteration:
            self._build_generator = None
            self._install_auto_save_connections()
            self._configure_slider_interaction()
            self._refresh_save_buttons_for_current_tab()

    def _configure_slider_interaction(self):
        """Keep sliders responsive and prevent accidental wheel changes while scrolling."""
        for slider in self.findChildren(QSlider):
            slider.setTracking(True)
            slider.setFocusPolicy(Qt.StrongFocus)
            slider.installEventFilter(self)

    def _on_tab_changed(self, index):
        self._refresh_save_buttons_for_current_tab()

    def _normalize_gradient_direction_label(self, direction):
        raw = str(direction or "").strip()
        if not raw:
            return self.GRADIENT_DIRECTION_OPTIONS[0]

        lookup = {
            "left to right": self.GRADIENT_DIRECTION_OPTIONS[0],
            "bottom-left to top-right": self.GRADIENT_DIRECTION_OPTIONS[1],
            "top to bottom": self.GRADIENT_DIRECTION_OPTIONS[6],
            "bottom to top": self.GRADIENT_DIRECTION_OPTIONS[2],
            "top-right to bottom-left": self.GRADIENT_DIRECTION_OPTIONS[5],
            "bottom-right to top-left": self.GRADIENT_DIRECTION_OPTIONS[3],
            "right to left": self.GRADIENT_DIRECTION_OPTIONS[4],
            "top-left to bottom-right": self.GRADIENT_DIRECTION_OPTIONS[7],
        }

        lowered = raw.lower()
        if lowered in lookup:
            return lookup[lowered]

        if "°" in raw:
            try:
                angle = int(float(raw.split("°", 1)[0])) % 360
                steps = angle // 45
                return self.GRADIENT_DIRECTION_OPTIONS[steps]
            except (ValueError, TypeError, IndexError):
                return self.GRADIENT_DIRECTION_OPTIONS[0]

        return self.GRADIENT_DIRECTION_OPTIONS[0]

    def _current_tab_label(self):
        if not hasattr(self, "tab_widget") or self.tab_widget.count() == 0:
            return ""
        return self.tab_widget.tabText(self.tab_widget.currentIndex())

    def _tab_allows_manual_save(self, tab_label=None):
        tab_label = tab_label or self._current_tab_label()
        if tab_label == "Track Theme":
            return self.media_source == 'spotify'
        return tab_label in {"Notifications", "App Defaults", "Connections", "Keyboard Shortcuts"}

    def _tab_allows_theme_snapshot(self, tab_label=None):
        tab_label = tab_label or self._current_tab_label()
        return tab_label == "Track Theme" and self.media_source == 'spotify'

    def _refresh_save_buttons_for_current_tab(self):
        if not hasattr(self, 'quick_save_btn'):
            return

        show_manual_save = (not self._auto_save_enabled) and self._tab_allows_manual_save()
        show_theme_snapshot = (not self._auto_save_enabled) and self._tab_allows_theme_snapshot()
        show_done = self._auto_save_enabled

        self.quick_save_btn.setVisible(show_manual_save)
        self.save_button.setVisible(show_manual_save)
        self.save_full_theme_btn.setVisible(show_theme_snapshot)
        if hasattr(self, 'done_button'):
            self.done_button.setVisible(show_done)
        if hasattr(self, 'action_layout'):
            self.action_layout.invalidate()

    def _install_auto_save_connections(self):
        if self._auto_save_connections_ready:
            return

        for checkbox in self.findChildren(QCheckBox):
            checkbox.toggled.connect(self._schedule_auto_save)

        for radio in self.findChildren(QRadioButton):
            radio.toggled.connect(self._schedule_auto_save)

        for combo in self.findChildren(QComboBox):
            combo.currentTextChanged.connect(self._schedule_auto_save)
            combo.currentIndexChanged.connect(self._schedule_auto_save)

        for slider in self.findChildren(QSlider):
            slider.valueChanged.connect(self._schedule_auto_save)

        for line_edit in self.findChildren(QLineEdit):
            if line_edit is getattr(self, 'font_search_input', None):
                continue
            line_edit.textChanged.connect(self._schedule_auto_save)

        if hasattr(self, 'govee_device_table'):
            self.govee_device_table.itemChanged.connect(self._schedule_auto_save)

        self._auto_save_connections_ready = True

    def _schedule_auto_save(self, *args):
        if not self._auto_save_enabled or not self._auto_save_on_change or not self._is_ui_built or self._loading_state or self._auto_save_suspended:
            return
        self._auto_save_timer.start(225)

    def _collect_pending_changes(self):
        global_changes = self._get_global_changes()
        theme_changes = self._collect_theme_changes() if self.media_source == 'spotify' else []
        return global_changes, theme_changes

    def _persist_selected_changes(self, keys_to_save, global_changes, theme_changes, quick=False, close_after=True, allow_restart_prompt=True):
        settings = QSettings("SpotifySync", "App")

        for item in global_changes:
            if item['key'] not in keys_to_save:
                continue
            val = item['value']
            if item['key'] == "keyboard_shortcuts":
                settings.setValue(item['key'], json.dumps(self._normalize_shortcut_bindings(val)))
            elif isinstance(val, bool):
                settings.setValue(item['key'], "true" if val else "false")
            else:
                settings.setValue(item['key'], val)

        if "keyboard_shortcuts" in keys_to_save and self.parent() and hasattr(self.parent(), 'apply_shortcut_bindings'):
            self.parent().apply_shortcut_bindings(self.shortcut_bindings, persist=False)

        needs_art_reload = False
        did_persist_custom_art = False
        if self.media_source == 'spotify':
            album_config = self.cached_data.copy()
            theme_keys_processed = False
            needs_art_reload = self._custom_art_changed or (self._active_custom_art_scope() != self.initial_custom_art_scope)
            should_persist_custom_art = needs_art_reload and (quick or "custom_art_scope" in keys_to_save)

            for item in theme_changes:
                if item['key'] not in keys_to_save:
                    continue
                if item['key'] == "custom_art_scope":
                    continue
                theme_keys_processed = True
                if item['value'] == "__REMOVE__":
                    album_config.pop(item['key'], None)
                else:
                    album_config[item['key']] = item['value']

            if theme_keys_processed:
                if hasattr(self, 'current_album_name') and self.current_album_name:
                    album_config['meta_album'] = self.current_album_name
                if hasattr(self, 'current_artist_name') and self.current_artist_name:
                    album_config['meta_artist'] = self.current_artist_name

                self.color_cache.set_album_data(self.album_id, album_config)

                slider_value = self.blob_amount_slider.value()
                if self.parent():
                    self.parent().blob_density = 400000 / slider_value if slider_value > 0 else 200000

            if should_persist_custom_art:
                self._persist_custom_art()
                self.initial_custom_art_scope = self._active_custom_art_scope()
                self._custom_art_changed = False
                did_persist_custom_art = True

            if theme_keys_processed or did_persist_custom_art:
                self._refresh_saved_theme_baseline()

        if keys_to_save or quick:
            emit_config = self.color_cache.get_album_data(self.album_id) or {}
            if self.media_source == 'spotify' and did_persist_custom_art:
                emit_config = dict(emit_config)
                emit_config["_reload_art"] = True
            self.config_saved.emit(self.album_id, emit_config)
            self.populate_theme_browser()

        if allow_restart_prompt:
            self._handle_credential_changes(close_after=close_after)
        elif close_after:
            self.accept()

    def _refresh_saved_theme_baseline(self):
        track_cache = self.color_cache.get_album_data(self.track_id) or {}
        cached_data = track_cache or self.color_cache.get_album_data(self.album_id) or {}
        if isinstance(cached_data, list):
            ui_palette = [cached_data] if not isinstance(cached_data[0], list) else cached_data
            cached_data = {"ui_palette": ui_palette}

        self.cached_data = cached_data
        self.initial_ui_bg_color = QColor(self.ui_bg_color)
        self.initial_ui_accent_color = QColor(self.ui_accent_color)
        self.initial_ui_text_color = QColor(self.ui_text_color)
        self.initial_is_text_color_auto = self.is_text_color_auto
        self.initial_blob_colors = [QColor(color) for color in self.blob_colors]
        self.initial_shadow_enabled = self.shadow_checkbox.isChecked()
        self.initial_title_case = self._get_selected_case(self.title_case_radios)
        self.initial_artist_case = self._get_selected_case(self.artist_case_radios)
        self.initial_text_border_enabled = self.text_border_checkbox.isChecked()
        self.initial_is_text_border_auto = self.is_text_border_auto
        self.initial_text_border_color = QColor(self.text_border_color)
        self.initial_is_border_size_overridden = self.override_border_size_checkbox.isChecked()
        self.initial_text_border_size = self.text_border_size_slider.value()
        self.initial_album_art_border_enabled = self.album_art_border_checkbox.isChecked()
        self.initial_title_gradient_enabled = self.title_gradient_checkbox.isChecked()
        self.initial_title_gradient_color = QColor(self.title_gradient_color)
        self.initial_title_gradient_direction = self.title_gradient_dir_combo.currentText()
        self.initial_is_font_size_overridden = self.override_size_checkbox.isChecked()
        self.initial_font_size_scale = self.font_size_slider.value()
        self.initial_is_progress_bar_overridden = self.override_progress_bar_checkbox.isChecked()
        self.initial_progress_bar_enabled = self.progress_bar_checkbox.isChecked()
        self.initial_font_family = self.font_family_combo.currentText()
        self.initial_font_style = self.font_style_combo.currentText()
        self.initial_lights_palette = [QColor(picker['color']) for picker in self.govee_color_pickers]
        self.effective_initial_lights_palette = [QColor(picker['color']) for picker in self.govee_color_pickers]
        self.initial_is_brightness_overridden = self.override_brightness_checkbox.isChecked()
        self.initial_track_brightness = self.govee_brightness_slider.value()
        self.initial_custom_art_scope = self._active_custom_art_scope()
        self._custom_art_changed = False

    def _flush_auto_save(self):
        if not self._auto_save_enabled or self._loading_state or self._auto_save_suspended:
            return

        global_changes, theme_changes = self._collect_pending_changes()
        keys_to_save = [item['key'] for item in (global_changes + theme_changes) if item['changed']]
        if not keys_to_save:
            return

        self._persist_selected_changes(keys_to_save, global_changes, theme_changes, quick=True, close_after=False, allow_restart_prompt=False)

    def _handle_credential_changes(self, close_after=True):
        settings = QSettings("SpotifySync", "App")
        new_spotify_id = self.spotify_id_input.text().strip()
        new_spotify_secret = self.spotify_secret_input.text().strip()
        new_govee_key = self.govee_key_input.text().strip()
        new_apple_music_team_id = self.apple_music_team_id_input.text().strip()
        new_apple_music_key_id = self.apple_music_key_id_input.text().strip()
        new_apple_music_private_key = self.apple_music_private_key_input.text().strip()
        new_apple_music_user_token = self.apple_music_user_token_input.text().strip()

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

        credentials_changed = (
            new_spotify_id != self.initial_spotify_id or
            new_spotify_secret != self.initial_spotify_secret or
            new_govee_key != self.initial_govee_key or
            new_apple_music_team_id != self.initial_apple_music_team_id or
            new_apple_music_key_id != self.initial_apple_music_key_id or
            new_apple_music_private_key != self.initial_apple_music_private_key or
            new_apple_music_user_token != self.initial_apple_music_user_token or
            new_govee_devices_json != initial_govee_devices_json
        )

        if credentials_changed:
            msg = ThemedMessageBox(
                "Restart Required",
                "Changing credentials requires an application restart. Save all changes and restart now?",
                [("Yes", QDialog.Accepted), ("No", QDialog.Rejected)],
                self,
                self.ui_bg_color,
                self.ui_text_color,
                self.ui_accent_color,
                self.text_border_checkbox.isChecked(),
                self.text_border_color,
                self.text_border_size_slider.value(),
            )

            if msg.exec_() == QDialog.Accepted:
                settings.setValue("spotify_client_id", new_spotify_id)
                settings.setValue("spotify_client_secret", new_spotify_secret)
                settings.setValue("govee_api_key", new_govee_key)
                settings.setValue("apple_music_team_id", new_apple_music_team_id)
                settings.setValue("apple_music_key_id", new_apple_music_key_id)
                settings.setValue("apple_music_private_key", new_apple_music_private_key)
                settings.setValue("apple_music_user_token", new_apple_music_user_token)
                settings.setValue("govee_devices", json.dumps(new_govee_devices))

                if os.path.exists(".cache"):
                    os.remove(".cache")
                self.parent().restart_app()
                return

        if close_after:
            self.accept()

    def _on_auto_save_toggled(self, checked):
        self._auto_save_enabled = checked
        settings = QSettings("SpotifySync", "App")
        settings.setValue("auto_save_enabled", "true" if checked else "false")
        self._refresh_save_buttons_for_current_tab()

    def _has_saved_theme_for_current_track(self):
        theme_keys = {
            "player_bg_color",
            "ui_palette",
            "text_color",
            "blob_palette",
            "shadow_enabled",
            "album_art_border_enabled",
            "title_gradient_enabled",
            "title_gradient_color",
            "title_gradient_direction",
            "font_family",
            "font_style",
            "font_size_scale",
            "text_border_enabled",
            "text_border_color",
            "text_border_size",
            "title_case",
            "artist_case",
            "progress_bar_enabled",
            "lights_config",
            "govee_brightness",
        }
        album_data = self.color_cache.get_album_data(self.album_id) or {}
        track_data = self.color_cache.get_album_data(self.track_id) or {}
        if not isinstance(album_data, dict):
            album_data = {}
        if not isinstance(track_data, dict):
            track_data = {}
        return any(key in album_data for key in theme_keys) or any(key in track_data for key in theme_keys)

    def _build_full_theme_snapshot(self):
        album_config = {}
        primary_tone = list(self.ui_bg_color.getRgb()[:3])
        album_config["player_bg_color"] = list(self.ui_bg_color.getRgb()[:3])
        album_config["ui_palette"] = [
            primary_tone,
            list(self.ui_accent_color.getRgb()[:3]),
        ]
        album_config["text_color"] = list(self.ui_text_color.getRgb()[:3])
        album_config["blob_palette"] = [list(c.getRgb()[:3]) for c in self.blob_colors]

        album_config["shadow_enabled"] = self.shadow_checkbox.isChecked()
        album_config["album_art_border_enabled"] = self.album_art_border_checkbox.isChecked()
        album_config["title_gradient_enabled"] = self.title_gradient_checkbox.isChecked()
        album_config["title_gradient_color"] = list(self.title_gradient_color.getRgb()[:3])
        album_config["title_gradient_direction"] = self.title_gradient_dir_combo.currentText()
        album_config["font_family"] = self.font_family_combo.currentText()
        album_config["font_style"] = self.font_style_combo.currentText()
        album_config["font_size_scale"] = self.font_size_slider.value()

        album_config["text_border_enabled"] = self.text_border_checkbox.isChecked()
        album_config["text_border_color"] = list(self.text_border_color.getRgb()[:3])
        album_config["text_border_size"] = self.text_border_size_slider.value()

        album_config["title_case"] = self._get_selected_case(self.title_case_radios)
        album_config["artist_case"] = self._get_selected_case(self.artist_case_radios)
        album_config["progress_bar_enabled"] = self.progress_bar_checkbox.isChecked()

        current_lights_palette = [list(p["color"].getRgb()[:3]) for p in self.govee_color_pickers]
        album_config["lights_config"] = {
            "mode": "custom",
            "palette": current_lights_palette,
        }
        album_config["govee_brightness"] = self.govee_brightness_slider.value() / 100.0

        if hasattr(self, 'current_album_name') and self.current_album_name:
            album_config['meta_album'] = self.current_album_name
        if hasattr(self, 'current_artist_name') and self.current_artist_name:
            album_config['meta_artist'] = self.current_artist_name

        return album_config

    def done_auto_save(self):
        """Save all settings and close (global settings + full current track theme snapshot)."""
        self._is_closing_via_save = True

        global_changes, theme_changes = self._collect_pending_changes()
        keys_to_save = [item['key'] for item in (global_changes + theme_changes)]
        self._persist_selected_changes(
            keys_to_save,
            global_changes,
            theme_changes,
            quick=False,
            close_after=False,
            allow_restart_prompt=False,
        )

        if self.media_source == 'spotify':
            album_config = self._build_full_theme_snapshot()
            self.color_cache.set_album_data(self.album_id, album_config)

            needs_art_reload = self._custom_art_changed or (self._active_custom_art_scope() != self.initial_custom_art_scope)
            self._persist_custom_art()
            if needs_art_reload:
                self.initial_custom_art_scope = self._active_custom_art_scope()
                self._custom_art_changed = False

            slider_value = self.blob_amount_slider.value()
            if self.parent():
                self.parent().blob_density = 400000 / slider_value if slider_value > 0 else 200000

            emit_config = dict(album_config)
            if needs_art_reload:
                emit_config["_reload_art"] = True
            self.config_saved.emit(self.album_id, emit_config)
            self.populate_theme_browser()
            self._refresh_saved_theme_baseline()

        self._handle_credential_changes(close_after=True)

    def _ensure_theme_library_dialog(self):
        if self.theme_library_dialog is not None:
            self.theme_library_dialog.bg_color = QColor(self.ui_bg_color)
            self.theme_library_dialog.text_color = QColor(self.ui_text_color)
            self.theme_library_dialog.accent_color = QColor(self.ui_accent_color)
            self.theme_library_dialog.border_enabled = self.text_border_checkbox.isChecked()
            self.theme_library_dialog.border_color = QColor(self.text_border_color)
            self.theme_library_dialog.border_width = self.text_border_size_slider.value()
            self.theme_library_dialog.title_label.setBorder(
                self.theme_library_dialog.border_enabled,
                self.theme_library_dialog.border_color,
                self.theme_library_dialog.border_width,
            )
            self.theme_library_dialog.title_label.setCustomTextColor(self.theme_library_dialog.text_color)
            self.theme_library_dialog.apply_theme()
            return self.theme_library_dialog

        dialog = ThemedDialog(
            self,
            "Saved Themes",
            QColor(self.ui_bg_color),
            QColor(self.ui_text_color),
            QColor(self.ui_accent_color),
            self.text_border_checkbox.isChecked(),
            QColor(self.text_border_color),
            self.text_border_size_slider.value(),
        )
        dialog.setMinimumSize(760, 520)
        dialog.resize(860, 620)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        control_layout = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.populate_theme_browser)
        import_batch_btn = QPushButton("Import Albums")
        import_batch_btn.setToolTip("Select multiple theme files to add or update.")
        import_batch_btn.clicked.connect(self.import_batch_themes)
        control_layout.addWidget(refresh_btn)
        control_layout.addWidget(import_batch_btn)
        control_layout.addStretch()
        layout.addLayout(control_layout)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.theme_library_content = QWidget()
        self.theme_library_grid = QGridLayout(self.theme_library_content)
        self.theme_library_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.theme_library_grid.setSpacing(15)
        scroll_area.setWidget(self.theme_library_content)
        layout.addWidget(scroll_area)

        dialog.content_layout.addWidget(container)
        self.theme_library_dialog = dialog
        return dialog

    def open_theme_library_dialog(self):
        dialog = self._ensure_theme_library_dialog()
        self.populate_theme_browser()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _install_filter_recursive(self, widget):
        """Installs the border event filter on the widget and all its children."""
        if isinstance(widget, (QLabel, QAbstractButton, QGroupBox)):
            widget.installEventFilter(self.ui_event_filter)

        if isinstance(widget, QPushButton):
            # Keep button focus on click only so Tab can be captured for shortcut binding.
            widget.setFocusPolicy(Qt.ClickFocus)
        
        for child in widget.children():
            if isinstance(child, QWidget):
                self._install_filter_recursive(child)

    def eventFilter(self, obj, event):
        if isinstance(obj, QSlider) and event.type() == QEvent.Wheel and not obj.hasFocus():
            event.ignore()
            return True
        if isinstance(obj, QSlider) and event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            option = QStyleOptionSlider()
            obj.initStyleOption(option)
            handle = obj.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderHandle, obj)
            if not handle.contains(event.pos()):
                if obj.orientation() == Qt.Horizontal:
                    value = QStyle.sliderValueFromPosition(obj.minimum(), obj.maximum(), event.x(), obj.width())
                else:
                    value = QStyle.sliderValueFromPosition(obj.minimum(), obj.maximum(), obj.height() - event.y(), obj.height())
                obj.setValue(value)
                event.accept()
                return True
        return super().eventFilter(obj, event)

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
        if is_html_or_wrapped:
            lbl.setTextFormat(Qt.RichText)
        else:
            self.ui_labels.append(lbl)
            lbl.setCustomTextColor(self.ui_text_color)
        return lbl

    def _ui_build_steps(self):
        settings = QSettings("SpotifySync", "App")
        lights_config = self.cached_data.get("lights_config", {})
        
        from PyQt5.QtWidgets import QStyledItemDelegate

        # --- Right Column (Tabbed Settings) ---
        settings_container_layout = QVBoxLayout(self.settings_container)
        settings_container_layout.setContentsMargins(0,0,0,0)

        self.tab_widget = QTabWidget()
        
        # --- NEW: Use Custom Tab Bar ---
        from ui.widgets import BorderedTabBar
        self.custom_tab_bar = BorderedTabBar()
        self.tab_widget.setTabBar(self.custom_tab_bar)
        
        # --- NEW: Connect the tab change signal here ---
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        
        # Create a placeholder for the disabled info label...
        self.disabled_info_label = QLabel("Theme and color editing is only available for tracks played via Spotify.")
        self.disabled_info_label.setWordWrap(True)
        self.disabled_info_label.setStyleSheet("font-style: italic; color: #999; padding-bottom: 10px;")
        self.disabled_info_label.hide()
        settings_container_layout.addWidget(self.tab_widget)

        yield # Yield after basic container setup

        # --- Tab 1: Track Theme (visuals for this track/album) ---
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
        self.tab_widget.addTab(theme_tab, "Track Theme")

        self.settings_col_1 = QVBoxLayout(); self.settings_col_1.setAlignment(Qt.AlignTop)
        self.settings_col_2 = QVBoxLayout(); self.settings_col_2.setAlignment(Qt.AlignTop)
        self.settings_grid_layout.addLayout(self.settings_col_1, 2) # Give left column a stretch factor of 2
        self.settings_grid_layout.addLayout(self.settings_col_2, 3) # Give right column more space with a stretch factor of 3
        self.settings_col_1.insertWidget(0, self.disabled_info_label)

        theme_actions_layout = QHBoxLayout()
        regenerate_btn = QPushButton("Rebuild Auto Theme from Artwork")
        regenerate_btn.setToolTip("Re-detect colors for auto-set fields based on current art.")
        regenerate_btn.clicked.connect(self.regenerate_theme)
        
        reset_theme_btn = QPushButton("Reset Track Theme")
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
        self.notification_enabled_checkbox = QCheckBox("Enable Now Playing Notifications")
        self.notification_enabled_checkbox.setChecked(settings.value("notification_enabled", "false") == "true")
        notif_layout.addWidget(self.notification_enabled_checkbox)

        # Behavior Group
        notification_group = QGroupBox("Placement & Behavior")
        notification_layout = QFormLayout(notification_group)
        notification_layout.setSpacing(12)
        notif_layout.addWidget(notification_group)

        self.notification_monitor_combo = NoScrollComboBox()
        self.notification_monitor_combo.setItemDelegate(QStyledItemDelegate())
        screens = QApplication.screens()
        monitor_names = ["Primary Monitor"]
        for screen in screens:
            name = screen.model() if screen.model() else screen.name()
            size = screen.size()
            monitor_names.append(f"{name} ({size.width()}x{size.height()})")
        self.notification_monitor_combo.addItems(monitor_names)
        self.notification_monitor_combo.setCurrentIndex(int(settings.value("notification_monitor_index", 0)))

        self.notification_corner_combo = NoScrollComboBox()
        self.notification_corner_combo.setItemDelegate(QStyledItemDelegate())
        self.notification_corner_combo.addItems(["Top-Left", "Top-Center", "Top-Right", "Bottom-Left", "Bottom-Center", "Bottom-Right"])
        self.notification_corner_combo.setCurrentText(settings.value("notification_corner", "Top-Right"))

        self.notif_smart_hide_checkbox = QCheckBox("Smart Hide When Player Is Visible")
        self.notif_smart_hide_checkbox.setToolTip("Hides notification if player is visible on the same screen.")
        self.notif_smart_hide_checkbox.setChecked(settings.value("notification_smart_hide", "false") == "true")
        
        self.notif_ignore_taskbar_checkbox = QCheckBox("Ignore Taskbar Area (Use Screen Edge)")
        self.notif_ignore_taskbar_checkbox.setChecked(settings.value("notification_ignore_taskbar", "true") == "true")

        notification_layout.addRow(self._create_label("Display:"), self.notification_monitor_combo)
        notification_layout.addRow(self._create_label("Position:"), self.notification_corner_combo)
        notification_layout.addRow(self.notif_smart_hide_checkbox)
        notification_layout.addRow(self.notif_ignore_taskbar_checkbox)

        # Appearance Group
        notif_style_group = QGroupBox("Appearance & Timing")
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

        self.notif_border_checkbox = QCheckBox("Show Notification Border")
        self.notif_border_checkbox.setChecked(settings.value("notification_border_enabled", "false") == "true")

        self.notification_anim_combo = NoScrollComboBox()
        self.notification_anim_combo.setItemDelegate(QStyledItemDelegate())
        self.notification_anim_combo.addItems(["Fade", "Slide", "Fade Slide", "Bounce"])
        self.notification_anim_combo.setCurrentText(settings.value("notification_anim", "Fade"))

        self.notification_dir_combo = NoScrollComboBox()
        self.notification_dir_combo.setItemDelegate(QStyledItemDelegate())
        self.notification_dir_combo.addItems(["From Top", "From Bottom", "From Left", "From Right"])
        self.notification_dir_combo.setCurrentText(settings.value("notification_dir", "From Top"))
        
        self.notification_anim_combo.currentTextChanged.connect(self._update_notification_options)

        self.notif_permanent_checkbox = QCheckBox("Keep Visible for Full Song")
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
        notif_style_layout.addRow(self._create_label("Background Opacity:"), opacity_layout)
        notif_style_layout.addRow(self.notif_border_checkbox)
        notif_style_layout.addRow(self._create_label("Animation Style:"), self.notification_anim_combo)
        notif_style_layout.addRow(self._create_label("Slide Direction:"), self.notification_dir_combo)
        notif_style_layout.addRow(self.notif_permanent_checkbox)
        notif_style_layout.addRow(self._create_label("Visible For:"), duration_layout)
        notif_style_layout.addRow(self._create_label("Transition Speed:"), anim_speed_layout)
        
        notif_layout.addStretch()

        self._update_notification_options(self.notification_anim_combo.currentText())

        yield # Yield after Tab 2 setup

        # --- Tab 3: App Defaults ---
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
        self.tab_widget.addTab(global_tab, "App Defaults")

        # Default Typography Group
        default_text_group = QGroupBox("Default Text Style")
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
        self.default_font_style_combo.setItemDelegate(
            FontStyleDelegate(lambda: self.default_font_family_combo.currentText(), self.default_font_style_combo)
        )
        
        self.default_font_size_slider = QSlider(Qt.Horizontal); self.default_font_size_slider.setRange(50, 200); self.default_font_size_slider.setValue(self.initial_default_font_size_scale)
        self.default_font_size_label = self._create_dynamic_label(f"{self.initial_default_font_size_scale}%")
        
        self.default_font_size_slider.valueChanged.connect(self._on_default_font_size_changed)
        
        default_size_layout = QHBoxLayout(); default_size_layout.addWidget(self.default_font_size_slider); default_size_layout.addWidget(self.default_font_size_label)

        default_text_layout.addRow(self._create_label("Font Family:"), self.default_font_family_combo); default_text_layout.addRow(self._create_label("Font Style:"), self.default_font_style_combo)
        default_text_layout.addRow(self._create_label("Font Size:"), default_size_layout)
        
        self.default_text_border_checkbox = QCheckBox("Show Text Outline by Default")
        self.default_text_border_checkbox.setToolTip("If checked, borders will be shown on all tracks unless manually disabled.\nIf unchecked, borders will only appear when text contrast is low (Auto).")
        self.default_text_border_checkbox.setChecked(self.initial_default_text_border_enabled)
        default_text_layout.addRow(self.default_text_border_checkbox)

        self.default_text_border_size_slider = QSlider(Qt.Horizontal); self.default_text_border_size_slider.setRange(1, 10); self.default_text_border_size_slider.setValue(self.initial_default_text_border_size)
        self.default_text_border_size_label = self._create_dynamic_label(f"{self.initial_default_text_border_size}px")
        self.default_text_border_size_slider.valueChanged.connect(lambda v: self.default_text_border_size_label.setText(f"{v}px"))
        self.default_text_border_size_slider.sliderReleased.connect(self.update_previews)
        default_border_size_layout = QHBoxLayout(); default_border_size_layout.addWidget(self.default_text_border_size_slider); default_border_size_layout.addWidget(self.default_text_border_size_label)
        
        default_text_layout.addRow(self._create_label("Outline Size:"), default_border_size_layout)

        # Visual Effects Group
        visual_effects_group = QGroupBox("Visual Effects")
        visual_effects_layout = QFormLayout(visual_effects_group)
        visual_effects_layout.setSpacing(12)
        global_layout.addWidget(visual_effects_group)

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
        visual_effects_layout.addRow(self._create_label("Background Motion Amount:"), amount_widget)

        lava_style_value = self._create_dynamic_label("Color Pop (fixed)")
        lava_style_value.setToolTip("Lava-lamp style is fixed to Color Pop.")
        visual_effects_layout.addRow(self._create_label("Lava Lamp Style:"), lava_style_value)

        self.default_progress_bar_checkbox = QCheckBox("Show Progress Bar by Default")
        self.default_progress_bar_checkbox.setChecked(self.initial_default_progress_bar_enabled)
        visual_effects_layout.addRow(self.default_progress_bar_checkbox)

        # Player Controls Bar
        controls_group = QGroupBox("Player Controls Bar")
        controls_layout = QFormLayout(controls_group)
        controls_layout.setSpacing(10)
        global_layout.addWidget(controls_group)

        self.default_show_player_controls_checkbox = QCheckBox("Show Player Controls Bar")
        self.default_show_player_controls_checkbox.setChecked(self.initial_default_show_player_controls)
        controls_layout.addRow(self.default_show_player_controls_checkbox)

        self.default_controls_play_pause_checkbox = QCheckBox("Play / Pause")
        self.default_controls_play_pause_checkbox.setChecked(self.initial_default_controls_play_pause)
        self.default_controls_shuffle_checkbox = QCheckBox("Shuffle")
        self.default_controls_shuffle_checkbox.setChecked(self.initial_default_controls_shuffle)
        self.default_controls_repeat_checkbox = QCheckBox("Repeat")
        self.default_controls_repeat_checkbox.setChecked(self.initial_default_controls_repeat)
        self.default_controls_add_playlist_checkbox = QCheckBox("Add to Playlist")
        self.default_controls_add_playlist_checkbox.setChecked(self.initial_default_controls_add_playlist)
        self.default_controls_liked_checkbox = QCheckBox("Liked / Heart")
        self.default_controls_liked_checkbox.setChecked(self.initial_default_controls_liked)

        controls_layout.addRow(self._create_label("Visible Buttons:"), self.default_controls_play_pause_checkbox)
        controls_layout.addRow("", self.default_controls_shuffle_checkbox)
        controls_layout.addRow("", self.default_controls_repeat_checkbox)
        controls_layout.addRow("", self.default_controls_add_playlist_checkbox)
        controls_layout.addRow("", self.default_controls_liked_checkbox)

        def _update_controls_checkboxes(enabled):
            for cb in [self.default_controls_play_pause_checkbox, self.default_controls_shuffle_checkbox,
                       self.default_controls_repeat_checkbox, self.default_controls_add_playlist_checkbox,
                       self.default_controls_liked_checkbox]:
                cb.setEnabled(enabled)
        _update_controls_checkboxes(self.initial_default_show_player_controls)
        self.default_show_player_controls_checkbox.toggled.connect(_update_controls_checkboxes)

        # Layout & Window Behavior
        behavior_group = QGroupBox("Window & Layout")
        behavior_layout = QFormLayout(behavior_group)
        behavior_layout.setSpacing(12)
        global_layout.addWidget(behavior_group)

        self.minimize_mode_checkbox = QCheckBox("Minimize Button Enters Notification-Only Mode")
        self.minimize_mode_checkbox.setChecked(settings.value("minimize_to_notification_only", "true") == "true")
        self.minimize_mode_checkbox.setToolTip(
            "ON: the custom minimize button hides the player and enters notification-only mode.\n"
            "OFF: the custom minimize button does a normal window minimize."
        )
        behavior_layout.addRow(self.minimize_mode_checkbox)

        self.player_art_side_combo = NoScrollComboBox()
        self.player_art_side_combo.setItemDelegate(QStyledItemDelegate())
        self.player_art_side_combo.addItems(["Left", "Right"])
        saved_art_side = str(settings.value("player_art_side", "left")).strip().lower()
        self.player_art_side_combo.setCurrentText("Right" if saved_art_side == "right" else "Left")
        behavior_layout.addRow(self._create_label("Album Art Side:"), self.player_art_side_combo)

        # Smart Lights Defaults
        lights_defaults_group = QGroupBox("Smart Lights Defaults")
        lights_defaults_layout = QFormLayout(lights_defaults_group)
        lights_defaults_layout.setSpacing(12)
        global_layout.addWidget(lights_defaults_group)
        
        self.default_brightness_slider = QSlider(Qt.Horizontal)
        self.default_brightness_slider.setRange(0, 100)
        self.default_brightness_slider.setValue(self.initial_default_govee_brightness)
        self.default_brightness_label = self._create_dynamic_label(f"{self.initial_default_govee_brightness}%")
        self.default_brightness_slider.valueChanged.connect(self._on_default_brightness_changed)
        def_bright_layout = QHBoxLayout()
        def_bright_layout.addWidget(self.default_brightness_slider); def_bright_layout.addWidget(self.default_brightness_label)
        lights_defaults_layout.addRow(self._create_label("Default Brightness:"), def_bright_layout)

        self.govee_override_checkbox = QCheckBox("Let Govee Mobile App Control Brightness")
        self.govee_override_checkbox.setToolTip("If enabled, the desktop app will ONLY control colors. Brightness is left to the Govee app.")
        is_override_on = settings.value("govee_brightness_override", "false") == "true"
        self.govee_override_checkbox.setChecked(is_override_on)
        self.govee_override_checkbox.toggled.connect(lambda c: self.default_brightness_slider.setDisabled(c))
        self.default_brightness_slider.setDisabled(is_override_on)
        
        lights_defaults_layout.addRow(self.govee_override_checkbox)

        # Sound Effects
        sound_group = QGroupBox("Sound Effects")
        sound_layout_form = QFormLayout(sound_group)
        sound_layout_form.setSpacing(12)
        global_layout.addWidget(sound_group)

        self.sound_volume_slider = QSlider(Qt.Horizontal)
        self.sound_volume_slider.setRange(0, 100)
        current_vol = int(self.parent().sound_manager.base_volume * 100)
        self.sound_volume_slider.setValue(current_vol)
        self.sound_volume_label = self._create_dynamic_label(f"{current_vol}%")
        self.sound_volume_slider.valueChanged.connect(self._on_sound_volume_changed)
        
        sound_layout = QHBoxLayout()
        sound_layout.addWidget(self.sound_volume_slider)
        sound_layout.addWidget(self.sound_volume_label)
        sound_layout_form.addRow(self._create_label("Volume:"), sound_layout)

        settings_behavior_group = QGroupBox("Settings")
        settings_behavior_layout = QVBoxLayout(settings_behavior_group)
        settings_behavior_layout.setContentsMargins(15, 15, 15, 15)
        settings_behavior_layout.setSpacing(10)
        global_layout.addWidget(settings_behavior_group)

        self.auto_save_checkbox = QCheckBox("Auto-save changes immediately")
        self.auto_save_checkbox.setChecked(self._auto_save_enabled)
        self.auto_save_checkbox.setToolTip("When enabled, changes are saved as soon as they are edited.")
        self.auto_save_checkbox.toggled.connect(self._on_auto_save_toggled)
        settings_behavior_layout.addWidget(self.auto_save_checkbox)

        self.saved_themes_button = QPushButton("Open Saved Themes")
        self.saved_themes_button.setToolTip("Browse, import, export, and delete saved themes.")
        self.saved_themes_button.clicked.connect(self.open_theme_library_dialog)
        settings_behavior_layout.addWidget(self.saved_themes_button)

        # Data Management Group
        data_group = QGroupBox("Maintenance")
        data_layout = QVBoxLayout(data_group)
        data_layout.setContentsMargins(15, 15, 15, 15)
        self.clear_cache_btn = QPushButton("Clear Theme Cache")
        self.clear_cache_btn.clicked.connect(self.confirm_clear_cache)
        data_layout.addWidget(self.clear_cache_btn)
        
        self.reset_app_btn = QPushButton("Reset Application Setup")
        self.reset_app_btn.clicked.connect(self.confirm_reset_app)
        data_layout.addWidget(self.reset_app_btn)
        
        global_layout.addWidget(data_group)
        global_layout.addStretch()

        yield # Yield after Tab 3 setup

        # --- Tab 4: Connections ---
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
        self.tab_widget.addTab(credentials_tab, "Connections")

        # --- Microphone Connection ---
        mic_group = QGroupBox("Microphone (Listen Mode)")
        mic_layout = QVBoxLayout(mic_group)
        
        self.mic_combo = NoScrollComboBox()
        self.mic_combo.setItemDelegate(QStyledItemDelegate())
        self.mic_combo.addItem("Default System Microphone", -1)
        
        mic_layout.addWidget(self._create_label("Note: Listen mode natively uses your default Windows microphone.\nChange your default device in Windows Sound Settings to switch inputs."))
        mic_layout.addWidget(self.mic_combo)
        credentials_layout.addWidget(mic_group)

        method_group = QGroupBox("Media Methods")
        method_layout = QVBoxLayout(method_group)
        method_layout.setContentsMargins(10, 10, 10, 10)
        method_layout.setSpacing(10)

        self.spotify_method_checkbox = None
        self.apple_music_method_checkbox = None
        self.windows_media_method_checkbox = QCheckBox("Enable Windows Media Sessions")
        self.windows_media_method_checkbox.setChecked(settings.value("windows_media_method_enabled", "true") == "true")
        method_layout.addWidget(self.windows_media_method_checkbox)

        spotify_has_creds = bool(str(self.initial_spotify_id).strip() and str(self.initial_spotify_secret).strip())
        if spotify_has_creds:
            self.spotify_method_checkbox = QCheckBox("Enable Spotify Method")
            self.spotify_method_checkbox.setChecked(settings.value("spotify_method_enabled", "true") == "true")
            method_layout.addWidget(self.spotify_method_checkbox)
        else:
            spotify_hint = self._create_dynamic_label(
                "Spotify credentials are missing. Add Client ID and Client Secret below to enable Spotify.",
                is_html_or_wrapped=True,
            )
            spotify_hint.setWordWrap(True)
            method_layout.addWidget(spotify_hint)
            spotify_focus_btn = QPushButton("Set Up Spotify Credentials")
            spotify_focus_btn.clicked.connect(lambda: self.spotify_id_input.setFocus())
            method_layout.addWidget(spotify_focus_btn)

        apple_has_creds = bool(
            str(self.initial_apple_music_team_id).strip()
            and str(self.initial_apple_music_key_id).strip()
            and str(self.initial_apple_music_private_key).strip()
        )
        if apple_has_creds:
            self.apple_music_method_checkbox = QCheckBox("Enable Apple Music Method")
            self.apple_music_method_checkbox.setChecked(settings.value("apple_music_method_enabled", "true") == "true")
            method_layout.addWidget(self.apple_music_method_checkbox)
        else:
            apple_hint = self._create_dynamic_label(
                "Apple Music credentials are missing. Add Team ID, Key ID, and Private Key below to enable Apple Music.",
                is_html_or_wrapped=True,
            )
            apple_hint.setWordWrap(True)
            method_layout.addWidget(apple_hint)
            apple_focus_btn = QPushButton("Set Up Apple Music Credentials")
            apple_focus_btn.clicked.connect(lambda: self.apple_music_team_id_input.setFocus())
            method_layout.addWidget(apple_focus_btn)

        windows_hint = self._create_dynamic_label(
            "Windows media sessions can show playback, but they never control lights.",
            is_html_or_wrapped=True,
        )
        windows_hint.setWordWrap(True)
        method_layout.addWidget(windows_hint)
        credentials_layout.addWidget(method_group)

        spotify_group = QGroupBox("Spotify Connection")
        spotify_layout = QFormLayout(spotify_group)
        spotify_layout.setSpacing(12)
        self.spotify_id_input = QLineEdit(self.initial_spotify_id)
        self.spotify_secret_input = QLineEdit(self.initial_spotify_secret)
        self.spotify_id_input.setEchoMode(QLineEdit.Password)
        self.spotify_secret_input.setEchoMode(QLineEdit.Password)
        spotify_layout.addRow(self._create_label("Client ID:"), self.spotify_id_input)
        spotify_layout.addRow(self._create_label("Client Secret:"), self.spotify_secret_input)
        credentials_layout.addWidget(spotify_group)

        apple_music_group = QGroupBox("Apple Music Connection")
        apple_music_layout = QFormLayout(apple_music_group)
        apple_music_layout.setSpacing(12)
        self.apple_music_team_id_input = QLineEdit(self.initial_apple_music_team_id)
        self.apple_music_key_id_input = QLineEdit(self.initial_apple_music_key_id)
        self.apple_music_private_key_input = QLineEdit(self.initial_apple_music_private_key)
        self.apple_music_user_token_input = QLineEdit(self.initial_apple_music_user_token)
        self.apple_music_private_key_input.setEchoMode(QLineEdit.Password)

        apple_music_help_label = self._create_dynamic_label("ⓘ Hover for Apple Music setup steps", is_html_or_wrapped=True)
        apple_music_help_label.setToolTip(
            "To get Apple Music credentials:\n"
            "1) Open developer.apple.com/account\n"
            "2) Create a MusicKit key\n"
            "3) Copy Team ID and Key ID\n"
            "4) Paste .p8 private key contents here\n"
            "5) User token is optional for personalized features"
        )
        apple_music_group.setToolTip(apple_music_help_label.toolTip())

        apple_music_layout.addRow(apple_music_help_label)
        apple_music_layout.addRow(self._create_label("Team ID:"), self.apple_music_team_id_input)
        apple_music_layout.addRow(self._create_label("Key ID:"), self.apple_music_key_id_input)
        apple_music_layout.addRow(self._create_label("Private Key (.p8):"), self.apple_music_private_key_input)
        apple_music_layout.addRow(self._create_label("User Token (Optional):"), self.apple_music_user_token_input)
        credentials_layout.addWidget(apple_music_group)

        govee_cred_group = QGroupBox("Govee Lights")
        govee_cred_layout = QVBoxLayout(govee_cred_group)
        govee_api_layout = QHBoxLayout()
        self.govee_key_input = QLineEdit(self.initial_govee_key)
        self.govee_key_input.setEchoMode(QLineEdit.Password)
        self.find_govee_button = QPushButton("Find Devices")
        govee_api_layout.addWidget(self._create_dynamic_label("API Key:"))
        govee_api_layout.addWidget(self.govee_key_input)
        govee_api_layout.addWidget(self.find_govee_button)
        govee_cred_layout.addLayout(govee_api_layout)

        self.govee_status_label = self._create_dynamic_label("Enter your Govee API key, then click 'Find Devices' to choose the lights this app controls.", is_html_or_wrapped=True)
        self.govee_status_label.setWordWrap(True)
        govee_cred_layout.addWidget(self.govee_status_label)

        self.govee_device_table = QTableWidget()
        self.govee_device_table.setColumnCount(4)
        self.govee_device_table.setHorizontalHeaderLabels(["Use", "Device ID", "Model", "Display Name"])
        self.govee_device_table.horizontalHeader().setStretchLastSection(True)
        self.govee_device_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        govee_cred_layout.addWidget(self.govee_device_table)
        credentials_layout.addWidget(govee_cred_group)

        show_hide_button = QPushButton("Show Secrets")
        show_hide_button.setCheckable(True)
        show_hide_button.setToolTip("Show or hide API keys and tokens.")
        show_hide_button.toggled.connect(self.toggle_credential_visibility)
        credentials_layout.addWidget(show_hide_button, 0, Qt.AlignRight)
        credentials_layout.addStretch()

        yield # Yield after Tab 4 setup

        # --- Tab 5: Keyboard Shortcuts ---
        controls_tab = QWidget()
        controls_tab_layout = QVBoxLayout(controls_tab)
        controls_tab_layout.setContentsMargins(0, 0, 5, 0)

        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        controls_content = QWidget()
        controls_content.setObjectName("scrollAreaContent")
        controls_scroll.setWidget(controls_content)

        from PyQt5.QtWidgets import QGridLayout
        controls_layout = QGridLayout(controls_content)
        controls_layout.setContentsMargins(15, 15, 15, 15)
        controls_layout.setSpacing(15)
        controls_layout.setColumnStretch(1, 1) 
        
        controls_tab_layout.addWidget(controls_scroll)
        self.tab_widget.addTab(controls_tab, "Keyboard Shortcuts")

        controls_layout.setColumnStretch(0, 0)
        controls_layout.setColumnStretch(1, 0)
        controls_layout.setColumnStretch(2, 1)

        help_label = self._create_dynamic_label(
            "Click a key button, press a key to remap, or clear an action to leave it unassigned.",
            is_html_or_wrapped=True
        )
        help_label.setWordWrap(True)
        controls_layout.addWidget(help_label, 0, 0, 1, 3)

        reset_shortcuts_btn = QPushButton("Reset All Shortcuts to Defaults")
        reset_shortcuts_btn.setToolTip("Restore all shortcut bindings to their default values")
        reset_shortcuts_btn.clicked.connect(self._reset_shortcuts_to_defaults)
        controls_layout.addWidget(reset_shortcuts_btn, 1, 0, 1, 3)

        row = 2
        for definition in self.shortcut_definitions:
            action_id = definition.get("id", "")
            action_label = self._create_dynamic_label(f"<b>{definition.get('label', action_id)}</b>", is_html_or_wrapped=True)
            action_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            action_label.setFixedWidth(180)
            controls_layout.addWidget(action_label, row, 0)

            key_button = QPushButton(self._shortcut_display_text(action_id))
            key_button.setToolTip("Left-click to assign. Right-click to clear.")
            key_button.clicked.connect(lambda checked=False, aid=action_id: self._on_shortcut_button_clicked(aid))
            key_button.setContextMenuPolicy(Qt.CustomContextMenu)
            key_button.customContextMenuRequested.connect(
                lambda pos, aid=action_id: self._clear_shortcut_binding(aid)
            )
            key_button.setMinimumWidth(120)
            controls_layout.addWidget(key_button, row, 1)
            self.shortcut_buttons[action_id] = key_button

            desc_text = definition.get("description", "")
            desc_label = self._create_dynamic_label(desc_text, is_html_or_wrapped=True)
            desc_label.setWordWrap(True)
            desc_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            controls_layout.addWidget(desc_label, row, 2)
            row += 1

        self.shortcut_status_label = self._create_dynamic_label("", is_html_or_wrapped=True)
        self.shortcut_status_label.setWordWrap(True)
        controls_layout.addWidget(self.shortcut_status_label, row, 0, 1, 3)
        controls_layout.setRowStretch(row + 1, 1)

        yield

        # --- Tab 6: Updates ---
        updates_tab = QWidget()
        updates_layout = QVBoxLayout(updates_tab)
        updates_layout.setContentsMargins(0, 0, 0, 0)
        
        self.updates_browser = QTextBrowser()
        self.updates_browser.setObjectName("updatesBrowser")
        self.updates_browser.setOpenExternalLinks(True)
        updates_layout.addWidget(self.updates_browser)
        self.tab_widget.addTab(updates_tab, "App Updates")

        yield # Yield after Tab 6 setup

        # --- Typography Group (Current Theme) ---
        text_group = QGroupBox("Text & Typography")
        text_layout = QFormLayout(text_group)
        text_layout.setSpacing(12)
        self.text_preview, self.pick_text_btn, self.reset_text_btn = self._create_color_picker(self.ui_text_color, self.pick_text_color, self.reset_text_color, is_text=True)
        text_layout.addRow(self._create_label("Text Color:"), self.create_color_row(self.text_preview, self.pick_text_btn, self.reset_text_btn))
        self.title_gradient_checkbox = QCheckBox("Use Gradient Song Title")
        self.title_gradient_checkbox.setChecked(self.title_gradient_enabled)
        self.title_grad_preview, self.title_grad_pick_btn, _ = self._create_color_picker(
            self.title_gradient_color,
            self.pick_player_title_gradient_color,
            is_text=True
        )
        self.title_gradient_dir_combo = NoScrollComboBox()
        self.title_gradient_dir_combo.setItemDelegate(QStyledItemDelegate())
        self.title_gradient_dir_combo.addItems(self.GRADIENT_DIRECTION_OPTIONS)
        self.title_gradient_dir_combo.setCurrentText(self._normalize_gradient_direction_label(self.title_gradient_direction))
        self.title_grad_pick_btn.setEnabled(self.title_gradient_checkbox.isChecked())
        self.title_grad_preview.setEnabled(self.title_gradient_checkbox.isChecked())
        self.title_gradient_dir_combo.setEnabled(self.title_gradient_checkbox.isChecked())
        self.title_gradient_checkbox.toggled.connect(self.title_grad_pick_btn.setEnabled)
        self.title_gradient_checkbox.toggled.connect(self.title_grad_preview.setEnabled)
        self.title_gradient_checkbox.toggled.connect(self.title_gradient_dir_combo.setEnabled)
        text_layout.addRow(self.title_gradient_checkbox)
        text_layout.addRow(self._create_label("Gradient Color:"), self.create_color_row(self.title_grad_preview, self.title_grad_pick_btn))
        text_layout.addRow(self._create_label("Gradient Direction:"), self.title_gradient_dir_combo)
        self.text_preview_shadow = QGraphicsDropShadowEffect()
        self.text_preview.setGraphicsEffect(self.text_preview_shadow)

        self.override_font_checkbox = QCheckBox("Use Custom Font for This Theme")
        self.override_font_checkbox.setChecked(self.is_font_family_overridden)
        self.override_font_checkbox.toggled.connect(self._on_override_font_toggled)

        self.font_family_combo = NoScrollComboBox()
        self.font_family_combo.setToolTip("Select the font family for the track title and artist.")
        self.font_family_combo.setEnabled(self.is_font_family_overridden)
        self.font_family_combo.setItemDelegate(FontFamilyDelegate(self.font_family_combo))
        
        self.font_style_combo = NoScrollComboBox()
        self.font_style_combo.setToolTip("Select the style for the chosen font family.")
        self.font_style_combo.setEnabled(self.is_font_family_overridden)
        self.font_style_combo.setItemDelegate(FontStyleDelegate(lambda: self.font_family_combo.currentText(), self.font_style_combo))

        self.font_search_input = QLineEdit()
        self.font_search_input.setPlaceholderText("Search fonts...")
        self.font_search_input.setEnabled(self.is_font_family_overridden)

        self.override_size_checkbox = QCheckBox("Use Custom Font Size for This Theme")
        self.override_size_checkbox.setChecked(self.is_font_size_overridden)
        self.override_size_checkbox.toggled.connect(self._on_override_size_toggled)

        self.font_size_slider = QSlider(Qt.Horizontal); self.font_size_slider.setRange(50, 200); self.font_size_slider.setValue(self.initial_font_size_scale)
        self.font_size_slider.setEnabled(self.is_font_size_overridden)
        self.font_size_label = self._create_dynamic_label(f"{self.initial_font_size_scale}%")
        self.font_size_slider.valueChanged.connect(lambda v: self.font_size_label.setText(f"{v}%"))
        self.font_size_slider.sliderReleased.connect(self.update_previews)
        size_layout = QHBoxLayout(); size_layout.addWidget(self.font_size_slider); size_layout.addWidget(self.font_size_label)

        self.shadow_checkbox = QCheckBox("Enable Text Shadow")
        self.title_case_radios, title_case_widget = self._create_case_controls(self.initial_title_case)
        self.artist_case_radios, artist_case_widget = self._create_case_controls(self.initial_artist_case)

        border_line = QFrame()
        border_line.setFrameShape(QFrame.HLine)
        border_line.setFrameShadow(QFrame.Sunken)
        border_line.setStyleSheet("background-color: #555;")

        self.text_border_checkbox = QCheckBox("Enable Text Outline")
        self.text_border_checkbox.setChecked(self.initial_text_border_enabled)
        self.text_border_checkbox.toggled.connect(self._on_text_border_toggled)
        
        self.reset_text_border_enable_btn = QPushButton("Auto")
        self.reset_text_border_enable_btn.setToolTip("Reset to automatic border detection based on contrast")
        self.reset_text_border_enable_btn.clicked.connect(self.reset_text_border_enable)
        
        border_enable_widget = QWidget()
        border_enable_layout = QHBoxLayout(border_enable_widget)
        border_enable_layout.setContentsMargins(0,0,0,0)
        border_enable_layout.addWidget(self.text_border_checkbox)
        border_enable_layout.addWidget(self.reset_text_border_enable_btn)
        border_enable_layout.addStretch()

        self.text_border_preview, self.pick_text_border_btn, self.reset_text_border_btn = self._create_color_picker(self.text_border_color, self.pick_text_border_color, self.reset_text_border_color)

        self.override_border_size_checkbox = QCheckBox("Override Border Size")
        self.override_border_size_checkbox.setChecked(self.is_border_size_overridden)
        self.override_border_size_checkbox.toggled.connect(self._on_override_border_size_toggled)

        self.text_border_size_slider = QSlider(Qt.Horizontal); self.text_border_size_slider.setRange(1, 10); self.text_border_size_slider.setValue(self.initial_text_border_size)
        self.text_border_size_slider.setEnabled(self.is_border_size_overridden)
        self.text_border_size_label = self._create_dynamic_label(f"{self.initial_text_border_size}px")
        self.text_border_size_slider.valueChanged.connect(lambda v: self.text_border_size_label.setText(f"{v}px"))
        self.text_border_size_slider.sliderReleased.connect(self.update_previews)
        border_size_layout = QHBoxLayout(); border_size_layout.addWidget(self.text_border_size_slider); border_size_layout.addWidget(self.text_border_size_label)

        text_layout.addRow(self.override_font_checkbox)
        text_layout.addRow(self._create_label("Find Font:"), self.font_search_input)
        text_layout.addRow(self._create_label("Font Family:"), self.font_family_combo)
        text_layout.addRow(self._create_label("Font Style:"), self.font_style_combo)
        text_layout.addRow(self.override_size_checkbox)
        text_layout.addRow(self._create_label("Size:"), size_layout)
        text_layout.addRow(self.shadow_checkbox)
        text_layout.addRow(border_line)
        text_layout.addRow(border_enable_widget)
        text_layout.addRow(self._create_label("Outline Color:"), self.create_color_row(self.text_border_preview, self.pick_text_border_btn, self.reset_text_border_btn))
        text_layout.addRow(self.override_border_size_checkbox)
        text_layout.addRow(self._create_label("Outline Size:"), border_size_layout)
        text_layout.addRow(self._create_label("Title Case:"), title_case_widget)
        text_layout.addRow(self._create_label("Artist Case:"), artist_case_widget)
        self.settings_col_2.addWidget(text_group) 

        yield # Yield after Typography Group

        # --- Background & Atmosphere Group (Current Theme) ---
        self.ui_group = QGroupBox("Background & Blobs")
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
        ui_colors_layout.addRow(self._create_label("Accent / Art Frame:"), self.create_color_row(self.ui_accent_preview, pick_ui_accent_btn, self.reset_ui_accent_btn))
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
        blob_label = self._create_dynamic_label("Blob Colors:", is_html_or_wrapped=False)
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
        self.art_group = QGroupBox("Album Artwork")
        art_layout = QVBoxLayout(self.art_group)
        self.album_art_border_checkbox = QCheckBox("Show Artwork Frame")
        self.album_art_border_checkbox.setChecked(self.initial_album_art_border_enabled)
        art_layout.addWidget(self.album_art_border_checkbox)

        art_scope_widget = QWidget()
        art_scope_layout = QHBoxLayout(art_scope_widget)
        art_scope_layout.setContentsMargins(0, 0, 0, 0)
        art_scope_layout.addWidget(self._create_dynamic_label("Custom Artwork Applies To:", is_html_or_wrapped=False))
        self.custom_art_track_radio = QRadioButton("This Track")
        self.custom_art_album_radio = QRadioButton("This Album")
        self.custom_art_track_radio.setChecked(self.custom_art_scope == "track")
        self.custom_art_album_radio.setChecked(self.custom_art_scope == "album")
        art_scope_layout.addWidget(self.custom_art_track_radio)
        art_scope_layout.addWidget(self.custom_art_album_radio)
        art_scope_layout.addStretch(1)
        art_layout.addWidget(art_scope_widget)

        art_button_layout = QHBoxLayout()
        set_art_button = QPushButton("Choose Custom Artwork...")
        reset_art_button = QPushButton("Remove Custom Artwork")
        art_button_layout.addWidget(set_art_button)
        art_button_layout.addWidget(reset_art_button)
        art_layout.addLayout(art_button_layout)
        self.settings_col_1.addWidget(self.art_group)
        
        for i, color in enumerate(self.blob_colors):
            self._add_blob_color_row(color, i)
        self._update_blob_buttons_style()

        yield # Yield after Art Group

        # --- Interface Group (Current Theme) ---
        interface_group = QGroupBox("Playback UI")
        interface_layout = QFormLayout(interface_group)
        
        self.override_progress_bar_checkbox = QCheckBox("Use Theme-Specific Progress Bar Setting")
        self.override_progress_bar_checkbox.setChecked(self.is_progress_bar_overridden)
        self.override_progress_bar_checkbox.toggled.connect(self._on_override_progress_bar_toggled)
        
        self.progress_bar_checkbox = QCheckBox("Show Progress Bar")
        self.progress_bar_checkbox.setChecked(self.initial_progress_bar_enabled)
        self.progress_bar_checkbox.setEnabled(self.is_progress_bar_overridden)
        interface_layout.addRow(self.override_progress_bar_checkbox)
        interface_layout.addRow("", self.progress_bar_checkbox)
        self.settings_col_2.addWidget(interface_group)

        yield # Yield after Interface Group

        # --- Light Synchronization Group (Current Theme) ---
        self.govee_group = QGroupBox("Light Sync")
        govee_group_main_layout = QVBoxLayout(self.govee_group)
        govee_group_main_layout.setContentsMargins(10, 10, 10, 10)
        govee_group_main_layout.setSpacing(12)
        
        status_widget = QWidget()
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(0,0,0,0)
        status_layout.setSpacing(6)
        lights_status = "Enabled" if self.parent().lights_enabled else "Disabled"
        status_layout.addWidget(self._create_dynamic_label("Global Lights:"))
        status_value_label = self._create_dynamic_label(lights_status)
        status_value_label.setStyleSheet("font-weight: normal;") 
        status_layout.addWidget(status_value_label)
        status_layout.addStretch()
        reset_lights_btn = QPushButton("Reset")
        reset_lights_btn.setToolTip("Reset lights to auto-generated colors")
        reset_lights_btn.clicked.connect(self.reset_lights_to_auto)
        status_layout.addWidget(reset_lights_btn)
        govee_group_main_layout.addWidget(status_widget)

        brightness_widget = QWidget()
        brightness_layout = QHBoxLayout(brightness_widget)
        brightness_layout.setContentsMargins(0,0,0,0)
        
        self.override_brightness_checkbox = QCheckBox("Use Theme")
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

        self.sizegrip = QSizeGrip(self)

        # --- Action Buttons ---
        self.action_layout = QHBoxLayout()
        self.action_layout.setContentsMargins(20, 5, 20, 15)
        self.action_layout.setSpacing(10)
        self.action_layout.addStretch()
        
        self.quick_save_btn = QPushButton("Quick Save")
        self.quick_save_btn.setToolTip("Save changed settings immediately.")
        self.quick_save_btn.clicked.connect(lambda: self.save_and_close(quick=True))
        
        self.save_full_theme_btn = QPushButton("Save Theme")
        self.save_full_theme_btn.setToolTip("Save the current look as a fixed theme (snapshots all colors and settings).")
        self.save_full_theme_btn.clicked.connect(self.save_full_theme)
        
        self.save_button = QPushButton("Save...")
        self.save_button.setDefault(True)
        self.save_button.setToolTip("Choose which settings to save.")
        self.save_button.clicked.connect(lambda: self.save_and_close(quick=False))

        self.done_button = QPushButton("Done")
        self.done_button.setToolTip("Save all settings and close.")
        self.done_button.clicked.connect(self.done_auto_save)
        
        self.cancel_button = QPushButton("Cancel")
        self.action_layout.addWidget(self.quick_save_btn)
        self.action_layout.addWidget(self.save_full_theme_btn)
        self.action_layout.addWidget(self.save_button)
        self.action_layout.addWidget(self.done_button)
        self.action_layout.addWidget(self.cancel_button)
        self.layout().addLayout(self.action_layout)

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
        self._refresh_save_buttons_for_current_tab()
        
        self._install_filter_recursive(self)
        self.tab_widget.installEventFilter(self.ui_event_filter)

        # --- 4. POPULATE DATA & SET INITIAL STATES ---
        self.shadow_checkbox.setChecked(self.initial_shadow_enabled)

        # FOOLPROOF FONT LOADING: If background thread failed or hasn't finished, load synchronously NOW.
        if not self.parent()._fonts_loaded or not self.parent().base_font_families:
            from PyQt5.QtGui import QFontDatabase
            db = QFontDatabase()
            self.parent().base_font_families = db.families()
            self.parent().font_styles_cache = {fam: db.styles(fam) for fam in self.parent().base_font_families}
            self.parent()._fonts_loaded = True

        self.font_styles_cache = self.parent().font_styles_cache
        self.base_font_families = self.parent().base_font_families

        # Safely populate the combo boxes without triggering early update signals
        self.font_family_combo.blockSignals(True)
        self.default_font_family_combo.blockSignals(True)

        self.font_family_combo.clear()
        self.default_font_family_combo.clear()
        self.font_family_combo.addItems(self.base_font_families)
        self.default_font_family_combo.addItems(self.base_font_families)

        self.font_family_combo.blockSignals(False)
        self.default_font_family_combo.blockSignals(False)

        # Forceably unlock the widgets so they are immediately clickable
        for w in [self.font_family_combo, self.font_style_combo, self.font_search_input, self.default_font_family_combo, self.default_font_style_combo]:
            w.setEnabled(True)

        self._font_list_populated = True

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
        # Default height start
        max_h = 600
        
        # Iterate tabs to find max content size.
        for i in range(self.tab_widget.count()):
            page = self.tab_widget.widget(i)

            scroll_area = page.findChild(QScrollArea)
            if scroll_area:
                content = scroll_area.widget()
                if content:
                    content.adjustSize()
                    size = content.sizeHint()
                    # We still check width to ensure it's wide enough
                    max_w = max(max_w, size.width() + 50)
                    # We check height for other tabs to ensure they fit
                    max_h = max(max_h, size.height() + 50)

        # Add chrome margins
        max_w += 40 
        max_h += 120 

        # Clamp to screen size
        screen = QApplication.primaryScreen()
        if self.parent() and self.parent().windowHandle():
            screen = self.parent().windowHandle().screen()
        avail = screen.availableGeometry()
        
        final_w = min(max_w, int(avail.width() * 0.9))
        final_h = min(max_h, int(avail.height() * 0.85)) # Slightly smaller height cap
        
        self.resize(final_w, final_h)
        self.setMinimumSize(800, 500)

    def _on_default_font_size_changed(self, value):
        """Updates default size label and preview without mutating theme-specific size."""
        self.default_font_size_label.setText(f"{value}%")
        self.update_previews()

    def _on_sound_volume_changed(self, value):
        self.sound_volume_label.setText(f"{value}%")
        # Live update master volume
        self.parent().sound_manager.set_master_volume(value / 100.0)

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
        pos_anim.setDuration(duration); pos_anim.setStartValue(current_pos); pos_anim.setEndValue(target_pos); pos_anim.setEasingCurve(QEasingCurve.InCubic)

        if anim_type == "Fade":
            self.exit_anim_group.addAnimation(opacity_anim)
        else: # Slide, Bounce, Fade Slide - all use pos + opacity for clean exit
            self.exit_anim_group.addAnimation(pos_anim)
            self.exit_anim_group.addAnimation(opacity_anim)

        self.exit_anim_group.finished.connect(lambda: super(ColorEditorDialog, self).done(self._result_code))
        self.exit_anim_group.start()

    def fetch_updates(self):
        from config import APP_VERSION # Import here to avoid circular imports if any
        self.updates_browser.setHtml("<p style='color: #aaa;'>Loading updates from GitHub...</p>")
        worker = GitHubUpdatesWorker("Hangt1m3", "Dynamic-Player", token=GITHUB_TOKEN, current_version=APP_VERSION)
        worker.signals.result.connect(self.display_updates)
        worker.signals.error.connect(lambda e: self.display_updates(str(e))) 
        self.threadpool.start(worker)

    def display_updates(self, data):
        if isinstance(data, dict):
            # Result from GitHubUpdatesWorker
            self.commits_data = data # Store the whole dict
            self.latest_version = data.get("latest_version", "?.?.?")
            self.current_version = data.get("current_version", "?.?.?")
            self.render_updates()
        elif isinstance(data, list):
            self.commits_data = data
            self.render_updates()
        else:
            self.updates_browser.setHtml(str(data))

    # [UPDATE THIS METHOD]
    def render_updates(self):
        if not self.commits_data: return
        
        # Use attributes set by display_updates, or fallback
        latest_version = getattr(self, "latest_version", "Unknown")
        current_version = getattr(self, "current_version", "Unknown")
        
        text_color = self.ui_text_color
        text_hex = text_color.name()
        
        dim_color = QColor(text_color)
        dim_color.setAlpha(180)
        dim_rgba = f"rgba({dim_color.red()}, {dim_color.green()}, {dim_color.blue()}, {dim_color.alpha()/255:.2f})"
        
        border_color = QColor(text_color)
        border_color.setAlpha(50)
        border_rgba = f"rgba({border_color.red()}, {border_color.green()}, {border_color.blue()}, {border_color.alpha()/255:.2f})"

        # HTML Header
        html = f"""
        <html>
        <head>
        <style>
            body {{ font-family: 'Segoe UI', sans-serif; margin: 20px; }}
            .header-box {{ 
                border-bottom: 2px solid {text_hex}; 
                padding-bottom: 15px; margin-bottom: 20px; 
            }}
            h2 {{ color: {text_hex}; margin: 0; padding-bottom: 5px; }}
            .version-info {{ font-size: 14px; color: {dim_rgba}; font-weight: bold; }}
            .commit {{ margin-bottom: 25px; border-bottom: 1px solid {border_rgba}; padding-bottom: 20px; }}
            .title {{ font-size: 15px; font-weight: bold; color: {text_hex}; margin-bottom: 5px; }}
            .meta {{ font-size: 12px; color: {dim_rgba}; margin-bottom: 10px; }}
            .desc {{ font-size: 13px; color: {text_hex}; margin-top: 8px; }}
        </style>
        </head>
        <body>
        <div class="header-box">
            <h2>System Updates</h2>
            <div class="version-info">
                Current: v{current_version} &nbsp;&nbsp;|&nbsp;&nbsp; Latest: {latest_version}
            </div>
        </div>
        """
        
        # Render Content based on type
        if isinstance(self.commits_data, dict):
            # Case 1: Official Release
            if self.commits_data.get('type') == 'release':
                 body = self.commits_data.get('body', '').replace('\n', '<br>')
                 html += f"<div class='desc'>{body}</div>"
            
            # Case 2: Commits (Fallback)
            elif self.commits_data.get('type') == 'commits':
                html += "<h3>Latest Activity (Commit History)</h3>"
                commits = self.commits_data.get('commits', [])
                if not commits:
                    html += "<div class='desc'>No recent commits found.</div>"
                
                for commit in commits:
                    desc_text = commit['desc'].replace('\n', '<br>')
                    desc_html = f"<div class='desc'>{desc_text}</div>" if commit['desc'] else ""
                    html += f"""
                    <div class='commit'>
                        <div class='title'>{commit['title']}</div>
                        <div class='meta'>{commit['date']} • {commit['author']}</div>
                        {desc_html}
                    </div>
                    """
        
        # Legacy fallback (just in case)
        elif isinstance(self.commits_data, list):
            html += "<h3>Latest Changes</h3>"
            for commit in self.commits_data:
                html += f"<div class='commit'><div class='title'>{commit.get('title','')}</div></div>"
                
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
        
        # 1. Update Main Stylesheet
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
        self._update_settings_titlebar_style()
        
        # 2. Update Custom Tab Bar Colors
        if hasattr(self, 'custom_tab_bar'):
            self.custom_tab_bar.setColors(self.ui_text_color, self.ui_bg_color, self.text_border_color, self.text_border_checkbox.isChecked())

        # 3. FIX: Update Govee Table Styling (White Rectangle Fix)
        if hasattr(self, 'govee_device_table'):
            # Calculate a semi-transparent grid color
            grid_rgba = f"rgba({self.ui_text_color.red()}, {self.ui_text_color.green()}, {self.ui_text_color.blue()}, 50)"
            
            table_style = f"""
                QTableWidget {{
                    background-color: transparent;
                    border: 1px solid {self.ui_text_color.name()};
                    gridline-color: {grid_rgba};
                    color: {self.ui_text_color.name()};
                }}
                QTableWidget::item {{
                    border-bottom: 1px solid {grid_rgba};
                    padding: 5px;
                }}
                QHeaderView::section {{
                    background-color: {self.ui_accent_color.name()};
                    color: {self.ui_bg_color.name()};
                    border: none;
                    padding: 4px;
                    font-weight: bold;
                }}
                QTableCornerButton::section {{
                    background-color: {self.ui_accent_color.name()};
                }}
                /* Fix Checkbox/Input colors inside table */
                QCheckBox, QLineEdit {{
                    color: {self.ui_text_color.name()};
                    background: transparent;
                }}
            """
            self.govee_device_table.setStyleSheet(table_style)

    def _update_settings_titlebar_style(self):
        """Updates the settings dialog title bar colors to match the current theme."""
        ar, ag, ab = self.ui_accent_color.red(), self.ui_accent_color.green(), self.ui_accent_color.blue()
        tc = self.ui_text_color.name()
        if hasattr(self, '_settings_title_sep'):
            self._settings_title_sep.setStyleSheet(f"background: rgba({ar}, {ag}, {ab}, 55);")
        if hasattr(self, '_settings_title_label'):
            self._settings_title_label.setStyleSheet(f"color: {tc}; font-weight: 600; font-size: 13px;")
        if hasattr(self, '_settings_close_btn'):
            self._settings_close_btn.setStyleSheet(
                f"QPushButton {{ border: none; background: transparent; font-size: 20px; color: {tc}; border-radius: 16px; font-weight: 300; }}"
                f" QPushButton:hover {{ color: #ffffff; background: #e0454a; border: none; }}"
                f" QPushButton:pressed {{ background: #c03030; color: #ffffff; }}"
            )

    def _update_blob_buttons_style(self):
        # Use the regular button theme for consistency with other buttons in settings
        btn_bg = self.ui_bg_color.lighter(130).name()
        btn_hover = self.ui_accent_color.name()
        txt_col = self.ui_text_color.name()
        
        btn_style = f"""
            QPushButton {{
                background-color: {btn_bg};
                color: {txt_col};
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 12px;
                min-width: 40px;
                min-height: 20px;
            }}
            QPushButton:hover {{
                background-color: {btn_hover};
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

    def _normalize_shortcut_key_text(self, key_text):
        if key_text is None:
            return ""

        candidate = str(key_text).strip()
        if not candidate:
            return ""

        seq = QKeySequence.fromString(candidate, QKeySequence.NativeText)
        if seq.isEmpty():
            seq = QKeySequence.fromString(candidate, QKeySequence.PortableText)
        if seq.isEmpty():
            return ""

        value = int(seq[0])
        modifiers = value & int(Qt.KeyboardModifierMask)
        if modifiers:
            return ""

        key = value & ~int(Qt.KeyboardModifierMask)
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr):
            return ""

        return QKeySequence(key).toString(QKeySequence.NativeText)

    def _normalize_shortcut_bindings(self, bindings):
        normalized = {}
        used_keys = set()

        if not isinstance(bindings, dict):
            bindings = {}

        defaults = {
            definition.get("id", ""): str(definition.get("default", ""))
            for definition in self.shortcut_definitions
        }

        for definition in self.shortcut_definitions:
            action_id = definition.get("id", "")
            raw_key = bindings.get(action_id, defaults.get(action_id, ""))
            key_text = self._normalize_shortcut_key_text(raw_key)
            if key_text and key_text not in used_keys:
                normalized[action_id] = key_text
                used_keys.add(key_text)
            else:
                normalized[action_id] = ""

        return normalized

    def _shortcut_display_text(self, action_id):
        key = self.shortcut_bindings.get(action_id, "")
        return key if key else "Unassigned"

    def _refresh_shortcut_rows(self):
        for action_id, button in self.shortcut_buttons.items():
            if self._shortcut_capture_action_id == action_id:
                button.setText("Press key...")
                button.setStyleSheet("font-weight: bold;")
            else:
                button.setText(self._shortcut_display_text(action_id))
                button.setStyleSheet("")

    def _cancel_shortcut_capture(self, clear_status=False):
        if getattr(self, "_shortcut_capture_action_id", None) is None:
            return
        self.releaseKeyboard()
        self._shortcut_capture_action_id = None
        self._shortcut_capture_button = None
        if clear_status and self.shortcut_status_label:
            self.shortcut_status_label.setText("")
        self._refresh_shortcut_rows()

    def _on_shortcut_button_clicked(self, action_id):
        if self._shortcut_capture_action_id == action_id:
            self._cancel_shortcut_capture(clear_status=True)
            return

        self._shortcut_capture_action_id = action_id
        self._shortcut_capture_button = self.shortcut_buttons.get(action_id)
        self.grabKeyboard()
        if self.shortcut_status_label:
            label = next((d.get("label", action_id) for d in self.shortcut_definitions if d.get("id") == action_id), action_id)
            self.shortcut_status_label.setText(f"Listening for {label}. Press a single key.")
        self._refresh_shortcut_rows()

    def _assign_shortcut(self, action_id, key_text):
        normalized = self._normalize_shortcut_key_text(key_text)
        if not normalized:
            return

        previous_action = None
        for candidate_id, existing in self.shortcut_bindings.items():
            if candidate_id != action_id and existing == normalized:
                previous_action = candidate_id
                break

        if previous_action:
            self.shortcut_bindings[previous_action] = ""

        self.shortcut_bindings[action_id] = normalized
        self._cancel_shortcut_capture(clear_status=False)
        self._refresh_shortcut_rows()

        if self.shortcut_status_label:
            if previous_action:
                prev_label = next((d.get("label", previous_action) for d in self.shortcut_definitions if d.get("id") == previous_action), previous_action)
                self.shortcut_status_label.setText(f"Assigned {normalized}. Removed from {prev_label} to keep keys unique.")
            else:
                self.shortcut_status_label.setText(f"Assigned {normalized}.")
        self._schedule_auto_save()

    def _reset_shortcuts_to_defaults(self):
        defaults = {
            definition.get("id", ""): str(definition.get("default", ""))
            for definition in self.shortcut_definitions
        }
        self._cancel_shortcut_capture(clear_status=False)
        self.shortcut_bindings = self._normalize_shortcut_bindings(defaults)
        self._refresh_shortcut_rows()
        if self.shortcut_status_label:
            self.shortcut_status_label.setText("Shortcut bindings reset to defaults.")
        self._schedule_auto_save()

    def _clear_shortcut_binding(self, action_id):
        if action_id not in getattr(self, "shortcut_bindings", {}):
            return

        if getattr(self, "_shortcut_capture_action_id", None) == action_id:
            self._cancel_shortcut_capture(clear_status=False)

        self.shortcut_bindings[action_id] = ""
        self._refresh_shortcut_rows()

        if self.shortcut_status_label:
            label = next((d.get("label", action_id) for d in self.shortcut_definitions if d.get("id") == action_id), action_id)
            self.shortcut_status_label.setText(f"Cleared {label} shortcut.")
        self._schedule_auto_save()

    def keyPressEvent(self, event):
        capture_action = getattr(self, "_shortcut_capture_action_id", None)
        if capture_action:
            modifiers = int(event.modifiers()) & ~int(Qt.KeypadModifier)
            if modifiers:
                if self.shortcut_status_label:
                    self.shortcut_status_label.setText("Use a single key without Ctrl, Alt, Shift, or Meta modifiers.")
                event.accept()
                return

            key = event.key()
            if key in (Qt.Key_unknown, Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr):
                event.accept()
                return

            key_text = QKeySequence(key).toString(QKeySequence.NativeText)
            self._assign_shortcut(capture_action, key_text)
            event.accept()
            return

        super().keyPressEvent(event)

    def event(self, event):
        # Qt can consume Tab for focus navigation before keyPressEvent.
        # Intercept it here so users can bind the Tab key reliably.
        capture_action = getattr(self, "_shortcut_capture_action_id", None)
        if capture_action and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Tab:
                self._assign_shortcut(capture_action, "Tab")
                event.accept()
                return True
        return super().event(event)

    def paintEvent(self, event):
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            outer_path = QPainterPath()
            outer_path.addRoundedRect(QRectF(self.rect()), 14, 14)

            preview_bg = QColor(self.ui_bg_color)
            preview_bg.setAlpha(240)

            painter.setClipPath(outer_path)
            painter.fillRect(self.rect(), preview_bg)

            title_h = getattr(self, '_SETTINGS_TITLE_BAR_HEIGHT', 50)
            header_color = QColor(self.ui_bg_color)
            if header_color.lightnessF() > 0.5:
                header_color = header_color.darker(108)
            else:
                header_color = header_color.lighter(112)
            header_color.setAlpha(240)
            painter.fillRect(0, 0, self.width(), title_h, header_color)

            painter.setClipping(False)
            ar, ag, ab = self.ui_accent_color.red(), self.ui_accent_color.green(), self.ui_accent_color.blue()
            border_color = QColor(ar, ag, ab, 120)
            painter.setPen(QPen(border_color, 1))
            painter.drawPath(outer_path)
        finally:
            painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.y() < 58:
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and not self.drag_pos.isNull():
            self.move(event.globalPos() - self.drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_pos = QPoint()

    def closeEvent(self, event):
        self._cancel_shortcut_capture(clear_status=False)
        if self._auto_save_timer.isActive():
            self._auto_save_timer.stop()
        if self.theme_library_dialog is not None:
            self.theme_library_dialog.close()
        super().closeEvent(event)

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
        self.update_previews()


    def _on_override_progress_bar_toggled(self, checked):
        self.progress_bar_checkbox.setEnabled(checked)
        if not checked:
            self.progress_bar_checkbox.setChecked(self.default_progress_bar_checkbox.isChecked())


    def _on_override_border_size_toggled(self, checked):
        self.text_border_size_slider.setEnabled(checked)
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
        self._schedule_auto_save()

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

    def pick_player_title_gradient_color(self):
        new_color = self._get_themed_color(self.title_gradient_color, "Select Player Title Gradient Color")
        if new_color.isValid():
            self.title_gradient_color = new_color
            self.title_grad_preview.setStyleSheet(f"background-color: {new_color.name()}; color: transparent; border-radius: 5px; border: 1px solid #555;")
            self._schedule_auto_save()

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
        self._sync_primary_tone_from_blobs()
        self.refresh_blob_rows()
        self._update_blob_buttons_style() # Ensure new button is styled
        self.update_previews()

    def remove_blob_color(self, index):
        if len(self.blob_colors) <= 1: return
        self.blob_colors.pop(index)
        self.is_blob_auto = False; QApplication.processEvents()
        self._sync_primary_tone_from_blobs()
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
            self._sync_primary_tone_from_blobs()
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
                    self._custom_art_changed = True
                    self._schedule_auto_save()
                except Exception as e:
                    print(f"Error loading custom art: {e}")
                    self.custom_art_b64 = None

    def reset_custom_art(self):
        self.custom_art_b64 = None
        self._custom_art_changed = True
        original_pixmap = self.parent().art.pixmap()
        self.current_art_pixmap = original_pixmap
        self._schedule_auto_save()

    def _active_custom_art_scope(self):
        return "album" if hasattr(self, "custom_art_album_radio") and self.custom_art_album_radio.isChecked() else "track"

    def _persist_custom_art(self):
        scope = self._active_custom_art_scope()
        track_config = self.color_cache.get_album_data(self.track_id) or {}
        album_config = self.color_cache.get_album_data(self.album_id) or {}

        if self.custom_art_b64:
            if scope == "album":
                album_config["custom_art_b64"] = self.custom_art_b64
                self.color_cache.set_album_data(self.album_id, album_config)
                if "custom_art_b64" in track_config:
                    track_config.pop("custom_art_b64", None)
                    self.color_cache.set_album_data(self.track_id, track_config)
            else:
                track_config["custom_art_b64"] = self.custom_art_b64
                self.color_cache.set_album_data(self.track_id, track_config)
                if "custom_art_b64" in album_config:
                    album_config.pop("custom_art_b64", None)
                    self.color_cache.set_album_data(self.album_id, album_config)
        else:
            if scope == "album":
                if "custom_art_b64" in album_config:
                    album_config.pop("custom_art_b64", None)
                    self.color_cache.set_album_data(self.album_id, album_config)
            else:
                if "custom_art_b64" in track_config:
                    track_config.pop("custom_art_b64", None)
                    self.color_cache.set_album_data(self.track_id, track_config)

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

    def start_content_fade_and_reload(self, album_id, track_id, album_art_pixmap, album_name="", artist_name=""):
        """Fades the dialog out, reloads the content for the new track, and fades it back in."""
        self._pending_reload_data = {
            "album_id": album_id,
            "track_id": track_id,
            "album_art_pixmap": album_art_pixmap,
            "album_name": album_name,
            "artist_name": artist_name
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
            animate=False,
            album_name=data.get("album_name", ""),
            artist_name=data.get("artist_name", "")
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

        self._sync_primary_tone_from_blobs()
        
        if self.is_lights_auto:
            for i, picker in enumerate(self.govee_color_pickers):
                picker["color"] = QColor(*lights_palette[i]) if i < len(lights_palette) else self.ui_accent_color
        
        if self.is_text_color_auto: self.ui_text_color = QColor(*text_color)
        if self.is_text_border_color_auto: self._update_auto_text_border_color()
        if self.is_text_border_auto: self._update_auto_text_border_enable()
             
        self._update_bg_accent_buttons()
        self.update_previews()
        self.update_stylesheet()

    def _get_theme_browser_grid(self):
        return self.theme_library_grid

    def populate_theme_browser(self):
        browser_grid = self._get_theme_browser_grid()
        if browser_grid is None:
            return

        # Clear existing layout
        while browser_grid.count():
            item = browser_grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        # Get cache
        cache = self.color_cache.cache
        row, col = 0, 0
        max_cols = 3
        
        found_any = False
        
        for album_id, data in cache.items():
            if not isinstance(data, dict): continue
            
            # Simple check to see if this is a "real" saved theme with IDs we can display
            # Note: The cache might store track_ids or album_ids. 
            # We try to deduce a displayable name. If the cache doesn't store name/artist, 
            # we might display the ID or "Unknown Album".
            # *However*, the WindowsMediaWorker now generates IDs based on Name+Artist.
            # But the cache key is just the hash. The cache VALUE stores settings.
            # If your cache doesn't store the Title/Artist strings, we can't display them 
            # unless we add them to the save logic. 
            # *Assumption*: We will show the ID or a placeholder, OR we assume the user 
            # has visited these and we want to show visual settings.
            
            card = self.create_theme_card(album_id, data)
            browser_grid.addWidget(card, row, col)
            
            found_any = True
            col += 1
            if col >= max_cols:
                col = 0
                row += 1
        
        if not found_any:
            lbl = QLabel("No themes saved yet.")
            lbl.setStyleSheet(f"color: {self.ui_text_color.name()}; font-style: italic;")
            browser_grid.addWidget(lbl, 0, 0)

    def create_theme_card(self, album_id, data):
        card = QFrame()
        card.setFixedSize(220, 140) 
        
        def safe_rgb(val):
            if not val or not isinstance(val, (list, tuple)) or len(val) < 3: return None
            return [int(c) for c in val[:3]]

        # --- Background ---
        bg_rgb = safe_rgb(data.get("player_bg_color"))
        if not bg_rgb and "ui_palette" in data:
            bg_rgb = safe_rgb(data["ui_palette"][0])
        if not bg_rgb: bg_rgb = [40, 40, 40]
        bg_color = QColor(*bg_rgb)

        blob_palette = data.get("blob_palette", [])
        if blob_palette and len(blob_palette) > 0:
            blob_rgb = safe_rgb(blob_palette[0])
            if blob_rgb:
                blob_col = QColor(*blob_rgb)
                bg_style = f"qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1, stop:0 {bg_color.name()}, stop:1 {blob_col.name()})"
            else: bg_style = bg_color.name()
        else: bg_style = bg_color.name()

        # --- Text Color ---
        text_rgb = safe_rgb(data.get("text_color"))
        if text_rgb: text_color = QColor(*text_rgb)
        else: text_color = QColor(255, 255, 255)

        # --- Card Border Logic ---
        border_width_px = 2
        border_color_q = None
        
        text_border_enabled = data.get("text_border_enabled", False)
        saved_border_rgb = safe_rgb(data.get("text_border_color"))
        
        if text_border_enabled and saved_border_rgb:
            border_color_q = QColor(*saved_border_rgb)
        elif "ui_palette" in data and len(data["ui_palette"]) > 1:
            accent = safe_rgb(data["ui_palette"][1])
            if accent: border_color_q = QColor(*accent)
        
        if not border_color_q:
            border_color_q = QColor(text_color)
            border_color_q.setAlpha(100)

        card_border_rgba = f"rgba({border_color_q.red()}, {border_color_q.green()}, {border_color_q.blue()}, {border_color_q.alpha()/255:.2f})"

        # --- Stylesheet ---
        # FIX: added 'QLabel { border: none; ... }' to remove random borders around text
        card.setStyleSheet(f"""
            QFrame {{
                background: {bg_style};
                border: {border_width_px}px solid {card_border_rgba};
                border-radius: 12px;
            }}
            QLabel {{
                border: none;
                background: transparent;
                padding: 0px; 
            }}
            QPushButton {{
                background-color: rgba({text_color.red()}, {text_color.green()}, {text_color.blue()}, 40);
                color: {text_color.name()};
                border: none;
                border-radius: 4px;
                font-weight: bold;
                padding: 2px 5px;
                font-size: 10px;
            }}
            QPushButton:hover {{
                background-color: {text_color.name()};
                color: {bg_color.name()};
            }}
        """)
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(2)
        
        # --- Metadata ---
        album_name = data.get("meta_album", "Unknown Album")
        artist_name = data.get("meta_artist", "Unknown Artist")
        if "meta_album" not in data: album_name = f"ID: {album_id[:8]}"

        # FIX: Use standard QLabel for robust word wrapping (BorderedLabel doesn't wrap well)
        album_lbl = QLabel(album_name)
        album_lbl.setAlignment(Qt.AlignCenter)
        album_lbl.setWordWrap(True)
        f = album_lbl.font(); f.setBold(True); f.setPointSize(10); album_lbl.setFont(f)
        
        artist_lbl = QLabel(artist_name)
        artist_lbl.setAlignment(Qt.AlignCenter)
        artist_lbl.setWordWrap(True)
        f2 = artist_lbl.font(); f2.setPointSize(8); artist_lbl.setFont(f2)
        
        # Apply Text Color
        # We manually set the stylesheet color for the artist to handle opacity
        artist_col = QColor(text_color)
        artist_col.setAlpha(180)
        
        album_lbl.setStyleSheet(f"color: {text_color.name()};")
        artist_lbl.setStyleSheet(f"color: rgba({artist_col.red()}, {artist_col.green()}, {artist_col.blue()}, {artist_col.alpha()/255:.2f});")

        # Emulate "Text Border" using Shadow (since we can't use BorderedLabel with wrapping easily)
        if text_border_enabled and saved_border_rgb:
             shadow = QGraphicsDropShadowEffect()
             shadow.setBlurRadius(0) # Hard shadow to look like a border
             shadow.setColor(QColor(*saved_border_rgb))
             shadow.setOffset(1, 1)
             album_lbl.setGraphicsEffect(shadow)

        layout.addWidget(album_lbl, 1)
        layout.addWidget(artist_lbl, 0)
        
        layout.addSpacing(6)
        
        # --- Action Buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0,0,0,0)
        btn_layout.setSpacing(5)
        
        export_btn = QPushButton("Export")
        export_btn.setCursor(Qt.PointingHandCursor)
        export_btn.clicked.connect(lambda: self.export_theme(album_id, data))
        
        import_btn = QPushButton("Import")
        import_btn.setCursor(Qt.PointingHandCursor)
        import_btn.clicked.connect(lambda: self.import_theme_to_card(album_id))
        
        del_btn = QPushButton("Delete")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.clicked.connect(lambda: self.confirm_delete_theme(album_id, album_name))
        
        btn_layout.addWidget(export_btn)
        btn_layout.addWidget(import_btn)
        btn_layout.addWidget(del_btn)
        
        layout.addLayout(btn_layout)
        
        return card

    # [ADD NEW METHODS to ColorEditorDialog]
    def confirm_delete_theme(self, album_id, album_name):
        msg = ThemedMessageBox("Confirm Delete", 
                               f"Are you sure you want to delete the saved theme for:\n\n<b>{album_name}</b>?", 
                               [("Yes", QDialog.Accepted), ("No", QDialog.Rejected)], 
                               self, self.ui_bg_color, self.ui_text_color, self.ui_accent_color, 
                               self.text_border_checkbox.isChecked(), self.text_border_color, self.text_border_size_slider.value())
        
        if msg.exec_() == QDialog.Accepted:
            self.delete_theme(album_id)

    # [UPDATE THIS METHOD]
    def export_theme(self, album_id, data):
        # Use the album name as the filename
        album_name = data.get("meta_album", "theme")
        safe_name = "".join(c for c in album_name if c.isalnum() or c in (' ', '-', '_')).strip()
        if not safe_name: safe_name = "theme"
        
        filename, _ = FramelessFileDialog(self, "Export Theme", f"{safe_name}.json", "JSON Files (*.json)",
                                          self.ui_bg_color, self.ui_accent_color, self.ui_text_color,
                                          self.text_border_checkbox.isChecked(), self.text_border_color, 
                                          self.text_border_size_slider.value()).getSaveFileName()
        
        if filename:
            try:
                # IMPORTANT: Inject the album_id so we can batch import later
                export_data = data.copy()
                export_data['_source_album_id'] = album_id
                
                with open(filename, 'w') as f:
                    json.dump(export_data, f, indent=4)
            except Exception as e:
                print(f"Export failed: {e}")

    def import_theme_to_card(self, target_album_id):
        filename, _ = FramelessFileDialog(self, "Import Theme", "", "JSON Files (*.json)",
                                          self.ui_bg_color, self.ui_accent_color, self.ui_text_color,
                                          self.text_border_checkbox.isChecked(), self.text_border_color, 
                                          self.text_border_size_slider.value()).getOpenFileName()
        
        if filename:
            try:
                with open(filename, 'r') as f:
                    data = json.load(f)
                
                self.color_cache.set_album_data(target_album_id, data)
                self.populate_theme_browser()
                
            except Exception as e:
                print(f"Import failed: {e}")

    # [ADD THIS NEW METHOD]
    def import_batch_themes(self):
        """Allows selecting multiple JSON files to import/update themes."""
        filenames, _ = FramelessFileDialog(self, "Batch Import Themes", "", "JSON Files (*.json)",
                                          self.ui_bg_color, self.ui_accent_color, self.ui_text_color,
                                          self.text_border_checkbox.isChecked(), self.text_border_color, 
                                          self.text_border_size_slider.value()).getOpenFileNames()
        
        if not filenames: return

        imported_count = 0
        skipped_count = 0
        
        for filename in filenames:
            try:
                with open(filename, 'r') as f:
                    data = json.load(f)
                
                # Check for the ID we saved during export
                target_id = data.get('_source_album_id')
                
                if target_id:
                    # Clean up the internal ID key before saving to cache (optional, but keeps cache clean)
                    # data.pop('_source_album_id', None) 
                    
                    # Update cache (Overwrite existing or create new)
                    self.color_cache.set_album_data(target_id, data)
                    imported_count += 1
                else:
                    print(f"Skipping {filename}: No '_source_album_id' found inside JSON.")
                    skipped_count += 1
                    
            except Exception as e:
                print(f"Failed to import {filename}: {e}")
                skipped_count += 1

        # Refresh the UI to show new cards
        self.populate_theme_browser()
        
        # Show summary
        summary = f"Imported: {imported_count}"
        if skipped_count > 0:
            summary += f"\nSkipped: {skipped_count} (Invalid format or missing ID)"
            
        ThemedMessageBox("Import Complete", summary, [("OK", QDialog.Accepted)], self, 
                         self.ui_bg_color, self.ui_text_color, self.ui_accent_color,
                         self.text_border_checkbox.isChecked(), self.text_border_color, 
                         self.text_border_size_slider.value()).exec_()

    # [ADD THIS NEW METHOD]
    def delete_theme(self, album_id):
        self.color_cache.set_album_data(album_id, None) # None deletes it
        self.populate_theme_browser()

    def load_track_state(self, album_id, track_id, album_art_pixmap, animate=True, album_name="", artist_name=""):
        self._auto_save_suspended = True
        self._loading_state = True
        
        # Block signals
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
            
            # Store Metadata
            self.current_album_name = album_name
            self.current_artist_name = artist_name
            
            # Reload cache data
            track_cache = self.color_cache.get_album_data(self.track_id) or {}
            cached_data = track_cache or self.color_cache.get_album_data(self.album_id) or {}
            if isinstance(cached_data, list): cached_data = {"ui_palette": cached_data}
            self.cached_data = cached_data

            # --- AUTO-UPDATE OLD SAVES ---
            # If we found data (it's a saved theme) BUT it's missing metadata, update it now.
            if self.cached_data and "meta_album" not in self.cached_data and self.current_album_name:
                print(f"Updating legacy save for {self.album_id} with metadata: {self.current_album_name}")
                self.cached_data['meta_album'] = self.current_album_name
                self.cached_data['meta_artist'] = self.current_artist_name
                self.color_cache.set_album_data(self.album_id, self.cached_data)
                self.populate_theme_browser()
            
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
            album_border_enabled = self.cached_data.get("album_art_border_enabled", True)
            self.album_art_border_checkbox.setChecked(album_border_enabled)
            self.initial_album_art_border_enabled = album_border_enabled
            self.title_gradient_checkbox.setChecked(bool(self.cached_data.get("title_gradient_enabled", False)))
            title_gradient_color_rgb = self.cached_data.get("title_gradient_color", [255, 255, 255])
            self.title_gradient_color = QColor(*title_gradient_color_rgb)
            self.title_grad_preview.setStyleSheet(
                f"background-color: {self.title_gradient_color.name()}; color: transparent; border-radius: 5px; border: 1px solid #555;"
            )
            self.title_gradient_dir_combo.setCurrentText(
                self._normalize_gradient_direction_label(self.cached_data.get("title_gradient_direction", "Left to Right"))
            )
            self.initial_title_gradient_enabled = self.title_gradient_checkbox.isChecked()
            self.initial_title_gradient_color = QColor(self.title_gradient_color)
            self.initial_title_gradient_direction = self.title_gradient_dir_combo.currentText()
            
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
            self.custom_art_scope = "track"
            if not self.custom_art_b64:
                self.custom_art_b64 = (self.color_cache.get_album_data(self.album_id) or {}).get("custom_art_b64")
                if self.custom_art_b64:
                    self.custom_art_scope = "album"

            if hasattr(self, "custom_art_track_radio") and hasattr(self, "custom_art_album_radio"):
                self.custom_art_track_radio.setChecked(self.custom_art_scope == "track")
                self.custom_art_album_radio.setChecked(self.custom_art_scope == "album")

            self.initial_custom_art_scope = self.custom_art_scope
            self._custom_art_changed = False
            
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
                self._auto_save_suspended = False
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
        self._refresh_save_buttons_for_current_tab()
        self._auto_save_suspended = False
        
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

            is_diff = False
            if type_cast == float:
                is_diff = abs(current_val - stored_val) > 0.001
            else:
                is_diff = current_val != stored_val

            if is_diff:
                changes.append({"key": key, "label": label, "value": current_val, "changed": True, "type": "global"})

        # Typography
        check("default_font_family", "App Default: Font Family", self.default_font_family_combo.currentText(), "Trebuchet MS")
        check("default_font_style", "App Default: Font Style", self.default_font_style_combo.currentText(), "Bold")
        check("default_font_size_scale", "App Default: Font Size", self.default_font_size_slider.value(), 100, int)
        check("default_progress_bar_enabled", "App Default: Show Progress Bar", self.default_progress_bar_checkbox.isChecked(), False, bool)
        check("default_text_border_enabled", "App Default: Show Text Outline", self.default_text_border_checkbox.isChecked(), False, bool)
        check("default_text_border_size", "App Default: Text Outline Size", self.default_text_border_size_slider.value(), 3, int)
        check("default_show_player_controls",   "App Default: Show Controls Bar",   self.default_show_player_controls_checkbox.isChecked(),   False, bool)
        check("default_controls_play_pause",    "App Default: Controls Play/Pause", self.default_controls_play_pause_checkbox.isChecked(),    True,  bool)
        check("default_controls_shuffle",       "App Default: Controls Shuffle",    self.default_controls_shuffle_checkbox.isChecked(),       True,  bool)
        check("default_controls_repeat",        "App Default: Controls Repeat",     self.default_controls_repeat_checkbox.isChecked(),        True,  bool)
        check("default_controls_add_playlist",  "App Default: Controls Add Playlist",self.default_controls_add_playlist_checkbox.isChecked(), True,  bool)
        check("default_controls_liked",         "App Default: Controls Liked",      self.default_controls_liked_checkbox.isChecked(),         True,  bool)

        # Notifications
        check("notification_enabled", "Notifications: Enabled", self.notification_enabled_checkbox.isChecked(), False, bool)
        check("notification_monitor_index", "Notifications: Display", self.notification_monitor_combo.currentIndex(), 0, int)
        check("notification_size", "Notifications: Size", self.notif_size_slider.value(), 1, int)
        check("notification_corner", "Notifications: Position", self.notification_corner_combo.currentText(), "Top-Right")
        check("notification_anim", "Notifications: Animation Style", self.notification_anim_combo.currentText(), "Fade")
        check("notification_dir", "Notifications: Slide Direction", self.notification_dir_combo.currentText(), "From Top")
        check("notification_permanent", "Notifications: Keep Visible for Full Song", self.notif_permanent_checkbox.isChecked(), False, bool)
        check("notification_duration", "Notifications: Visible Duration", self.notif_duration_slider.value(), 4000, int)
        check("notification_anim_duration", "Notifications: Transition Speed", self.notif_anim_speed_slider.value(), 500, int)
        check("notification_bg_opacity", "Notifications: Background Opacity", self.notif_opacity_slider.value(), 230, int)
        check("notification_border_enabled", "Notifications: Show Border", self.notif_border_checkbox.isChecked(), False, bool)
        check("notification_smart_hide", "Notifications: Smart Hide", self.notif_smart_hide_checkbox.isChecked(), False, bool)
        check("notification_ignore_taskbar", "Notifications: Ignore Taskbar", self.notif_ignore_taskbar_checkbox.isChecked(), True, bool)

        # Global Visuals
        check("default_govee_brightness", "Lights: Default Brightness", self.default_brightness_slider.value() / 100.0, 1.0, float)
        
        # --- NEW: Sound Volume Check ---
        check("sound_volume", "Sound: Effects Volume", self.sound_volume_slider.value() / 100.0, 0.5, float)
        check("minimize_to_notification_only", "Window: Minimize Behavior", self.minimize_mode_checkbox.isChecked(), True, bool)
        check("player_art_side", "Layout: Album Art Side", self.player_art_side_combo.currentText().strip().lower(), "left")

        current_shortcuts = self._normalize_shortcut_bindings(self.shortcut_bindings)
        raw_shortcuts = settings.value("keyboard_shortcuts", "")
        stored_shortcuts = {}
        if isinstance(raw_shortcuts, dict):
            stored_shortcuts = raw_shortcuts
        elif isinstance(raw_shortcuts, str) and raw_shortcuts.strip():
            try:
                parsed = json.loads(raw_shortcuts)
                if isinstance(parsed, dict):
                    stored_shortcuts = parsed
            except (json.JSONDecodeError, TypeError, ValueError):
                stored_shortcuts = {}

        stored_shortcuts = self._normalize_shortcut_bindings(stored_shortcuts)
        if current_shortcuts != stored_shortcuts:
            changes.append({
                "key": "keyboard_shortcuts",
                "label": "Keyboard: Shortcut Bindings",
                "value": current_shortcuts,
                "changed": True,
                "type": "global"
            })

        # --- NEW: Check Override ---
        check("govee_brightness_override", "Lights: Mobile App Brightness Control", self.govee_override_checkbox.isChecked(), False, bool)
        if self.spotify_method_checkbox is not None:
            check("spotify_method_enabled", "Media Methods: Spotify", self.spotify_method_checkbox.isChecked(), True, bool)
        if self.apple_music_method_checkbox is not None:
            check("apple_music_method_enabled", "Media Methods: Apple Music", self.apple_music_method_checkbox.isChecked(), True, bool)
        check("windows_media_method_enabled", "Media Methods: Windows Sessions", self.windows_media_method_checkbox.isChecked(), True, bool)

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
        current_primary = list(self.ui_bg_color.getRgb()[:3])
        initial_primary = list(self.initial_ui_bg_color.getRgb()[:3])
        check_auto(
            "ui_palette",
            "Track Theme: Core Colors",
            self.is_bg_auto and self.is_accent_auto,
            [current_primary, list(self.ui_accent_color.getRgb()[:3])],
            [initial_primary, list(self.initial_ui_accent_color.getRgb()[:3])],
        )
        check_auto("player_bg_color", "Track Theme: Player Background", self.is_bg_auto, list(self.ui_bg_color.getRgb()[:3]), list(self.initial_ui_bg_color.getRgb()[:3]))
        check_auto("blob_palette", "Track Theme: Blob Colors", self.is_blob_auto, [list(c.getRgb()[:3]) for c in self.blob_colors], [list(c.getRgb()[:3]) for c in self.initial_blob_colors])
        check_manual("shadow_enabled", "Track Theme: Text Shadow", self.shadow_checkbox.isChecked(), self.initial_shadow_enabled)
        check_manual("album_art_border_enabled", "Track Theme: Artwork Frame", self.album_art_border_checkbox.isChecked(), self.initial_album_art_border_enabled)
        check_manual("title_gradient_enabled", "Track Theme: Title Gradient", self.title_gradient_checkbox.isChecked(), self.initial_title_gradient_enabled)
        check_manual("title_gradient_color", "Track Theme: Title Gradient Color", list(self.title_gradient_color.getRgb()[:3]), list(self.initial_title_gradient_color.getRgb()[:3]))
        check_manual("title_gradient_direction", "Track Theme: Title Gradient Direction", self.title_gradient_dir_combo.currentText(), self.initial_title_gradient_direction)
        
        if self.override_font_checkbox.isChecked():
            check_manual("font_family", "Track Theme: Font Family", self.font_family_combo.currentText(), self.initial_font_family, always_save=True)
            check_manual("font_style", "Track Theme: Font Style", self.font_style_combo.currentText(), self.initial_font_style, always_save=True)
        else:
            if "font_family" in self.cached_data: potential_saves.append({"key": "font_family", "label": "Track Theme: Font Family (Reset)", "value": "__REMOVE__", "changed": True, "type": "theme"})
            if "font_style" in self.cached_data: potential_saves.append({"key": "font_style", "label": "Track Theme: Font Style (Reset)", "value": "__REMOVE__", "changed": True, "type": "theme"})
        
        t_case = self._get_selected_case(self.title_case_radios)
        if t_case != "default": check_manual("title_case", "Track Theme: Title Case", t_case, self.initial_title_case, always_save=True)
        elif "title_case" in self.cached_data: potential_saves.append({"key": "title_case", "label": "Track Theme: Title Case (Reset)", "value": "__REMOVE__", "changed": True, "type": "theme"})

        a_case = self._get_selected_case(self.artist_case_radios)
        if a_case != "default": check_manual("artist_case", "Track Theme: Artist Case", a_case, self.initial_artist_case, always_save=True)
        elif "artist_case" in self.cached_data: potential_saves.append({"key": "artist_case", "label": "Track Theme: Artist Case (Reset)", "value": "__REMOVE__", "changed": True, "type": "theme"})
        
        check_auto("text_border_enabled", "Track Theme: Text Outline", self.is_text_border_auto, self.text_border_checkbox.isChecked(), self.initial_text_border_enabled)
        check_auto("text_border_color", "Track Theme: Text Outline Color", self.is_text_border_color_auto, list(self.text_border_color.getRgb()[:3]), list(self.initial_text_border_color.getRgb()[:3]))
        
        if self.override_border_size_checkbox.isChecked():
            check_manual("text_border_size", "Track Theme: Text Outline Size", self.text_border_size_slider.value(), self.initial_text_border_size, always_save=True)
        elif "text_border_size" in self.cached_data:
            potential_saves.append({"key": "text_border_size", "label": "Track Theme: Text Outline Size (Reset)", "value": "__REMOVE__", "changed": True, "type": "theme"})
            
        current_lights_palette = [list(p["color"].getRgb()[:3]) for p in self.govee_color_pickers]
        initial_lights_palette_list = [list(c.getRgb()[:3]) for c in self.effective_initial_lights_palette]
        check_auto("lights_config", "Track Theme: Light Colors", self.is_lights_auto, {"mode": "custom", "palette": current_lights_palette}, {"mode": "custom", "palette": initial_lights_palette_list})

        if self.override_progress_bar_checkbox.isChecked():
            check_manual("progress_bar_enabled", "Track Theme: Show Progress Bar", self.progress_bar_checkbox.isChecked(), self.initial_progress_bar_enabled, always_save=True)
        elif "progress_bar_enabled" in self.cached_data:
            potential_saves.append({"key": "progress_bar_enabled", "label": "Track Theme: Progress Bar (Reset)", "value": "__REMOVE__", "changed": True, "type": "theme"})

        if self.override_size_checkbox.isChecked():
            check_manual("font_size_scale", "Track Theme: Font Size", self.font_size_slider.value(), self.initial_font_size_scale, always_save=True)
        elif "font_size_scale" in self.cached_data:
            potential_saves.append({"key": "font_size_scale", "label": "Track Theme: Font Size (Reset)", "value": "__REMOVE__", "changed": True, "type": "theme"})

        current_val = self.govee_brightness_slider.value() / 100.0 if self.override_brightness_checkbox.isChecked() else None
        initial_val = self.initial_track_brightness / 100.0 if self.initial_is_brightness_overridden else None
        if current_val != initial_val:
            check_manual("govee_brightness", "Track Theme: Light Brightness", current_val, initial_val, always_save=True)

        check_auto("text_color", "Track Theme: Text Color", self.is_text_color_auto, list(self.ui_text_color.getRgb()[:3]), list(self.initial_ui_text_color.getRgb()[:3]))

        if self._custom_art_changed or (self._active_custom_art_scope() != self.initial_custom_art_scope):
            potential_saves.append({
                "key": "custom_art_scope",
                "label": "Track Theme: Custom Artwork",
                "value": "__CUSTOM_ART__",
                "changed": True,
                "type": "theme"
            })

        return potential_saves
    
    def _populate_govee_table(self):
        self.govee_device_table.setRowCount(len(self.initial_govee_devices))
        for row, device_config in enumerate(self.initial_govee_devices):
            chk_box_item = QTableWidgetItem(); chk_box_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled); chk_box_item.setCheckState(Qt.Checked)
            self.govee_device_table.setItem(row, 0, chk_box_item)
            self.govee_device_table.setItem(row, 1, QTableWidgetItem(device_config.get("device", ""))); self.govee_device_table.setItem(row, 2, QTableWidgetItem(device_config.get("model", ""))); self.govee_device_table.setItem(row, 3, QTableWidgetItem(device_config.get("name", "")))
        self.govee_device_table.resizeColumnsToContents()

    def save_full_theme(self):
        """Snapshots the exact current state of the panel and saves it as the theme."""
        self._is_closing_via_save = True
        album_config = self._build_full_theme_snapshot()

        # 8. Save to Cache
        self.color_cache.set_album_data(self.album_id, album_config)
        
        # 9. Handle Custom Art (scope-aware)
        needs_art_reload = self._custom_art_changed or (self._active_custom_art_scope() != self.initial_custom_art_scope)
        self._persist_custom_art()

        # 10. Apply Immediate Side Effects (Blob Density)
        slider_value = self.blob_amount_slider.value()
        if self.parent():
            self.parent().blob_density = 400000 / slider_value if slider_value > 0 else 200000

        # 11. Notify & Refresh
        emit_config = dict(album_config)
        if needs_art_reload:
            emit_config["_reload_art"] = True
            self.initial_custom_art_scope = self._active_custom_art_scope()
            self._custom_art_changed = False
        self.config_saved.emit(self.album_id, emit_config)
        self.populate_theme_browser()
            
        # Close the dialog to indicate success
        self.accept()

    def save_and_close(self, quick=False):
        self._is_closing_via_save = True
        global_changes, theme_changes = self._collect_pending_changes()
        all_changes = global_changes + theme_changes

        keys_to_save = []
        if quick:
            keys_to_save = [item['key'] for item in all_changes if item['changed']]
        else:
            if not all_changes:
                self.accept()
                return
            dialog = SaveConfirmationDialog(all_changes, self.ui_bg_color, self.ui_accent_color, self.ui_text_color, self)
            if dialog.exec_() == QDialog.Accepted:
                keys_to_save = dialog.selected_keys
            else:
                return

        self._persist_selected_changes(keys_to_save, global_changes, theme_changes, quick=quick, close_after=True, allow_restart_prompt=True)

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
            self.apple_music_team_id_input.setEchoMode(QLineEdit.Normal)
            self.apple_music_key_id_input.setEchoMode(QLineEdit.Normal)
            self.apple_music_private_key_input.setEchoMode(QLineEdit.Normal)
            self.apple_music_user_token_input.setEchoMode(QLineEdit.Normal)
            button.setText("Hide Secrets")
        else:
            self.spotify_id_input.setEchoMode(QLineEdit.Password)
            self.spotify_secret_input.setEchoMode(QLineEdit.Password)
            self.govee_key_input.setEchoMode(QLineEdit.Password)
            self.apple_music_team_id_input.setEchoMode(QLineEdit.Password)
            self.apple_music_key_id_input.setEchoMode(QLineEdit.Password)
            self.apple_music_private_key_input.setEchoMode(QLineEdit.Password)
            self.apple_music_user_token_input.setEchoMode(QLineEdit.Password)
            button.setText("Show Secrets")

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

    def confirm_reset_app(self):
        """Show initial reset dialog with 3 options."""
        reset_msg = "What would you like to do?"
        msg = ThemedMessageBox(
            "Reset Player?",
            reset_msg,
            [
                ("Yes, but keep my data", 1),
                ("Yes, and erase my data", 2),
                ("Cancel", QDialog.Rejected)
            ],
            self,
            self.ui_bg_color,
            self.ui_text_color,
            self.ui_accent_color,
            self.text_border_checkbox.isChecked(),
            self.text_border_color,
            self.text_border_size_slider.value()
        )
        
        result = msg.exec_()
        if result == 1:
            self._confirm_reset_keep_data()
        elif result == 2:
            self._confirm_reset_erase_data()

    def _confirm_reset_keep_data(self):
        """Show confirmation dialog for reset with data kept."""
        confirm_msg = (
            "The app will close and restart, showing you the first-time setup dialogs.\n\n"
            "Your saved album themes and customizations will be preserved.\n\n"
            "You will be prompted to set up Spotify credentials again.\n\n"
            "Continue?"
        )
        msg = ThemedMessageBox(
            "Confirm Reset",
            confirm_msg,
            [("Yes", QDialog.Accepted), ("No", QDialog.Rejected)],
            self,
            self.ui_bg_color,
            self.ui_text_color,
            self.ui_accent_color,
            self.text_border_checkbox.isChecked(),
            self.text_border_color,
            self.text_border_size_slider.value()
        )
        
        if msg.exec_() == QDialog.Accepted:
            self._restart_app(erase_data=False)

    def _confirm_reset_erase_data(self):
        """Show confirmation dialog for reset with data erased."""
        confirm_msg = (
            "WARNING: This will erase ALL app data including:\n"
            "- Saved credentials (Spotify, Govee)\n"
            "- All album themes and customizations\n"
            "- All cache and settings\n\n"
            "The app will restart as if it's running for the first time.\n"
            "This action cannot be undone.\n\n"
            "Continue?"
        )
        msg = ThemedMessageBox(
            "Confirm Full Reset",
            confirm_msg,
            [("Yes", QDialog.Accepted), ("No", QDialog.Rejected)],
            self,
            self.ui_bg_color,
            self.ui_text_color,
            self.ui_accent_color,
            self.text_border_checkbox.isChecked(),
            self.text_border_color,
            self.text_border_size_slider.value()
        )
        
        if msg.exec_() == QDialog.Accepted:
            self._restart_app(erase_data=True)

    def _restart_app(self, erase_data=False):
        """Restart the application, optionally clearing all data.
        
        If erase_data is False: Closes and restarts the app showing first-time setup dialogs,
                                but keeps saved themes, playlists, and other user data.
                                Saved credentials are preserved and pre-filled in setup dialogs.
        If erase_data is True: Clears everything and restarts as if app never ran before.
        """
        import sys
        
        settings = QSettings("SpotifySync", "App")
        
        if erase_data:
            # Clear ALL settings when erasing data
            settings.clear()
            settings.sync()
            # Also clear the color cache
            if hasattr(self, 'color_cache'):
                self.color_cache.clear()
        else:
            # Keep data mode: Preserve credentials but force re-setup dialogs
            # Keep spotify credentials - they will be pre-filled in the setup dialog
            # Just set a flag to force the Spotify setup dialog to show
            settings.setValue("force_spotify_setup", "true")
            # This shows the welcome dialog
            settings.setValue("first_run", "true")
            settings.sync()
        
        # Close the settings dialog and main window to fully release resources
        self.close()
        
        # Close the main window first and wait a bit for proper cleanup
        QApplication.instance().processEvents()
        
        # Give the application a moment to fully clean up before restarting
        QTimer.singleShot(500, lambda: self._do_restart())
    
    def _do_restart(self):
        """Actually restart the application after cleanup."""
        import sys
        
        # Start a new instance of the application
        QProcess.startDetached(sys.executable, sys.argv)
        
        # Now quit the current application
        QApplication.instance().quit()