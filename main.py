# main.py
import sys
import os
import json
import io
import multiprocessing
from PIL import Image

# --- FIXED IMPORTS ---
# QRectF, QPropertyAnimation, and QVariantAnimation moved to QtCore
from PyQt5.QtCore import (
    Qt, QTimer, QThreadPool, QSettings, QRect, QDateTime, pyqtSlot, QProcess, 
    pyqtProperty, QEasingCurve, QParallelAnimationGroup, QSequentialAnimationGroup,
    QAbstractAnimation, QPoint, QRectF, QPropertyAnimation, QVariantAnimation
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QBoxLayout, QVBoxLayout, 
    QGraphicsDropShadowEffect, QSizePolicy, QSystemTrayIcon, QMenu, QDialog
)
from PyQt5.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPixmap
)

from spotipy import Spotify, SpotifyOAuth

from config import SPOTIPY_REDIRECT_URI, SPOTIFY_SCOPE, SPOTIFY_GREEN
from utils import resource_path
from services import ColorCache, GoveeController
from workers import SpotifyPollingWorker, WindowsMediaWorker, TrackLoaderWorker, FontLoaderWorker, GoveeWorker, IS_WINDOWS
from ui.widgets import ResponsiveAlbumArtLabel, ScrollingTextLabel, SmoothProgressBar, BlobManager, BorderedLabel
from utils import get_best_text_color, get_best_border_color
from ui.overlays import OverlayWidget, NotificationWidget
from ui.dialogs import ColorEditorDialog, SpotifySetupDialog, ThemedMessageBox

class SpotifyPlayer(QMainWindow):
    artOpacity = pyqtProperty(float, fget=lambda self: self.art._opacity if hasattr(self, 'art') else 1.0, fset=lambda self, o: self.art.setOpacity(o) if hasattr(self, 'art') else None)
    textAlpha = pyqtProperty(float, fget=lambda self: self._text_alpha, fset=lambda self, a: self.setTextAlpha(a))
    bgCrossfadeLerp = pyqtProperty(float, fget=lambda self: self._bg_crossfade_lerp, fset=lambda self, v: self.setBgCrossfadeLerp(v))

    def __init__(self):
        super().__init__()
        self.setWindowOpacity(0.0)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._prev_track_data = None
        self._last_spotify_track_data = None
        self._pending_track_data = None
        self._is_paused = False
        self.is_fullscreen = True
        self.is_wallpaper_mode = False
        self.threadpool = QThreadPool()
        self.font_styles_cache = {}
        self.base_font_families = []
        self._fonts_loaded = False
        self.active_media_source = None # 'spotify' or 'windows'
        self.spotify_worker = None
        self.windows_worker = None
        self._current_track_id = None
        self.load_token = 0
        self._current_pil_img = None
        self._current_bg_color = QColor("black")
        self._current_album_id = None
        self._old_bg_color = QColor("black")
        self._current_palette = []
        self._current_ui_palette = [] 
        self._current_lights_palette = [] 
        self._current_blob_palette = [] 
        self._current_shadow_enabled = True
        self._current_font_family = "Trebuchet MS"
        self._current_font_style = "Bold"
        self._current_font_size_scale = 100
        self._current_title_case = "default"
        self._current_artist_case = "default"
        self._current_text_border_enabled = False
        self._current_text_border_color = [0, 0, 0]
        self._current_text_color = [255, 255, 255]
        self._current_progress_bar_enabled = False
        self._current_text_border_size = 3
        self._current_track_duration = 0
        self._last_progress_sync_time = 0
        self._last_progress_val = 0
        self._idle_pixmap = None
        self._idle_pil_img = None
        self._bg_crossfade_lerp = 0.0
        self.blob_density = 200000 # Default, will be loaded from settings
        self.blob_manager = None
        self.notification_only_mode = False
        self.recent_colors = []
        self.drag_pos = None

        self.multi_monitor_mode = False
        self.target_monitor_geo = None
        self.total_screens_geo = None
        self.tray_icon = None

        self.NORMAL_MARGINS = (40, 40, 40, 40) 
        self.VERTICAL_ORIENTATION_MARGINS = (80, 80, 80, 80) 
        self._cur_text_color = QColor(255, 255, 255)
        self._text_alpha = 255
        self.govee_brightness = 1.0
        self.default_govee_brightness = 1.0
        self.lights_enabled = True
        self._last_sent_lights_config = None
        
        self.settings_dialog = None
        self.NORMAL_POLL_INTERVAL = 1000
        self.IDLE_POLL_INTERVAL = 3000
        
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.setInterval(300000) # 5 minutes
        self.idle_timer.timeout.connect(self._on_idle_timeout)

        # Default font properties, will be loaded from settings
        self.default_font_family = "Trebuchet MS"
        self.default_font_style = "Bold"
        self.default_font_size_scale = 100
        self.default_progress_bar_enabled = False
        self.default_text_border_enabled = False
        self.default_auto_border_enabled = False
        self.default_text_border_size = 3

        self.container = None
        self.main_layout = None
        self.art_container = None
        self.art = None
        self.details_widget = None
        self.title = None
        self.artist = None
        self.progress_bar = None
        self.album_name = None # New: Album name label
        self.art_shadow = None
        self.title_shadow = None
        self.artist_shadow = None

        self.notification_widget = NotificationWidget()
        self.notification_widget.clicked.connect(self._on_notification_clicked)
        
        self.error_notification_widget = NotificationWidget()
        self.error_notification_widget.clicked.connect(self._on_error_notification_clicked)

        try:
            self._idle_pil_img = Image.open(resource_path('icon.ico'))
        except Exception:
            # Fallback if icon is missing or invalid
            self._idle_pil_img = Image.new("RGB", (256, 256), "black")

        did_show_setup = self._setup_spotify()
        self._load_govee_settings() 
        self.color_cache = ColorCache()
        self._govee = GoveeController(self.govee_api_key, self.govee_devices)
        self._load_settings()

        if not did_show_setup:
            self._check_for_first_run()

        self._setup_ui()
        self._setup_animations()
        self._setup_tray_icon()
        self._setup_timers()
        # Pre-load the settings dialog slowly in the background after a short delay
        QTimer.singleShot(2500, self._setup_settings_dialog)
        self._load_fonts()

        self.overlay = OverlayWidget(self.container)
        self.overlay.hide()
        self.overlay.settings_button.clicked.connect(self.open_settings_dialog)
        self.overlay.lights_button.clicked.connect(self.toggle_lights)
        self.overlay.multi_monitor_button.clicked.connect(self.toggle_multi_monitor_fullscreen)
        self.overlay.wallpaper_button.clicked.connect(self.toggle_wallpaper_mode)
        self.overlay.notif_mode_button.clicked.connect(self.toggle_notification_only_mode)

        # Show an initial idle screen.
        QTimer.singleShot(100, self._show_idle_screen)

    def _check_for_first_run(self):
        """Shows a welcome message with instructions on the first launch."""
        settings = QSettings("SpotifySync", "App")
        if settings.value("first_run", "true") == "true":
            tutorial_text = """
            <h2>Welcome to Spotify Sync!</h2>
            <p>Here are some quick tips to get you started:</p>
            <ul>
                <li><b>Play Music:</b> Start playing a song on any Spotify-connected device. The display will update automatically.</li>
                <li><b>Settings:</b> Press the <b>C</b> key to open the settings panel. Here you can customize colors, fonts, and more for the current album.</li>
                <li><b>Fullscreen:</b> Press <b>F</b> to toggle fullscreen mode.</li>
                <li><b>Multi-Monitor:</b> Press <b>F11</b> to span across all your monitors. Use the <b>&larr;</b> and <b>&rarr;</b> arrow keys to shift the content between screens.</li>
                <li><b>Wallpaper Mode:</b> Press <b>F12</b> to enter a 'wallpaper' mode that sits behind your desktop icons. A tray icon will appear to let you exit this mode or open settings.</li>
                <li><b>Exit:</b> Press <b>Esc</b> to close the application.</li>
            </ul>
            <p>Enjoy the vibes!</p>
            """
            ThemedMessageBox("Welcome!", tutorial_text, [("Let's Go!", QDialog.Accepted)], self, self._current_bg_color, self._current_text_color, QColor(100, 100, 100), self._current_text_border_enabled, QColor(*self._current_text_border_color), self._current_text_border_size).exec_()
            settings.setValue("first_run", False)

    def _show_idle_screen(self):
        """Displays a default idle screen when no music is playing."""
        if self._prev_track_data: # Don't show if a track was just playing and we are fading out
            return

        self._current_ui_palette = [[0, 0, 0], [255, 255, 255]]
        self.art.setAspectRatio(1.0)
        if self._idle_pil_img:
            self._set_album_art(self._idle_pil_img)
        self.art.setBorderColor(QColor("transparent"))
        self.art.setLoadingState(False)

        self.title.setText("Spotify Sync")
        self.artist.setText("Play music on any device to begin")
        self.album_name.setText("Press 'C' for settings & controls")
        self._current_text_color = [200, 200, 200]

        self.textAlpha = 255
        self._update_text_properties()
        self.text_color_anim.setStartValue(self._cur_text_color)
        self.text_color_anim.setEndValue(QColor(200, 200, 200))
        self.text_color_anim.start()

        self._old_bg_color = self._current_bg_color
        self._current_bg_color = QColor("black")
        self.bg_fade_anim.setStartValue(self._bg_crossfade_lerp)
        self.bg_fade_anim.setEndValue(1.0)
        self.bg_fade_anim.start()

        self.fade_in_group.start()
        self.update_layout()

    def _load_govee_settings(self):
        settings = QSettings("SpotifySync", "App")
        self.govee_api_key = settings.value("govee_api_key", "")
        self.govee_devices = json.loads(settings.value("govee_devices", "[]"))

    def _setup_spotify(self):
        settings = QSettings("SpotifySync", "App")
        did_show_setup_dialog = False
        
        while True:
            client_id = settings.value("spotify_client_id")
            client_secret = settings.value("spotify_client_secret")

            if not client_id or not client_secret:
                did_show_setup_dialog = True
                dialog = SpotifySetupDialog()
                if dialog.exec_() != QDialog.Accepted:
                    sys.exit(0) # User cancelled, exit app
                continue # Loop again to load the new settings

            try:
                auth_manager = SpotifyOAuth(
                    client_id=client_id, 
                    client_secret=client_secret, 
                    redirect_uri=SPOTIPY_REDIRECT_URI, 
                    scope=SPOTIFY_SCOPE, 
                    open_browser=True
                )
                self.sp = Spotify(auth_manager=auth_manager)
                # A simple call to check if auth works. This will trigger browser auth if no token.
                self.sp.me() 
                break # Success, exit loop
            except Exception as e:
                print(f"Failed to initialize Spotify. Please check credentials. Error: {e}")
                
                # Show an error message to the user but don't auto-clear credentials (could be network issue)
                msg = ThemedMessageBox("Authentication Error",
                    f"Spotify Authentication Failed.\n\nError: {e}\n\n"
                    "Do you want to reset your saved Client ID and Secret?\n"
                    "(Yes to reset, No to retry, Cancel to exit)",
                    [("Yes", QDialog.Accepted), ("No", QDialog.Rejected), ("Cancel", 2)], self, self._current_bg_color, self._current_text_color, QColor(100, 100, 100), self._current_text_border_enabled, QColor(*self._current_text_border_color), self._current_text_border_size)

                res = msg.exec_()
                if res == QDialog.Accepted:
                    settings.remove("spotify_client_id")
                    settings.remove("spotify_client_secret")
                elif res == 2:
                    sys.exit(0)
        return did_show_setup_dialog

    def _load_settings(self):
        settings = QSettings("SpotifySync", "App")
        
        # Load base geometry and state that will be used to show the window initially
        geometry = settings.value("geometry", QRect(100, 100, 600, 700)) 
        if not isinstance(geometry, QRect): geometry = QRect(100, 100, 600, 700)
        
        self.is_fullscreen = settings.value("fullscreen", "true") == "true"
        self.multi_monitor_mode = settings.value("multi_monitor_mode", "false") == "true"
        self._start_in_wallpaper = settings.value("start_in_wallpaper_mode", "false") == "true"
        
        self.lights_enabled = settings.value("lights_enabled", "true") == "true"
        val = settings.value("default_govee_brightness")
        if val is not None:
            self.default_govee_brightness = float(val)
        else:
            self.default_govee_brightness = float(settings.value("govee_brightness", 1.0))
        self.blob_density = int(float(settings.value("blob_density", 200000)))
        if not isinstance(geometry, QRect): 
             geometry = QRect(100, 100, 600, 700)
        self.setGeometry(geometry)

        # Load default font styles
        self.default_font_family = settings.value("default_font_family", "Trebuchet MS")
        self.default_font_style = settings.value("default_font_style", "Bold")
        self.default_font_size_scale = int(settings.value("default_font_size_scale", 100))
        self.default_progress_bar_enabled = settings.value("default_progress_bar_enabled", "false") == "true"
        self.default_text_border_enabled = settings.value("default_text_border_enabled", "false") == "true"
        self.default_text_border_size = int(settings.value("default_text_border_size", 3))

        # Load recent colors
        recent_colors_str = settings.value("recent_colors", "[]")
        try:
            # Stored as hex strings
            self.recent_colors = [QColor(name) for name in json.loads(recent_colors_str)]
        except (json.JSONDecodeError, TypeError):
            self.recent_colors = []

        # Set initial geometry and flags based on loaded state
        if self.multi_monitor_mode:
            target_geo = settings.value("target_monitor_geo")
            if isinstance(target_geo, QRect):
                self.target_monitor_geo = target_geo
                screens = QApplication.screens()
                if screens:
                    total_rect = QRect()
                    for screen in screens: total_rect = total_rect.united(screen.geometry())
                    self.total_screens_geo = total_rect
                    self.setWindowFlags(Qt.FramelessWindowHint)
                    self.setGeometry(total_rect)
            else: # Invalid multi-monitor data, fallback
                self.multi_monitor_mode = False
                self.setWindowFlags(Qt.FramelessWindowHint)
                self.setGeometry(geometry)
        else:
            self.setGeometry(geometry)

    def _save_settings(self):
        settings = QSettings("SpotifySync", "App")
        settings.setValue("geometry", self.geometry())
        settings.setValue("fullscreen", "true" if self.is_fullscreen else "false")
        settings.setValue("lights_enabled", "true" if self.lights_enabled else "false")
        settings.setValue("default_govee_brightness", self.default_govee_brightness)
        settings.setValue("blob_density", self.blob_density)
        settings.setValue("start_in_wallpaper_mode", "true" if self.is_wallpaper_mode else "false")

        if self.is_wallpaper_mode:
            # If in wallpaper mode, save the state we would revert to
            settings.setValue("geometry", self._saved_geometry)
            settings.setValue("fullscreen", "true" if self._was_fullscreen else "false")
            settings.setValue("multi_monitor_mode", "true" if self._was_multi_monitor else "false")
            if self._was_multi_monitor:
                settings.setValue("target_monitor_geo", self._saved_target_monitor_geo)
        else:
            # Otherwise, save the current state
            settings.setValue("geometry", self.geometry())
            settings.setValue("fullscreen", "true" if self.is_fullscreen else "false")
            settings.setValue("multi_monitor_mode", "true" if self.multi_monitor_mode else "false")
            if self.multi_monitor_mode:
                settings.setValue("target_monitor_geo", self.target_monitor_geo)

        # Save recent colors
        recent_colors_names = [c.name(QColor.HexRgb) for c in self.recent_colors]
        settings.setValue("recent_colors", json.dumps(recent_colors_names))

    def _setup_ui(self):
        self.setWindowTitle("Spotify Sync")
        self.setWindowIcon(QIcon(resource_path('icon.ico')))
        self.setMinimumSize(400, 500)
        
        self.container = QWidget(self)
        self.container.setStyleSheet("background-color: transparent;")
        self.setCentralWidget(self.container)
        
        self.main_layout = QBoxLayout(QBoxLayout.TopToBottom)
        self.main_layout.setSpacing(20)
        self.container.setLayout(self.main_layout)

        self.art_container = QWidget()
        self.art_container.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        art_container_layout = QVBoxLayout(self.art_container)
        art_container_layout.setContentsMargins(0,0,0,0)
        
        self.title_shadow = QGraphicsDropShadowEffect(self)
        self.artist_shadow = QGraphicsDropShadowEffect(self)

        self.art = ResponsiveAlbumArtLabel(radius=15)

        self.details_widget = QWidget()
        details_layout = QVBoxLayout(self.details_widget)
        details_layout.setSpacing(15)
        details_layout.setContentsMargins(20, 0, 20, 0)
        
        font_family = "Trebuchet MS" if "Trebuchet MS" in QFontDatabase().families() else "Sans Serif"
        self.title = ScrollingTextLabel("–")
        self.title.setFont(QFont(font_family, 23, QFont.Bold))
        self.title.setGraphicsEffect(self.title_shadow) 
        self.title.setStyleSheet("background: transparent;") # Ensure background is transparent

        self.album_name = ScrollingTextLabel("–") # New album name label
        self.album_name.setFont(QFont(font_family, 16)) # Smaller than title, slightly smaller than artist
        self.album_name.setGraphicsEffect(QGraphicsDropShadowEffect(self)) # Add shadow effect
        self.album_name.setStyleSheet("background: transparent;") # Ensure background is transparent
        
        self.artist = ScrollingTextLabel("–")
        self.artist.setFont(QFont(font_family, 18))
        self.artist.setGraphicsEffect(self.artist_shadow) 
        self.artist.setStyleSheet("background: transparent;") # Ensure background is transparent

        self.progress_bar = SmoothProgressBar()

        details_layout.addWidget(self.title)
        details_layout.addWidget(self.artist)

        art_container_layout.addWidget(self.art)

        self.main_layout.addStretch(1)
        details_layout.insertWidget(1, self.album_name) # Insert album name between title and artist
        details_layout.addWidget(self.progress_bar)
        self.main_layout.addWidget(self.art_container, 5)
        self.main_layout.addWidget(self.details_widget, 2, Qt.AlignCenter)
        self.main_layout.addStretch(1)

        self.title.setAlignment(Qt.AlignCenter)
        self.artist.setAlignment(Qt.AlignCenter)
        details_layout.setAlignment(Qt.AlignCenter)
        
        self.update_art_shadow_properties()
        self.setTextAlpha(self._text_alpha)

    def _setup_animations(self):
        EASING_CURVE = QEasingCurve.InOutCubic
        EASING_IN = QEasingCurve.InCubic
        EASING_OUT = QEasingCurve.OutCubic
        self.fade_in_group = QParallelAnimationGroup(self)
        self.fade_out_group = QParallelAnimationGroup(self)
        
        # Art Opacity Animations
        art_anim_in = QPropertyAnimation(self, b"artOpacity"); art_anim_in.setDuration(800); art_anim_in.setEndValue(1.0); art_anim_in.setEasingCurve(EASING_CURVE)
        art_anim_out = QPropertyAnimation(self, b"artOpacity"); art_anim_out.setDuration(800); art_anim_out.setEndValue(0.0); art_anim_out.setEasingCurve(EASING_CURVE)
        art_anim_in = QPropertyAnimation(self, b"artOpacity"); art_anim_in.setDuration(800); art_anim_in.setEndValue(1.0); art_anim_in.setEasingCurve(EASING_IN)
        art_anim_out = QPropertyAnimation(self, b"artOpacity"); art_anim_out.setDuration(800); art_anim_out.setEndValue(0.0); art_anim_out.setEasingCurve(EASING_OUT)
        art_anim_in = QPropertyAnimation(self, b"artOpacity"); art_anim_in.setDuration(800); art_anim_in.setEndValue(1.0); art_anim_in.setEasingCurve(EASING_OUT)
        art_anim_out = QPropertyAnimation(self, b"artOpacity"); art_anim_out.setDuration(800); art_anim_out.setEndValue(0.0); art_anim_out.setEasingCurve(EASING_IN)
        self.fade_in_group.addAnimation(art_anim_in)
        self.fade_out_group.addAnimation(art_anim_out)

        # Staggered Text Entrance
        def add_staggered_anim(target, delay):
            # Opacity
            op_anim = QPropertyAnimation(target, b"opacity"); op_anim.setDuration(800); op_anim.setStartValue(0.0); op_anim.setEndValue(1.0); op_anim.setEasingCurve(QEasingCurve.OutCubic)
            op_anim = QPropertyAnimation(target, b"opacity"); op_anim.setDuration(800); op_anim.setStartValue(0.0); op_anim.setEndValue(1.0); op_anim.setEasingCurve(EASING_IN)
            op_anim = QPropertyAnimation(target, b"opacity"); op_anim.setDuration(800); op_anim.setStartValue(0.0); op_anim.setEndValue(1.0); op_anim.setEasingCurve(EASING_OUT)
            # Slide In (From Left)
            slide_anim = QPropertyAnimation(target, b"anim_offset_x"); slide_anim.setDuration(800); slide_anim.setStartValue(-40.0); slide_anim.setEndValue(0.0); slide_anim.setEasingCurve(QEasingCurve.OutCubic)
            slide_anim = QPropertyAnimation(target, b"anim_offset_x"); slide_anim.setDuration(800); slide_anim.setStartValue(-40.0); slide_anim.setEndValue(0.0); slide_anim.setEasingCurve(EASING_IN)
            slide_anim = QPropertyAnimation(target, b"anim_offset_x"); slide_anim.setDuration(800); slide_anim.setStartValue(-40.0); slide_anim.setEndValue(0.0); slide_anim.setEasingCurve(EASING_OUT)
            
            if delay > 0:
                seq_op = QSequentialAnimationGroup(); seq_op.addPause(delay); seq_op.addAnimation(op_anim); self.fade_in_group.addAnimation(seq_op)
                seq_slide = QSequentialAnimationGroup(); seq_slide.addPause(delay); seq_slide.addAnimation(slide_anim); self.fade_in_group.addAnimation(seq_slide)
            else:
                self.fade_in_group.addAnimation(op_anim); self.fade_in_group.addAnimation(slide_anim)

        add_staggered_anim(self.title, 0)
        add_staggered_anim(self.album_name, 100)
        add_staggered_anim(self.artist, 200)

        # Text Exit (Slide Out)
        def add_exit_anim(target, delay):
            slide_out = QPropertyAnimation(target, b"anim_offset_x")
            slide_out.setDuration(800)
            slide_out.setStartValue(0.0)
            slide_out.setEndValue(-40.0)
            slide_out.setEasingCurve(EASING_CURVE)
            slide_out.setEasingCurve(EASING_OUT)
            slide_out.setEasingCurve(EASING_IN)

            op_out = QPropertyAnimation(target, b"opacity")
            op_out.setDuration(800)
            op_out.setStartValue(1.0)
            op_out.setEndValue(0.0)
            op_out.setEasingCurve(EASING_CURVE)
            op_out.setEasingCurve(EASING_OUT)
            op_out.setEasingCurve(EASING_IN)

            if delay > 0:
                seq_slide = QSequentialAnimationGroup()
                seq_slide.addPause(delay)
                seq_slide.addAnimation(slide_out)
                self.fade_out_group.addAnimation(seq_slide)

                seq_op = QSequentialAnimationGroup()
                seq_op.addPause(delay)
                seq_op.addAnimation(op_out)
                self.fade_out_group.addAnimation(seq_op)
            else:
                self.fade_out_group.addAnimation(slide_out)
                self.fade_out_group.addAnimation(op_out)

        add_exit_anim(self.title, 0)
        add_exit_anim(self.album_name, 100)
        add_exit_anim(self.artist, 200)
        
        self.fade_out_group.finished.connect(self._on_fade_out_finished); self.text_color_anim = QVariantAnimation(self); self.text_color_anim.setDuration(1200); self.text_color_anim.setEasingCurve(EASING_CURVE); self.text_color_anim.valueChanged.connect(self.setTextColor)
        self.bg_fade_anim = QPropertyAnimation(self, b"bgCrossfadeLerp"); self.bg_fade_anim.setDuration(1200); self.bg_fade_anim.setEasingCurve(EASING_CURVE)
        self.fade_out_group.finished.connect(self._on_fade_out_finished); self.text_color_anim = QVariantAnimation(self); self.text_color_anim.setDuration(1200); self.text_color_anim.setEasingCurve(EASING_IN); self.text_color_anim.valueChanged.connect(self.setTextColor)
        self.bg_fade_anim = QPropertyAnimation(self, b"bgCrossfadeLerp"); self.bg_fade_anim.setDuration(1200); self.bg_fade_anim.setEasingCurve(EASING_IN)
        self.fade_out_group.finished.connect(self._on_fade_out_finished); self.text_color_anim = QVariantAnimation(self); self.text_color_anim.setDuration(1200); self.text_color_anim.setEasingCurve(EASING_OUT); self.text_color_anim.valueChanged.connect(self.setTextColor)
        self.bg_fade_anim = QPropertyAnimation(self, b"bgCrossfadeLerp"); self.bg_fade_anim.setDuration(1200); self.bg_fade_anim.setEasingCurve(EASING_OUT)

        bg_fade_out_anim = QPropertyAnimation(self, b"bgCrossfadeLerp")
        bg_fade_out_anim.setDuration(800)
        bg_fade_out_anim.setEndValue(0.0)
        bg_fade_out_anim.setEasingCurve(EASING_CURVE)
        bg_fade_out_anim.setEasingCurve(EASING_OUT)
        bg_fade_out_anim.setEasingCurve(EASING_IN)
        self.fade_out_group.addAnimation(bg_fade_out_anim)
        self.art_scale_anim = QPropertyAnimation(self.art, b"scale")
        self.art_scale_anim.setDuration(600)
        self.art_scale_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.art_scale_anim.setEasingCurve(EASING_IN)
        self.art_scale_anim.setEasingCurve(EASING_OUT)

    def _setup_tray_icon(self):
        """Initializes the system tray icon and its context menu."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = None
            return

        self.tray_icon = QSystemTrayIcon(QIcon(resource_path('icon.ico')), self)
        self.tray_icon.setToolTip("Spotify Sync")

        menu = QMenu(self)
        
        open_settings_action = menu.addAction("Settings & Controls")
        open_settings_action.triggered.connect(self.open_settings_dialog)

        toggle_wallpaper_action = menu.addAction("Exit Wallpaper Mode")
        toggle_wallpaper_action.triggered.connect(self.toggle_wallpaper_mode)

        show_player_action = menu.addAction("Show Player")
        show_player_action.triggered.connect(lambda: self.toggle_notification_only_mode() if self.notification_only_mode else self.show())

        menu.addSeparator()

        exit_action = menu.addAction("Exit")
        exit_action.triggered.connect(self.close)

        self.tray_icon.setContextMenu(menu)
        # The icon is shown/hidden in toggle_wallpaper_mode

    def _setup_timers(self):
        self.spotify_worker = SpotifyPollingWorker(self.sp)
        self.spotify_worker.signals.track_changed.connect(self._on_spotify_track_changed)
        self.spotify_worker.signals.playback_state_changed.connect(self._on_playback_state_changed)
        self.spotify_worker.signals.no_playback.connect(self._on_spotify_no_playback)
        self.threadpool.start(self.spotify_worker)

        if IS_WINDOWS:
            self.windows_worker = WindowsMediaWorker()
            self.windows_worker.signals.track_changed.connect(self._on_windows_track_changed)
            self.windows_worker.signals.no_playback.connect(self._on_windows_no_playback)
            self.threadpool.start(self.windows_worker)

        # New timer to control the repaint rate for animations, reducing CPU usage.
        self.repaint_timer = QTimer(self)
        self.repaint_timer.setTimerType(Qt.PreciseTimer)
        self.repaint_timer.setInterval(1000 // 60)  # ~60 FPS for smoother progress
        self.repaint_timer.timeout.connect(self._on_frame_update)
        self.repaint_timer.start()

    def _setup_settings_dialog(self):
        """Initializes the settings dialog in the background at startup."""
        if self.settings_dialog:
            return

        # Create with dummy data. It will be updated when opened.
        pixmap = QPixmap(resource_path('icon.ico')).scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        album_id = "no-album"
        track_id = "no-track"
        media_source = 'none'

        self.settings_dialog = ColorEditorDialog(
            pixmap,
            album_id,
            track_id,
            self.color_cache,
            self,
            media_source=media_source
        )
        self.settings_dialog.config_saved.connect(self.on_config_saved)

    def _load_fonts(self):
        """Starts a background worker to scan for system fonts."""
        font_worker = FontLoaderWorker()
        font_worker.signals.result.connect(self._on_fonts_loaded)
        self.threadpool.start(font_worker)

    @pyqtSlot(dict)
    def _on_fonts_loaded(self, result):
        """Caches the font data once the background worker is finished."""
        self.font_styles_cache = result["font_styles_cache"]
        self.base_font_families = result["base_font_families"]
        self._fonts_loaded = True
        if self.settings_dialog:
            self.settings_dialog.update_font_data(self.font_styles_cache, self.base_font_families)

    def _handle_no_playback(self, source):
        if self.active_media_source == source:
            # The currently active media source has stopped.
            self.active_media_source = None
            self._current_track_duration = 0
            self.progress_bar.fade_out()
            self.art.setAspectRatio(1.0) # Revert to square

            # If the source that stopped was Windows, and Spotify has a track (even paused),
            # switch back to showing the Spotify track.
            if source == 'windows' and self._last_spotify_track_data:
                # Force load the last known Spotify track, preserving its paused state
                spotify_item = self._last_spotify_track_data["item"]
                spotify_is_playing = self._last_spotify_track_data["is_playing"]
                spotify_progress_ms = self._last_spotify_track_data["progress_ms"]
                self.active_media_source = 'spotify' # Re-assert Spotify as active
                self._load_track_data(spotify_item, spotify_is_playing, spotify_progress_ms, aspect_ratio=1.0)
                return # Don't proceed to fade out/idle screen

            # If no other media is available, or if Spotify was the one that stopped,
            # then proceed to fade out and show the idle screen.
            if not self.idle_timer.isActive():
                self.idle_timer.start()

    def _on_idle_timeout(self):
        if self.active_media_source is None and self.fade_out_group.state() != QAbstractAnimation.Running and self._text_alpha > 0:
            self._old_bg_color = QColor("black") # Prepare for fade-out
            self.fade_out_group.start()
            self.notification_widget.fade_out()

    @pyqtSlot()
    def _on_spotify_no_playback(self):
        self._handle_no_playback('spotify')

    @pyqtSlot()
    def _on_windows_no_playback(self):
        self._handle_no_playback('windows')

    def _on_frame_update(self):
        if self.isMinimized() or self.isHidden(): return
        if self._current_progress_bar_enabled and self.active_media_source == 'spotify':
            if not self._is_paused and self._current_track_duration > 0:
                elapsed = (QDateTime.currentMSecsSinceEpoch() - self._last_progress_sync_time)
                current = min(self._last_progress_val + elapsed, self._current_track_duration)
                self.progress_bar.setTargetValue(current)
            elif self._is_paused:
                self.progress_bar.setTargetValue(self._last_progress_val)
            
            self.progress_bar.update_smooth_value()
        self.update()

    @pyqtSlot(dict)
    def _on_spotify_track_changed(self, data):
        # If another media source is active and Spotify is not currently playing,
        # just update the last track data in the background without interrupting the UI.
        if self.active_media_source != 'spotify' and not data.get("is_playing"):
            self._last_spotify_track_data = data
            return

        self.idle_timer.stop()
        self.active_media_source = 'spotify'
        self._last_spotify_track_data = data
        
        self._current_track_duration = data["item"]["duration_ms"]
        self._last_progress_val = data["progress_ms"]
        self._last_progress_sync_time = QDateTime.currentMSecsSinceEpoch()
        self.progress_bar.setRange(0, self._current_track_duration)
        self.progress_bar.setTargetValue(self._last_progress_val, snap=True)
        # Aspect ratio is now set after the fade-out to prevent a jarring switch.
        self._load_track_data(data["item"], data["is_playing"], data["progress_ms"], aspect_ratio=1.0)

    @pyqtSlot(dict)
    def _on_windows_track_changed(self, data):
        # Only process if spotify is not the active source, or if Spotify is paused.
        # This allows Windows media to take over when Spotify is paused.
        if self.active_media_source != 'spotify' or self._is_paused:
            self.idle_timer.stop()
            # Aspect ratio is now set after the fade-out to prevent a jarring switch.
            self._current_track_duration = 0 # Disable progress for Windows for now
            self.active_media_source = 'windows'
            item = data["item"]
            thumbnail_data = data.get("thumbnail_data")

            pil_img = None
            if thumbnail_data:
                try:
                    pil_img = Image.open(io.BytesIO(thumbnail_data)).convert("RGB")
                except Exception:
                    pil_img = None

            if not pil_img:
                pil_img = Image.new("RGB", (640, 640), "black")

            self._load_track_data(item, data["is_playing"], data["progress_ms"], preloaded_image=pil_img, aspect_ratio=16.0/9.0)

    def _load_track_data(self, item, is_playing, progress_ms, preloaded_image=None, aspect_ratio=1.0):
        self._pending_track_data = None

        self._prev_track_data = {"item": item, "is_playing": is_playing, "progress_ms": progress_ms, "aspect_ratio": aspect_ratio}
        self.load_token += 1
        images_data = item["album"]["images"]
        self._current_album_id = item.get("album_id") or item["album"]["id"] or "no-album-id"
        self._current_track_id = item["id"]
        worker = TrackLoaderWorker(
            images_data, self.load_token, self._current_album_id, self._current_track_id, self.color_cache, 
            preloaded_image=preloaded_image,
            defaults={
                "font_family": self.default_font_family, "font_style": self.default_font_style,
                "font_size_scale": self.default_font_size_scale,
                "text_border_enabled": self.default_text_border_enabled
            }
        )
        worker.signals.result.connect(self._on_track_data_loaded)
        worker.signals.art_loaded.connect(self._on_high_res_art_loaded) 
        self.threadpool.start(worker)

    @pyqtSlot(dict)
    def _on_track_data_loaded(self, result_data):
        if result_data['token'] != self.load_token: return

        self._pending_track_data = result_data
        self._pending_track_data["high_res_loaded"] = False

        # Check if we are currently visible (opacity > 0)
        # If we are visible, we need to fade out the OLD track first.
        # If we are already hidden (e.g. idle screen or mid-transition), we can apply immediately.
        is_visible = self.artOpacity > 0.01 or self.textAlpha > 1
        
        if is_visible:
            if self.fade_in_group.state() == QAbstractAnimation.Running:
                self.fade_in_group.stop()
            
            # Capture the current background color to crossfade FROM
            self._old_bg_color = self._current_bg_color
            
            if self.fade_out_group.state() != QAbstractAnimation.Running:
                self.fade_out_group.start()
        else:
            self._apply_pending_track_data()

    def _on_fade_out_finished(self):
        if self._pending_track_data and self._pending_track_data['token'] == self.load_token:
            self._apply_pending_track_data()
        elif self.active_media_source is None:
            # This branch is taken only when playback has definitively stopped.
            self._prev_track_data = None
            self._is_paused = False
            self.progress_bar.fade_out()
            self._current_pil_img = None
            self._current_ui_palette = []
            self._show_idle_screen()
        # If a track is loading but the worker isn't done, do nothing. The screen is black, and we wait for _on_track_data_loaded.

    def _apply_pending_track_data(self):
        if not self._pending_track_data or not self._prev_track_data: return
        result_data = self._pending_track_data
        self._pending_track_data = None

        # Set the aspect ratio here, after the old art has faded out.
        new_aspect_ratio = self._prev_track_data.get("aspect_ratio", 1.0)
        self.art.setAspectRatio(new_aspect_ratio)

        self._current_pil_img = result_data["pil_img"]
        self._set_album_art(self._current_pil_img)
        self.art.setLoadingState(not result_data.get("high_res_loaded", False))

        item = self._prev_track_data["item"]
        track_cache = self.color_cache.get_album_data(self._current_track_id) or {}
        cached_data = track_cache or self.color_cache.get_album_data(self._current_album_id) or {}
        
        self._current_ui_palette = result_data["ui_palette"]
        self._current_lights_palette = result_data["original_lights_palette"]
        self._current_blob_palette = result_data["blob_palette"]

        # Add new theme colors to recent colors
        all_new_colors = []
        if self._current_ui_palette:
            all_new_colors.extend([QColor(*c) for c in self._current_ui_palette])
        if self._current_blob_palette:
            all_new_colors.extend([QColor(*c) for c in self._current_blob_palette])

        # Remove duplicates from new colors, keeping last seen
        # The dict.fromkeys method fails because QColor is not a hashable type.
        # We can achieve the same result (unique items, keeping last occurrence)
        # by iterating in reverse and using a set of hashable RGB values to track seen colors.
        seen_rgbs = set()
        unique_new_colors = []
        for color in reversed(all_new_colors):
            rgb_val = color.rgb()
            if rgb_val not in seen_rgbs:
                unique_new_colors.append(color)
                seen_rgbs.add(rgb_val)
        unique_new_colors.reverse()

        for color in unique_new_colors:
            # remove if exists
            self.recent_colors = [c for c in self.recent_colors if c.rgb() != color.rgb()]
            # add to front
            self.recent_colors.insert(0, color)
        self.recent_colors = self.recent_colors[:16] # Limit history

        self._current_progress_bar_enabled = cached_data.get("progress_bar_enabled", self.default_progress_bar_enabled) if isinstance(cached_data, dict) else self.default_progress_bar_enabled
        new_text_rgb = result_data["text_color"]
        self._current_text_color = new_text_rgb
        self._current_shadow_enabled = result_data["shadow_enabled"]
        self._current_font_family = result_data["font_family"]
        self._current_font_style = result_data["font_style"]
        self._current_font_size_scale = result_data.get("font_size_scale", 100)
        self._current_title_case = result_data["title_case"]
        # For now, album name will use the artist's case transformation
        self._current_artist_case = result_data["artist_case"]
        self._current_text_border_enabled = result_data.get("text_border_enabled", False)
        self._current_text_border_color = result_data.get("text_border_color") or [0, 0, 0]
        self._current_text_border_size = result_data.get("text_border_size") or self.default_text_border_size
        
        track_brightness = cached_data.get("govee_brightness")
        if track_brightness is not None:
            self.govee_brightness = float(track_brightness)
        else:
            self.govee_brightness = self.default_govee_brightness
        
        player_bg_rgb = cached_data.get("player_bg_color")
        if player_bg_rgb:
            primary_qcolor = QColor(*player_bg_rgb)
        else:
            primary_qcolor = QColor(*self._current_ui_palette[0])

        # _old_bg_color already holds the previous track's color from _load_track_data
        # Now set _current_bg_color to the new track's color
        self._current_bg_color = primary_qcolor
        

        self._update_blobs() 
        border_color = QColor(*self._current_ui_palette[1]) if len(self._current_ui_palette) > 1 else primary_qcolor.lighter(150)
        self.art.setBorderColor(border_color)
        
        self.progress_bar.set_color(new_text_rgb)
        if self._current_progress_bar_enabled and self.active_media_source == 'spotify':
            self.progress_bar.fade_in()
        else:
            self.progress_bar.fade_out()

        album_text = self._apply_case_transform(item["album"]["name"], self._current_artist_case)
        title_text = self._apply_case_transform(item["name"], self._current_title_case)
        artist_text = self._apply_case_transform(", ".join(a["name"] for a in item["artists"]), self._current_artist_case)

        self.album_name.setText(album_text)
        self.title.setText(title_text)
        self.artist.setText(artist_text)

        self.art.scale = 0.9 
        self.art_scale_anim.setStartValue(0.9)
        self.art_scale_anim.setEndValue(1.0)
        self.art_scale_anim.start()

        # Only change lights for Spotify tracks
        if self.active_media_source == 'spotify':
            lights_config = cached_data.get("lights_config", {})
            if lights_config.get("mode") == "custom" and lights_config.get("palette"):
                lights_palette_to_send = lights_config["palette"]
            else:
                lights_palette_to_send = self._current_lights_palette
            
            new_lights_config = {
                "palette": lights_palette_to_send,
                "devices": self.lights_enabled and self.govee_devices,
                "brightness": self.govee_brightness
            }
            if new_lights_config != self._last_sent_lights_config:
                self._last_sent_lights_config = new_lights_config
                worker = GoveeWorker(self._govee, lights_palette_to_send, self.lights_enabled and self.govee_devices, self.govee_brightness)
                worker.signals.error.connect(self._on_govee_error)
                self.threadpool.start(worker)   
        self.notification_widget.fade_out()
        self.textAlpha = 255
        self._bg_crossfade_lerp = 0.0  # Ensure it starts from the "from" state
        self.bg_fade_anim.setStartValue(0.0); self.bg_fade_anim.setEndValue(1.0); self.bg_fade_anim.start()
        self._trigger_notification(title_text, artist_text, self._current_pil_img, QColor(*new_text_rgb))
        self.fade_in_group.start()
        self._on_playback_state_changed(self._prev_track_data)
        self.update_layout() 
        self._update_text_properties()

        self.text_color_anim.setStartValue(self._cur_text_color); self.text_color_anim.setEndValue(QColor(*new_text_rgb)); self.text_color_anim.start()

        
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.start_content_fade_and_reload(
                self._current_album_id,
                self._current_track_id,
                self.art.pixmap())

    @pyqtSlot(dict)
    def _on_high_res_art_loaded(self, result_data):
        if result_data['token'] != self.load_token: return
        
        if self._pending_track_data and self._pending_track_data['token'] == self.load_token:
            self._pending_track_data["pil_img"] = result_data["pil_img"]
            self._pending_track_data["high_res_loaded"] = True
        else:
            self._set_album_art(result_data["pil_img"])
            self.art.setLoadingState(False)
            
            if self.settings_dialog and self.settings_dialog.isVisible():
                self.settings_dialog.load_track_state(
                    self._current_album_id,
                    self._current_track_id,
                    self.art.pixmap(),
                    animate=False
                )

    def _apply_and_refresh_ui(self):
        if not self._current_ui_palette or not self._prev_track_data:
            return
        
        item = self._prev_track_data["item"]
        
        album_cache = self.color_cache.get_album_data(self._current_album_id) or {}
        cached_data = album_cache.copy()
        cached_data.update(self.color_cache.get_album_data(self._current_track_id) or {})

        self._current_ui_palette = cached_data.get("ui_palette", self._current_ui_palette)
        self._current_blob_palette = cached_data.get("blob_palette", self._current_blob_palette)
        self._current_progress_bar_enabled = cached_data.get("progress_bar_enabled", self.default_progress_bar_enabled) if isinstance(cached_data, dict) else self.default_progress_bar_enabled
        self._current_lights_palette = cached_data.get("original_lights_palette", self._current_lights_palette)
        
        player_bg_rgb = cached_data.get("player_bg_color", self._current_ui_palette[0])
        text_rgb = cached_data.get("text_color")
        if not text_rgb:
            accent_rgb = self._current_ui_palette[1] if len(self._current_ui_palette) > 1 else None
            text_rgb = get_best_text_color(player_bg_rgb, accent_rgb)
        self._current_text_color = text_rgb

        lights_config = cached_data.get("lights_config", {})
        if lights_config.get("mode") == "custom" and lights_config.get("palette"):
            lights_palette = lights_config["palette"]
        else:
            lights_palette = self._current_lights_palette

        self._current_shadow_enabled = cached_data.get("shadow_enabled", True)
        self._current_font_family = cached_data.get("font_family", self.default_font_family)
        self._current_font_style = cached_data.get("font_style", self.default_font_style)
        self._current_font_size_scale = cached_data.get("font_size_scale", self.default_font_size_scale)
        self._current_title_case = cached_data.get("title_case", "default")
        # For now, album name will use the artist's case transformation
        self._current_artist_case = cached_data.get("artist_case", "default")
        self._current_text_border_enabled = cached_data.get("text_border_enabled", self.default_text_border_enabled)
        # Note: auto_border_enabled logic is handled in TrackLoaderWorker, so text_border_enabled here is the final result
        self._current_text_border_size = cached_data.get("text_border_size", self.default_text_border_size)
        
        track_brightness = cached_data.get("govee_brightness")
        if track_brightness is not None:
            self.govee_brightness = float(track_brightness)
        else:
            self.govee_brightness = self.default_govee_brightness
        
        # Auto-detect border color if enabled but not cached
        cached_border_color = cached_data.get("text_border_color")
        if self._current_text_border_enabled and not cached_border_color:
            candidates = []
            if len(self._current_ui_palette) > 1: candidates.append(self._current_ui_palette[1])
            if self._current_blob_palette: candidates.extend(self._current_blob_palette)
            
            self._current_text_border_color = list(get_best_border_color(player_bg_rgb, text_rgb, candidates))
        else:
            self._current_text_border_color = cached_border_color or [0, 0, 0]

        title_text = self._apply_case_transform(item["name"], self._current_title_case)
        artist_text = self._apply_case_transform(", ".join(a["name"] for a in item["artists"]), self._current_artist_case)
        self.title.setText(title_text)
        self.artist.setText(artist_text)

        album_text = self._apply_case_transform(item["album"]["name"], self._current_artist_case)
        self.album_name.setText(album_text)
        primary_qcolor = QColor(*player_bg_rgb)
        border_color = QColor(*self._current_ui_palette[1]) if len(self._current_ui_palette) > 1 else primary_qcolor.lighter(150)
        self.art.setBorderColor(border_color)
        self._old_bg_color = self._current_bg_color
        self._current_bg_color = primary_qcolor
        
        self.progress_bar.set_color(text_rgb)
        if self._current_progress_bar_enabled and self.active_media_source == 'spotify':
            self.progress_bar.fade_in()
        else:
            self.progress_bar.fade_out()

        self._update_blobs()
        # Only change lights for Spotify tracks
        if self.active_media_source == 'spotify':
            new_lights_config = {
                "palette": lights_palette,
                "devices": self.lights_enabled and self.govee_devices,
                "brightness": self.govee_brightness
            }
            
            # Only send if the configuration has actually changed
            if new_lights_config != self._last_sent_lights_config:
                self._last_sent_lights_config = new_lights_config
                worker = GoveeWorker(self._govee, lights_palette, self.lights_enabled and self.govee_devices, self.govee_brightness)
                worker.signals.error.connect(self._on_govee_error)
                self.threadpool.start(worker)

        self.textAlpha = 255
        self.text_color_anim.setStartValue(self._cur_text_color); self.text_color_anim.setEndValue(QColor(*text_rgb)); self.text_color_anim.start()
        self.bg_fade_anim.setStartValue(0.0); self.bg_fade_anim.setEndValue(1.0); self.bg_fade_anim.start()
        self.fade_in_group.stop(); self.fade_in_group.start()
        self._trigger_notification(title_text, artist_text, self._current_pil_img, QColor(*text_rgb))

        self._update_text_properties()
        self.update() 

    def _trigger_notification(self, title, artist, pil_img, text_color=None):
        settings = QSettings("SpotifySync", "App")
        if settings.value("notification_enabled", "false") != "true":
            return

        screens = QApplication.screens()
        monitor_idx = int(settings.value("notification_monitor_index", 0))
        
        screen = None
        if monitor_idx == 0:
            screen = QApplication.primaryScreen()
        elif monitor_idx - 1 < len(screens):
            screen = screens[monitor_idx - 1]
        
        if not screen: screen = QApplication.primaryScreen()
        
        if settings.value("notification_smart_hide", "false") == "true":
            if self.isVisible() and not self.isMinimized() and not self.notification_only_mode:
                player_screen = QApplication.screenAt(self.geometry().center())
                if player_screen == screen:
                    return
        
        if settings.value("notification_ignore_taskbar", "true") == "true":
            geo = screen.geometry()
        else:
            geo = screen.availableGeometry()
        corner = settings.value("notification_corner", "Top-Right")
        
        size_index = int(settings.value("notification_size", 1))
        scales = [0.7, 0.85, 1.0, 1.25, 1.5]
        scale = scales[size_index] if 0 <= size_index < len(scales) else 1.0
        self.notification_widget.set_zoom(scale)
        
        w, h = self.notification_widget.width(), self.notification_widget.height()
        margin = 20
        x, y = 0, 0
        
        if corner == "Top-Left":
            x = geo.x() + margin
            y = geo.y() + margin
        elif corner == "Top-Center":
            x = geo.x() + (geo.width() - w) // 2
            y = geo.y() + margin
        elif corner == "Top-Right":
            x = geo.x() + geo.width() - w - margin
            y = geo.y() + margin
        elif corner == "Bottom-Left":
            x = geo.x() + margin
            y = geo.y() + geo.height() - h - margin
        elif corner == "Bottom-Center":
            x = geo.x() + (geo.width() - w) // 2
            y = geo.y() + geo.height() - h - margin
        elif corner == "Bottom-Right":
            x = geo.x() + geo.width() - w - margin
            y = geo.y() + geo.height() - h - margin
            
        anim_type = settings.value("notification_anim", "Fade")
        anim_dir = settings.value("notification_dir", "From Top")
        permanent = settings.value("notification_permanent", "false") == "true"
        duration = int(settings.value("notification_duration", 4000))
        anim_duration = int(settings.value("notification_anim_duration", 500))
        notif_opacity = int(settings.value("notification_bg_opacity", 230))
        notif_border_enabled = settings.value("notification_border_enabled", "false") == "true"
        
        if self._current_ui_palette:
            primary_qcolor = self._current_bg_color
            if len(self._current_ui_palette) > 1:
                notif_border_color = QColor(*self._current_ui_palette[1]).name()
            else:
                notif_border_color = primary_qcolor.lighter(150).name()
        else:
            notif_border_color = settings.value("notification_border_color", "#FFFFFF")
        
        pixmap = QPixmap()
        if pil_img:
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            pixmap.loadFromData(buf.getvalue(), "PNG")

        if text_color is None:
            text_color = self._cur_text_color

        # Bundle arguments instead of applying them immediately
        style_args = {
            "bg_color": self._current_bg_color,
            "text_color": text_color,
            "font_family": self._current_font_family,
            "font_style": self._current_font_style,
            "border_enabled": self._current_text_border_enabled,
            "border_color": QColor(*self._current_text_border_color),
            "notif_opacity": notif_opacity,
            "notif_border_enabled": notif_border_enabled,
            "notif_border_color": notif_border_color,
            "border_size": self._current_text_border_size
        }

        content_args = {
            "title": title,
            "artist": artist,
            "pixmap": pixmap
        }

        anim_args = {
            "anim_type": anim_type,
            "direction": anim_dir,
            "screen_pos": QPoint(x, y),
            "duration": duration,
            "anim_duration": anim_duration,
            "permanent": permanent
        }

        # Use the transition method to handle the animation lifecycle
        self.notification_widget.transition_to_notification(style_args, content_args, anim_args)

    def _on_notification_clicked(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_error_notification_clicked(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    @pyqtSlot(str)
    def _on_govee_error(self, error_message):
        settings = QSettings("SpotifySync", "App")
        track_corner = settings.value("notification_corner", "Top-Right")
        
        # Determine opposite vertical corner
        if "Top" in track_corner:
            error_corner = track_corner.replace("Top", "Bottom")
        else:
            error_corner = track_corner.replace("Bottom", "Top")
            
        screens = QApplication.screens()
        monitor_idx = int(settings.value("notification_monitor_index", 0))
        screen = screens[monitor_idx - 1] if 0 < monitor_idx <= len(screens) else QApplication.primaryScreen()
        
        if settings.value("notification_ignore_taskbar", "true") == "true":
            geo = screen.geometry()
        else:
            geo = screen.availableGeometry()
            
        w, h = self.error_notification_widget.width(), self.error_notification_widget.height()
        margin = 20
        x, y = 0, 0
        
        if "Top-Left" in error_corner: x, y = geo.x() + margin, geo.y() + margin
        elif "Top-Center" in error_corner: x, y = geo.x() + (geo.width() - w) // 2, geo.y() + margin
        elif "Top-Right" in error_corner: x, y = geo.x() + geo.width() - w - margin, geo.y() + margin
        elif "Bottom-Left" in error_corner: x, y = geo.x() + margin, geo.y() + geo.height() - h - margin
        elif "Bottom-Center" in error_corner: x, y = geo.x() + (geo.width() - w) // 2, geo.y() + geo.height() - h - margin
        elif "Bottom-Right" in error_corner: x, y = geo.x() + geo.width() - w - margin, geo.y() + geo.height() - h - margin

        self.error_notification_widget.update_style(
            bg_color=QColor(180, 40, 40),
            text_color=QColor(255, 255, 255),
            font_family="Trebuchet MS",
            font_style="Bold",
            notif_opacity=240,
            border_enabled=False,
            notif_border_enabled=False
        )
        
        self.error_notification_widget.set_content("Govee API Error", error_message, None)
        self.error_notification_widget.show_notification("Fade", "From Bottom" if "Bottom" in error_corner else "From Top", QPoint(x, y), duration=6000)

    def _apply_case_transform(self, text, case_mode):
        if case_mode == "upper": return text.upper()
        if case_mode == "lower": return text.lower()
        return text

    @pyqtSlot(str, dict)
    def on_config_saved(self, album_id, new_config):
        # Reload global defaults from QSettings as they might have changed
        settings = QSettings("SpotifySync", "App")
        self.default_font_family = settings.value("default_font_family", "Trebuchet MS")
        self.default_font_style = settings.value("default_font_style", "Bold")
        self.default_font_size_scale = int(settings.value("default_font_size_scale", 100))
        self.default_progress_bar_enabled = settings.value("default_progress_bar_enabled", "false") == "true"
        self.default_text_border_enabled = settings.value("default_text_border_enabled", "false") == "true"
        self.default_text_border_size = int(settings.value("default_text_border_size", 3))
        val = settings.value("default_govee_brightness")
        if val is not None:
            self.default_govee_brightness = float(val)
        self._apply_and_refresh_ui() 

    def toggle_lights(self):
        """Toggles Govee light synchronization on or off."""
        self.lights_enabled = not self.lights_enabled
        print(f"Govee lights toggled: {'ON' if self.lights_enabled else 'OFF'}")
        # If we are turning lights on and a track is playing, refresh to send colors.
        if self.lights_enabled and self._prev_track_data:
            self._apply_and_refresh_ui()

    def toggle_notification_only_mode(self):
        """Toggles the mode where the player is hidden but notifications still work."""
        if self.notification_only_mode:
            self.notification_only_mode = False
            
            if self.is_fullscreen and not self.multi_monitor_mode:
                self.showFullScreen()
            else:
                self.show()
            
            self.raise_()
            self.activateWindow()
            
            self.entry_anim.setStartValue(0.0)
            self.entry_anim.setEndValue(1.0)
            self.entry_anim.start()
            if self.tray_icon and not self.is_wallpaper_mode:
                self.tray_icon.hide()
        else:
            if not self.tray_icon: return # Cannot enter this mode without tray to restore
            self.notification_only_mode = True
            self.tray_icon.show()
            
            self.exit_anim = QPropertyAnimation(self, b"windowOpacity")
            self.exit_anim.setDuration(600)
            self.exit_anim.setStartValue(self.windowOpacity())
            self.exit_anim.setEndValue(0.0)
            self.exit_anim.setEasingCurve(QEasingCurve.OutQuad)
            self.exit_anim.finished.connect(self._hide_for_notif_mode)
            self.exit_anim.start()

    def _hide_for_notif_mode(self):
        if self.notification_only_mode:
            self.hide()
            try: self.exit_anim.finished.disconnect(self._hide_for_notif_mode)
            except: pass

    def _update_blobs(self):
        palette = self._current_blob_palette
        if not palette:
            if self._current_ui_palette:
                accent = QColor(*self._current_ui_palette[1]) if len(self._current_ui_palette) > 1 else QColor(*SPOTIFY_GREEN)
                base = QColor(*self._current_ui_palette[0]) if len(self._current_ui_palette) > 0 else QColor("black")
                palette = [accent.getRgb()[:3], base.darker(130).getRgb()[:3], accent.darker(150).getRgb()[:3]]
            else:
                palette = [SPOTIFY_GREEN, [10, 100, 40], [15, 150, 60]]

        blob_colors = [QColor(*c) for c in palette]

        if self.blob_manager:
            # Manager exists, just update its palette. This will handle adding/removing/recoloring blobs smoothly.
            self.blob_manager.update_palette(blob_colors)
        else:
            # First time setup for blobs
            self.blob_manager = BlobManager(self, self.size(), blob_colors)
            self.blob_manager.density = self.blob_density
            self.blob_manager.adjust_blob_count()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        is_rounded = not (self.is_fullscreen or self.multi_monitor_mode or self.is_wallpaper_mode)
        path = QPainterPath()
        if is_rounded:
            path.addRoundedRect(QRectF(self.rect()), 20, 20)
        else:
            path.addRect(QRectF(self.rect()))

        painter.setClipPath(path)

        if self._bg_crossfade_lerp >= 1.0:
            painter.fillPath(path, self._current_bg_color)
        else:
            painter.fillPath(path, self._old_bg_color)
            painter.setOpacity(self._bg_crossfade_lerp)
            painter.fillPath(path, self._current_bg_color)

        if self.blob_manager:
            # SmoothPixmapTransform is a good quality/performance tradeoff for the blobs.
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            for blob in self.blob_manager.blobs + self.blob_manager.dying_blobs:
                if not blob.pixmap or blob.opacity <= 0.01: continue
                painter.setOpacity(blob.opacity)
                
                r = blob.radius * blob.scale
                target_rect = QRectF(blob.center.x() - r, blob.center.y() - r, r * 2, r * 2)
                painter.drawPixmap(target_rect, blob.pixmap, QRectF(blob.pixmap.rect()))

        painter.setOpacity(1.0) 
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_layout() 
        self._update_text_properties() 
        if self.title and self.artist:
            self.album_name.update_scroll() # Update scroll for album name
            self.title.update_scroll()
            self.artist.update_scroll()

        if self.blob_manager:
            self.blob_manager.resize(self.size())

        if hasattr(self, 'overlay'):
            self.overlay.resize(self.container.size())

        self._bg_crossfade_lerp = 1.0 
        self.update()

    def update_layout(self):
        width = self.width()
        height = self.height()
        if width == 0 or height == 0 or not self.details_widget:
            return

        effective_w = width
        effective_h = height
        extra_left = extra_top = extra_right = extra_bottom = 0

        # Check if we should apply a multi-monitor layout. This is true if we are actively in multi-monitor mode,
        # OR if we are in wallpaper mode that was initiated FROM multi-monitor mode.
        is_multi_monitor_layout = self.multi_monitor_mode and self.target_monitor_geo and self.total_screens_geo
        is_wallpaper_from_multi = self.is_wallpaper_mode and self._was_multi_monitor and hasattr(self, '_saved_target_monitor_geo')

        if is_multi_monitor_layout or is_wallpaper_from_multi:
            if is_multi_monitor_layout:
                target_geo = self.target_monitor_geo
                total_geo = self.total_screens_geo
            else: # is_wallpaper_from_multi
                target_geo = self._saved_target_monitor_geo
                total_geo = self._saved_total_screens_geo

            rel_x = target_geo.x() - total_geo.x()
            rel_y = target_geo.y() - total_geo.y()
            target_w = target_geo.width()
            target_h = target_geo.height()
            
            effective_w = target_w
            effective_h = target_h
            
            extra_left = rel_x
            extra_top = rel_y
            extra_right = width - (rel_x + target_w)
            extra_bottom = height - (rel_y + target_h)

        is_vertical = effective_h >= effective_w
        details_layout = self.details_widget.layout()

        if is_vertical:
            # In vertical mode, the details widget can take the full width.
            self.details_widget.setMaximumWidth(16777215) # QWIDGETSIZE_MAX
        else:
            # In horizontal mode, cap the width of the details widget to prevent
            # it from shrinking the album art too much with long text.
            max_details_width = int(effective_w * 0.60)
            self.details_widget.setMaximumWidth(max_details_width)

        if is_vertical:
            self.main_layout.setDirection(QBoxLayout.TopToBottom)
            m = self.VERTICAL_ORIENTATION_MARGINS
            self.main_layout.setContentsMargins(m[0] + extra_left, m[1] + extra_top, m[2] + extra_right, m[3] + extra_bottom)
            details_layout.setAlignment(Qt.AlignCenter)
            self.title.setAlignment(Qt.AlignCenter)
            self.artist.setAlignment(Qt.AlignCenter)
            self.album_name.setAlignment(Qt.AlignCenter)
            self.progress_bar.setFixedWidth(340)
        else:
            self.main_layout.setDirection(QBoxLayout.LeftToRight)
            m = self.NORMAL_MARGINS # Use normal margins for horizontal layout
            self.main_layout.setContentsMargins(m[0] + extra_left, m[1] + extra_top, m[2] + extra_right, m[3] + extra_bottom)
            details_layout.setAlignment(Qt.AlignCenter)
            self.title.setAlignment(Qt.AlignCenter)
            self.album_name.setAlignment(Qt.AlignCenter)
            self.artist.setAlignment(Qt.AlignCenter)
            self.progress_bar.setFixedWidth(550)

        while self.main_layout.count():
            self.main_layout.takeAt(0)

        if is_vertical:
            details_layout.insertWidget(1, self.album_name) # Re-insert album name
            self.main_layout.addStretch(1)
            self.main_layout.addWidget(self.art_container, 5)
            self.main_layout.addWidget(self.details_widget, 2, Qt.AlignCenter)
            self.main_layout.addStretch(1)
            details_layout.setAlignment(self.progress_bar, Qt.AlignCenter)
        else:
            self.main_layout.addStretch(1)
            self.main_layout.addWidget(self.art_container, 5)
            self.main_layout.addWidget(self.details_widget, 6)
            details_layout.insertWidget(1, self.album_name) # Re-insert album name
            details_layout.addWidget(self.progress_bar, 0, Qt.AlignCenter)
            self.main_layout.addStretch(1)

        # Defensive check to ensure wallpaper mode flags are not lost
        if self.is_wallpaper_mode:
            current_flags = self.windowFlags()
            wallpaper_flags = Qt.FramelessWindowHint | Qt.WindowStaysOnBottomHint | Qt.Tool
            if current_flags != wallpaper_flags:
                self.setWindowFlags(wallpaper_flags)
                self.show()

        self.details_widget.setContentsMargins(20 if is_vertical else 40, 0, 20, 0)
        self.update() 
        self._update_text_properties() 
        
        if self._prev_track_data:
            self.fade_in_group.start()

    @pyqtSlot(dict)
    def _on_playback_state_changed(self, data):
        is_playing = data.get("is_playing", False)
        self._last_progress_val = data.get("progress_ms", 0)
        self._last_progress_sync_time = QDateTime.currentMSecsSinceEpoch()
        
        is_paused = not is_playing
        if is_paused == self._is_paused:
            return
        self._is_paused = is_paused

        # If Spotify starts playing (was paused, now playing) while we are viewing
        # another media source, we should switch back to Spotify.
        if is_playing and self.active_media_source != 'spotify' and self._last_spotify_track_data:
            # A spotify track exists and has just started playing. Re-assert it as the active source.
            self._last_spotify_track_data['is_playing'] = True
            self._on_spotify_track_changed(self._last_spotify_track_data)
        
    def setBgCrossfadeLerp(self, value):
        self._bg_crossfade_lerp = value
        self.update()

    def setTextAlpha(self, alpha): 
        if self.title and self.artist and self.album_name: 
            self._text_alpha=int(alpha)
            self.setTextColor(self._cur_text_color)
            
    def setTextColor(self, color):
        self._cur_text_color = color
        text_with_alpha = QColor(color)
        text_with_alpha.setAlpha(self._text_alpha) # Apply alpha to text color

        border_c = QColor(*self._current_text_border_color)
        border_c.setAlpha(self._text_alpha)

        shadow_color = QColor(0, 0, 0) 
        shadow_color.setAlpha(int((100 / 255) * self._text_alpha)) 

        # Apply alpha to album name shadow and text
        if self.album_name.graphicsEffect(): self.album_name.graphicsEffect().setColor(shadow_color)
        self.album_name.setTextColor(text_with_alpha)
        self.album_name.setBorder(self._current_text_border_enabled, border_c)
        self.album_name.setBorder(self._current_text_border_enabled, border_c, self._current_text_border_size)
        
        if self.title.graphicsEffect(): self.title.graphicsEffect().setColor(shadow_color)
        if self.artist.graphicsEffect(): self.artist.graphicsEffect().setColor(shadow_color)

        self.title.setTextColor(text_with_alpha)
        self.title.setBorder(self._current_text_border_enabled, border_c)
        self.title.setBorder(self._current_text_border_enabled, border_c, self._current_text_border_size)
        self.artist.setTextColor(text_with_alpha)
        self.artist.setBorder(self._current_text_border_enabled, border_c)
        self.artist.setBorder(self._current_text_border_enabled, border_c, self._current_text_border_size)
        self.progress_bar.set_color(text_with_alpha)

    def update_art_shadow_properties(self):
        if not self.art_shadow: return
        self.art_shadow.setBlurRadius(40)
        self.art_shadow.setColor(QColor(0, 0, 0, 80))
        self.art_shadow.setOffset(0, 8)
        self.art_shadow.setEnabled(self.art._opacity > 0)

    def _update_text_properties(self):
        if not self.art or self.art.width() < 50: 
            return
        self.update_art_shadow_properties()

        art_w, art_h = self.art.width(), self.art.height()
        art_diagonal = (art_w**2 + art_h**2)**0.5
        base_diagonal = (500**2 + 500**2)**0.5 
        scale_factor = (art_diagonal / base_diagonal) ** 0.8 
        user_scale = self._current_font_size_scale / 100.0

        db = QFontDatabase()
        title_font = db.font(self._current_font_family, self._current_font_style, -1)
        title_font.setPixelSize(int(max(12, 28 * scale_factor * user_scale)))
        self.title.setFont(title_font)

        artist_font = db.font(self._current_font_family, self._current_font_style, -1)
        artist_font.setPixelSize(int(max(10, 22 * scale_factor * user_scale)))
        self.artist.setFont(artist_font)
        
        # New: Album name font size
        album_font = db.font(self._current_font_family, self._current_font_style, -1)
        album_font.setPixelSize(int(max(9, 18 * scale_factor * user_scale))) # Slightly smaller than artist
        self.album_name.setFont(album_font)

        offset_val = abs(max(1, 2.5 * scale_factor))
        
        self.title_shadow.setBlurRadius(max(8, 15 * scale_factor))
        self.title_shadow.setOffset(offset_val, offset_val)

        self.artist_shadow.setBlurRadius(max(6, 13 * scale_factor))
        self.artist_shadow.setOffset(offset_val, offset_val)

        # New: Album name shadow properties
        self.album_name.graphicsEffect().setBlurRadius(max(6, 13 * scale_factor))
        self.album_name.graphicsEffect().setOffset(offset_val, offset_val)

        self.title_shadow.setEnabled(self._current_shadow_enabled)
        self.artist_shadow.setEnabled(self._current_shadow_enabled)
        self.album_name.graphicsEffect().setEnabled(self._current_shadow_enabled) # Enable/disable album shadow

        self.title.setContentsMargins(0, 0, 0, int(offset_val) + 2)
        self.setTextColor(self._cur_text_color)

    def open_settings_dialog(self):
        """Shows the pre-loaded settings/color editor dialog."""
        if not self.settings_dialog:
            self._setup_settings_dialog()

        pixmap = self.art.pixmap()
        if not pixmap or pixmap.isNull():
            pixmap = QPixmap(resource_path('icon.ico')).scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        album_id = self._current_album_id or "no-album"
        track_id = self._current_track_id or "no-track"
        media_source = self.active_media_source or 'none'

        # The dialog is already created, just update its state and show it.
        self.settings_dialog.media_source = media_source
        self.settings_dialog.load_track_state(album_id, track_id, pixmap, animate=False)

        # Position the dialog
        if self.is_wallpaper_mode and self.tray_icon:
            screen_geo = QApplication.primaryScreen().geometry()
            dialog_x = screen_geo.center().x() - self.settings_dialog.width() / 2
            dialog_y = screen_geo.center().y() - self.settings_dialog.height() / 2
            self.settings_dialog.move(int(dialog_x), int(dialog_y))
        else:
            parent_rect = self.geometry()
            self.settings_dialog.move(parent_rect.right() - self.settings_dialog.width() - 20, parent_rect.top() + 40)

        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def restart_app(self):
        """Closes the current application instance and starts a new one."""
        # The closeEvent will handle saving settings and stopping workers.
        QProcess.startDetached(sys.executable, sys.argv)
        self.close()

    def closeEvent(self, event):
        if not getattr(self, '_is_closing', False):
            event.ignore()
            self._is_closing = True
            self.exit_anim = QPropertyAnimation(self, b"windowOpacity")
            self.exit_anim.setDuration(600)
            self.threadpool.clear()

            self.exit_anim.setStartValue(self.windowOpacity())
            self.exit_anim.setEndValue(0.0)
            self.exit_anim.setEasingCurve(QEasingCurve.OutQuad)
            self.exit_anim.finished.connect(self.close)
            self.exit_anim.start()
            return

        if self.spotify_worker: self.spotify_worker.is_running = False
        if IS_WINDOWS and self.windows_worker: self.windows_worker.stop()
        
        
        # Wait for running tasks to finish. With the improved worker sleep, this should be fast.
        if not self.threadpool.waitForDone(2000): # Wait up to 2 seconds
            print("Warning: Background threads did not finish gracefully.")
        del self.spotify_worker
        del self.windows_worker
        del self.blob_manager
        del self.settings_dialog
        self._save_settings()
        # Force exit to ensure all processes are terminated, which can be an issue in bundled executables.
        sys.exit(0)
        
    def _set_album_art(self, pil_img):
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        pixmap = QPixmap()
        pixmap.loadFromData(buf.getvalue(), "PNG")
        if not pixmap.isNull():
            self.art.setPixmap(pixmap)
        else:
            print("Error: Could not create QPixmap from PIL image data")
        
    def toggle_multi_monitor_fullscreen(self):
        screens = QApplication.screens()
        if not screens:
            return  # Handle case with no screens

        total_rect = QRect()
        for screen in screens:
            total_rect = total_rect.united(screen.geometry())

        if self.multi_monitor_mode:
            self.multi_monitor_mode = False
            self.setWindowFlags(Qt.FramelessWindowHint)
            self.showNormal()
            self.is_fullscreen = False
        else:
            current_screen = QApplication.screenAt(self.geometry().center())
            if not current_screen:
                current_screen = screens[0]
            
            self.target_monitor_geo = current_screen.geometry()
            self.total_screens_geo = total_rect
            self.multi_monitor_mode = True

            self.showNormal()
            self.setWindowFlags(Qt.FramelessWindowHint)
            self.setGeometry(total_rect)
            self.show()
            self.is_fullscreen = True
            
    def shift_multi_monitor_content(self, direction):
        # Allow shifting if in multi-monitor OR in wallpaper that came from multi-monitor
        is_in_valid_state = self.multi_monitor_mode or (self.is_wallpaper_mode and self._was_multi_monitor)
        if not is_in_valid_state:
            return

        screens = QApplication.screens()
        screens.sort(key=lambda s: (s.geometry().x(), s.geometry().y()))

        # Determine which geometry to use as the current one
        if self.is_wallpaper_mode:
            current_geo = self._saved_target_monitor_geo
        else:
            current_geo = self.target_monitor_geo
        
        if not current_geo: return

        current_index = -1
        for i, screen in enumerate(screens):
            if screen.geometry() == current_geo:
                current_index = i
                break
        
        if current_index != -1:
            new_index = (current_index + direction) % len(screens)
            self.target_monitor_geo = screens[new_index].geometry()
            new_geo = screens[new_index].geometry()
            
            # Update the correct geometry variable
            if self.is_wallpaper_mode:
                self._saved_target_monitor_geo = new_geo
            else:
                self.target_monitor_geo = new_geo
            
            self.update_layout()

    def shift_single_monitor_fullscreen(self, direction):
        screens = QApplication.screens()
        if len(screens) < 2: return
        screens.sort(key=lambda s: (s.geometry().x(), s.geometry().y()))
        
        current_screen = QApplication.screenAt(self.geometry().center())
        if not current_screen: current_screen = screens[0]
        
        try: index = screens.index(current_screen)
        except ValueError: index = 0
        
        new_index = (index + direction) % len(screens)
        new_screen = screens[new_index]
        
        self.notification_widget.hide()

        if self.windowState() & Qt.WindowFullScreen:
            self.showNormal()
            if self.windowHandle(): self.windowHandle().setScreen(new_screen)
            self.setGeometry(new_screen.geometry())
            self.showFullScreen()
        else:
            self.setGeometry(new_screen.geometry())
            self.update_layout()

        # Delay updates to allow window system to complete resize/move
        QTimer.singleShot(100, lambda: (
            self.update_layout(),
            self._update_text_properties(),
            self.title and self.artist and self._trigger_notification(self.title.text(), self.artist.text(), self._current_pil_img, self._cur_text_color)
        ))

    def toggle_wallpaper_mode(self):
        if self.is_wallpaper_mode:
            self.is_wallpaper_mode = False
            if self.tray_icon: self.tray_icon.hide()
            self.setWindowFlags(self._saved_flags)
            if self._was_multi_monitor:
                self.target_monitor_geo = self._saved_target_monitor_geo
                self.total_screens_geo = self._saved_total_screens_geo
            self.setGeometry(self._saved_geometry)
            if self._was_multi_monitor:
                self.multi_monitor_mode = True
                self.is_fullscreen = True
                self.show()
            elif self._was_fullscreen:
                self.is_fullscreen = True
                self.showFullScreen()
            else:
                self.is_fullscreen = False
                self.showNormal()
        else:
            self._saved_flags = self.windowFlags()
            self._saved_geometry = self.geometry()
            self._was_fullscreen = self.is_fullscreen
            self._was_multi_monitor = self.multi_monitor_mode
            if self.multi_monitor_mode:
                self._saved_target_monitor_geo = self.target_monitor_geo
                self._saved_total_screens_geo = self.total_screens_geo

            self.is_wallpaper_mode = True
            self.multi_monitor_mode = False
            self.is_fullscreen = False
            
            target_geo = self.geometry()
            if not self._was_fullscreen and not self._was_multi_monitor:
                screen = QApplication.screenAt(self.geometry().center())
                if not screen:
                    screens = QApplication.screens()
                    if screens: screen = screens[0]
                if screen: # Use availableGeometry() to avoid taskbar overlap
                    target_geo = screen.availableGeometry()
            
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnBottomHint | Qt.Tool)
            self.setGeometry(target_geo)
            self.show()
            if self.tray_icon: self.tray_icon.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            # The dialog is modal, so this event shouldn't fire when it's open,
            # but this is a good safeguard.
            if self.overlay.isHidden():
                self.overlay.resize(self.container.size())
                self.overlay.fade_in()
                event.accept()
        elif event.button() == Qt.LeftButton:
            if not (self.is_fullscreen or self.multi_monitor_mode or self.is_wallpaper_mode):
                self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
        else:
            # Pass other clicks to the parent
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_pos:
            if not (self.is_fullscreen or self.multi_monitor_mode or self.is_wallpaper_mode):
                self.move(event.globalPos() - self.drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape: self.close()
        elif event.key() == Qt.Key_F:
            if self.is_wallpaper_mode:
                return
            if self.multi_monitor_mode:
                self.multi_monitor_mode = False
                self.is_fullscreen = True
                self.setWindowFlags(Qt.FramelessWindowHint)
                if self.target_monitor_geo: self.setGeometry(self.target_monitor_geo)
                self.show()
                self.update_layout()
            elif self.is_fullscreen:
                self.is_fullscreen = False
                if not (self.windowState() & Qt.WindowFullScreen):
                    self.setWindowFlags(Qt.FramelessWindowHint)
                self.showNormal()
            else:
                self.is_fullscreen = True
                self.showFullScreen()
        elif event.key() == Qt.Key_F11:
            if self.is_wallpaper_mode:
                return
            self.toggle_multi_monitor_fullscreen()
        elif event.key() == Qt.Key_F12:
            self.toggle_wallpaper_mode()
        elif event.key() == Qt.Key_Left:
            if self.multi_monitor_mode or (self.is_wallpaper_mode and hasattr(self, '_was_multi_monitor') and self._was_multi_monitor):
                self.shift_multi_monitor_content(-1)
            elif self.is_fullscreen:
                self.shift_single_monitor_fullscreen(-1)
        elif event.key() == Qt.Key_Right:
            if self.multi_monitor_mode or (self.is_wallpaper_mode and hasattr(self, '_was_multi_monitor') and self._was_multi_monitor):
                self.shift_multi_monitor_content(1)
            elif self.is_fullscreen:
                self.shift_single_monitor_fullscreen(1)
        elif event.key() == Qt.Key_L:
            self.toggle_lights()

        elif event.key() == Qt.Key_C: # Customization Dialog
            self.open_settings_dialog()
        else:
            super().keyPressEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.entry_anim = QPropertyAnimation(self, b"windowOpacity")
        self.entry_anim.setDuration(600)
        self.entry_anim.setStartValue(0.0)
        self.entry_anim.setEndValue(1.0)
        self.entry_anim.setEasingCurve(QEasingCurve.OutQuad)
        self.entry_anim.start()

if __name__ == "__main__":
    multiprocessing.freeze_support()
    os.environ["XDG_SESSION_TYPE"] = "xcb"
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setOrganizationName("SpotifySync")
    app.setApplicationName("App")

    player = SpotifyPlayer()
    if player.is_fullscreen and not player.multi_monitor_mode:
        player.showFullScreen()
    else:
        player.show()

    if hasattr(player, '_start_in_wallpaper') and player._start_in_wallpaper:
        QTimer.singleShot(100, player.toggle_wallpaper_mode)

    sys.exit(app.exec_())