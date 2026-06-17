# main.py
import sys

class PhantomAudioOp:
    """A pure-Python dummy module to prevent pydub from crashing on import in Python 3.14+"""
    class error(Exception): pass
    
    @staticmethod
    def rms(*args, **kwargs): return 1
    @staticmethod
    def max(*args, **kwargs): return 1
    @staticmethod
    def getsample(*args, **kwargs): return 0
    @staticmethod
    def tomono(fragment, *args, **kwargs): return fragment
    @staticmethod
    def tostereo(fragment, *args, **kwargs): return fragment
    @staticmethod
    def lin2lin(fragment, *args, **kwargs): return fragment
    @staticmethod
    def ratecv(fragment, *args, **kwargs): return fragment, None
    @staticmethod
    def mul(fragment, *args, **kwargs): return fragment
    @staticmethod
    def add(fragment1, *args, **kwargs): return fragment1
    @staticmethod
    def reverse(fragment, *args, **kwargs): return fragment

sys.modules['audioop'] = PhantomAudioOp()
sys.modules['pyaudioop'] = PhantomAudioOp()

import os
import json
import io
import time
import multiprocessing
import ctypes
from services import ColorCache, LyricsCache, GoveeController, SoundManager, GlobalSoundFilter, AppleMusicClient
from PIL import Image
from requests import get

# --- FIXED IMPORTS ---
# QRectF, QPropertyAnimation, and QVariantAnimation moved to QtCore
from PyQt5.QtCore import (
    Qt, QTimer, QThreadPool, QRunnable, QSettings, QRect, QDateTime, pyqtSlot, QProcess, 
    pyqtProperty, QEasingCurve, QParallelAnimationGroup, QSequentialAnimationGroup,
    QEvent,
    QAbstractAnimation, QPoint, QRectF, QPropertyAnimation, QVariantAnimation, QStandardPaths
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QBoxLayout, QVBoxLayout,
    QGraphicsDropShadowEffect, QSizePolicy, QSystemTrayIcon, QMenu, QDialog
)
from PyQt5.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPixmap, QKeySequence, QFontMetrics
)

from spotipy import Spotify, SpotifyOAuth
from spotipy.cache_handler import CacheFileHandler

from config import (
    SPOTIPY_REDIRECT_URI,
    SPOTIFY_SCOPE,
    SPOTIFY_GREEN,
    APPLE_MUSIC_RED,
    BACKGROUND_TARGET_FPS,
    LAVA_LAMP_PRESET,
)
from utils import resource_path
from workers import ListenModeWorker, SpotifyPollingWorker, WindowsMediaWorker, TrackLoaderWorker, FontLoaderWorker, GoveeWorker, AppleMusicPollingWorker, LyricsWorker, IS_WINDOWS
from ui.widgets import ResponsiveAlbumArtLabel, ScrollingTextLabel, SmoothProgressBar, BlobManager, BorderedLabel, LyricsLabel, PlayerControlsBar
from ui.playlist_panel import PlaylistPanel
from ui.renderers import BackgroundRendererController
from utils import get_best_text_color, get_best_border_color
from ui.overlays import OverlayWidget, NotificationWidget
from ui.dialogs import ColorEditorDialog, SpotifySetupDialog, AppleMusicSetupDialog, ThemedMessageBox


class _MonitorHopOverlay(QWidget):
    """Full-window black veil used during monitor-hop transitions.

    Animates its own painted alpha so the main window stays at opacity 1.0
    throughout — this prevents DWM / QOpenGLWidget compositing flicker that
    occurs when setWindowOpacity is animated on a WA_TranslucentBackground
    window containing an OpenGL surface.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._alpha = 0

    def get_alpha(self):
        return self._alpha

    def set_alpha(self, val):
        self._alpha = max(0, min(255, int(val)))
        self.update()

    alpha = pyqtProperty(int, get_alpha, set_alpha)

    def paintEvent(self, event):
        if self._alpha > 0:
            p = QPainter(self)
            p.fillRect(self.rect(), QColor(0, 0, 0, self._alpha))


class SpotifyPlayer(QMainWindow):
    artOpacity = pyqtProperty(float, fget=lambda self: self.art._opacity if hasattr(self, 'art') else 1.0, fset=lambda self, o: self.art.setOpacity(o) if hasattr(self, 'art') else None)
    textAlpha = pyqtProperty(float, fget=lambda self: self._text_alpha, fset=lambda self, a: self.setTextAlpha(a))
    bgCrossfadeLerp = pyqtProperty(float, fget=lambda self: self._bg_crossfade_lerp, fset=lambda self, v: self.setBgCrossfadeLerp(v))
    SHORTCUT_DEFINITIONS = [
        {"id": "toggle_fullscreen", "label": "Toggle Fullscreen", "description": "Toggle fullscreen mode.", "default": "F"},
        {"id": "toggle_multi_monitor", "label": "Toggle Multi-Monitor", "description": "Toggle multi-monitor spanning mode.", "default": "F11"},
        {"id": "toggle_wallpaper", "label": "Toggle Wallpaper Mode", "description": "Toggle wallpaper mode (places behind icons).", "default": "F12"},
        {"id": "shift_left", "label": "Shift Left", "description": "Shift player content to the previous monitor.", "default": "Left"},
        {"id": "shift_right", "label": "Shift Right", "description": "Shift player content to the next monitor.", "default": "Right"},
        {"id": "toggle_lights", "label": "Toggle Lights", "description": "Toggle Govee light synchronization.", "default": "L"},
        {"id": "open_settings", "label": "Open Settings", "description": "Open the settings panel.", "default": "C"},
        {"id": "close_app", "label": "Close Application", "description": "Close the application.", "default": ""},
    ]

    def __init__(self):
        super().__init__()
        self._last_native_caption_rgb = None
        self._user_playlists = []  # Preloaded user playlists
        self._user_albums = []  # Preloaded user albums
        self.playlists = []  # Currently displayed playlists/albums (saved + user)
        # --- NEW: Global Sound Engine Setup ---
        self.sound_manager = SoundManager(self)
        self.sound_filter = GlobalSoundFilter(self.sound_manager)
        # Install the filter on the global application instance so it catches EVERYTHING
        QApplication.instance().installEventFilter(self.sound_filter)
        # --------------------------------------
        # Keep top-level window opacity stable; animating full-window opacity can flicker in capture apps.
        self.setWindowOpacity(1.0)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._prev_track_data = None
        self._last_spotify_track_data = None
        self._pending_track_data = None
        self._pending_text_color = None
        self._is_track_transitioning = False
        self._is_paused = False
        self.is_fullscreen = True
        self._saved_geometry = None
        self.is_wallpaper_mode = False
        self.was_wallpaper_mode = False
        self.threadpool = QThreadPool()
        self.font_styles_cache = {}
        self.base_font_families = []
        self._fonts_loaded = False
        self.active_media_source = None # 'spotify', 'apple_music', or 'windows'
        self.spotify_worker = None
        self.apple_music_worker = None
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
        self._current_title_gradient_enabled = False
        self._current_title_gradient_color = [255, 255, 255]
        self._current_title_gradient_direction = "Left to Right"
        self._current_progress_bar_enabled = False
        self._current_album_border_enabled = True
        self._current_text_border_size = 3
        self._current_track_duration = 0
        self._last_progress_sync_time = 0
        self._last_progress_val = 0
        self._last_reported_progress_val = 0
        self._last_applied_album_id = None
        self._incoming_album_changed = True
        self._last_display_state = {
            "title": "Dynamic Player",
            "artist": "Play music on any device to begin",
            "album": "Press 'C' for settings & controls",
        }
        self._active_text_animations = []
        self._idle_pixmap = None
        self._idle_pil_img = None
        self._bg_crossfade_lerp = 0.0
        self.blob_density = 200000 # Default, will be loaded from settings
        self.blob_manager = None
        self.background_renderer = None
        self.notification_only_mode = False
        self.background_only_mode = False
        self._background_only_target_state = False
        self.recent_colors = []
        self._gl_focus_stabilizing = False
        self._gl_stabilize_until_ms = 0
        self._is_closing = False
        self._close_fade_started = False
        self._global_fade = 1.0
        self._startup_fade_done = False
        self._suspend_layout_updates = False
        self._mode_switch_in_progress = False
        self._desktop_parent_hwnd = None
        self._monitor_shift_animating = False
        self._last_monitor_shift_ms = 0
        self._monitor_shift_cooldown_ms = 420
        self._monitor_shift_settle_ms = 180
        self._monitor_hop_fade_out_anim = None
        self._monitor_hop_fade_in_anim = None
        self.drag_pos = None
        self.resize_corner = None  # Track which corner is being dragged: TL, TR, BL, BR, None
        self.resize_start_rect = None  # Store the window rect when resize starts
        self.resize_start_pos = None  # Store the mouse position when resize starts
        self.RESIZE_CORNER_SIZE = 15  # Pixel size for corner detection

        self.multi_monitor_mode = False
        self._was_multi_monitor = False
        self.target_monitor_geo = None
        self.total_screens_geo = None
        self.tray_icon = None

        self.NORMAL_MARGINS = (40, 40, 40, 40) 
        self.VERTICAL_ORIENTATION_MARGINS = (80, 80, 80, 80) 
        self.album_art_target_size_px = 620
        self._current_art_size_px = 620
        self._cached_art_size_px = None
        self._cached_art_is_vertical = None
        self._cached_content_w = 0
        self._cached_content_h = 0
        self._content_line_width_px = 600
        self._lyrics_line_width_px = 520
        self._cur_text_color = QColor(255, 255, 255)
        self._text_alpha = 255
        self.govee_brightness = 1.0
        self.default_govee_brightness = 1.0
        self.lights_enabled = True
        self.spotify_method_enabled = True
        self.apple_music_method_enabled = True
        self.windows_media_method_enabled = True
        self._last_sent_lights_config = None
        self.minimize_to_notification_only = True
        self.player_art_side = "left"
        self.shortcut_bindings = {}
        self._shortcut_key_to_action = {}
        
        self.settings_dialog = None
        self.NORMAL_POLL_INTERVAL = 1000
        self.IDLE_POLL_INTERVAL = 3000
        
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.setInterval(300000) # 5 minutes
        self.idle_timer.timeout.connect(self._on_idle_timeout)

        self._gl_stabilize_timer = QTimer(self)
        self._gl_stabilize_timer.setSingleShot(True)
        self._gl_stabilize_timer.setInterval(220)
        self._gl_stabilize_timer.timeout.connect(self._end_gl_focus_stabilization)

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
        self.lyrics_label = None  # Lyrics: single synced line
        self.player_controls_bar = None  # Optional playback controls row
        self.art_shadow = None
        self.title_shadow = None
        self.artist_shadow = None

        # Playback state for controls bar
        self._shuffle_state = False
        self._repeat_mode = "off"   # 'off', 'context', 'track'
        self._is_liked = False
        self._controls_track_id = None  # track id whose liked state is cached

        # Lyrics state
        self._current_lyrics = []  # [(ms, text), ...]
        self._current_lyric_index = -1

        self.notification_widget = NotificationWidget()
        self.notification_widget.clicked.connect(self._on_notification_clicked)
        
        self.error_notification_widget = NotificationWidget()
        self.error_notification_widget.clicked.connect(self._on_error_notification_clicked)

        try:
            self._idle_pil_img = Image.open(resource_path('icon.ico'))
        except Exception:
            # Fallback if icon is missing or invalid
            self._idle_pil_img = Image.new("RGB", (256, 256), "black")

        # Setup music services - order matters for priority
        did_show_spotify_setup = self._setup_spotify()
        did_show_apple_music_setup = self._setup_apple_music()
        did_show_setup = did_show_spotify_setup or did_show_apple_music_setup
        
        self._load_govee_settings() 
        self.color_cache = ColorCache()
        self.lyrics_cache = LyricsCache()
        self._govee = GoveeController(self.govee_api_key, self.govee_devices)
        self._load_settings()
        self._apply_window_mode_flags()

        if not did_show_setup:
            self._check_for_first_run()

        self._setup_ui()
        self._apply_controls_bar_settings()
        self._setup_background_renderer()
        self._apply_background_only_mode(self.background_only_mode, animate=False)
        self._load_saved_playlists()  # Load saved playlists before preloading new ones
        self._setup_animations()
        self._setup_tray_icon()
        self._setup_timers()
        # Pre-load the settings dialog slowly in the background after a short delay
        QTimer.singleShot(2500, self._setup_settings_dialog)
        self._load_fonts()

        self.overlay = OverlayWidget(self.container)
        self.overlay.hide()
        self.overlay.settings_button.clicked.connect(self.open_settings_dialog)
        self.overlay.listen_mode_button.clicked.connect(self.toggle_listen_mode)
        self.overlay.lights_button.clicked.connect(self.toggle_lights)
        self.overlay.fullscreen_button.clicked.connect(self.toggle_fullscreen_mode)
        self.overlay.switch_monitor_button.clicked.connect(self.switch_monitor)
        self.overlay.multi_monitor_button.clicked.connect(self.toggle_multi_monitor_fullscreen)
        self.overlay.wallpaper_button.clicked.connect(self.toggle_wallpaper_mode)
        self.overlay.background_only_button.clicked.connect(self.toggle_background_only_mode)
        self.overlay.notif_mode_button.clicked.connect(self.toggle_notification_only_mode)

        # --- Playlist/Album Panel (Centered in overlay, triggered by right-click) ---
        self.playlist_panel = PlaylistPanel(self.overlay, main_window=self)
        self.playlist_panel.setVisible(False)
        self.playlist_panel.playlist_selected.connect(self._on_playlist_selected)
        self.playlist_panel.shuffle_requested.connect(self._on_shuffle_playlist)
        # Attach playlist panel to overlay
        self.overlay.set_playlist_panel(self.playlist_panel)
        # Apply saved playlists/albums after panel is created
        if getattr(self, "playlists", None):
            print(f"Applying {len(self.playlists)} saved playlists/albums to panel after creation")
            self.playlist_panel.set_playlists(self.playlists, skip_save=True)

        # Show an initial idle screen.
        QTimer.singleShot(100, self._show_idle_screen)

    def _is_windowed_mode(self):
        return not (self.is_fullscreen or self.multi_monitor_mode or self.is_wallpaper_mode)

    def _is_custom_frameless_windowed_mode(self):
        return self._is_windowed_mode() and bool(self.windowFlags() & Qt.FramelessWindowHint)

    def _clear_native_fullscreen_state(self):
        if self.windowState() & Qt.WindowFullScreen:
            self.setWindowState(self.windowState() & ~Qt.WindowFullScreen)

    def _screen_for_fullscreen(self, preferred_screen=None):
        if preferred_screen:
            return preferred_screen
        screen = QApplication.screenAt(self.geometry().center())
        if screen:
            return screen
        screens = QApplication.screens()
        return screens[0] if screens else None

    def toggle_listen_mode(self):
        self.listen_mode_enabled = not getattr(self, 'listen_mode_enabled', False)
        
        # Save state for the next time the app opens
        settings = QSettings("SpotifySync", "App")
        settings.setValue("listen_mode_active", self.listen_mode_enabled)
        
        if self.listen_mode_enabled:
            # Stop existing media streams
            self._stop_media_workers()
            self.active_media_source = 'microphone'
            
            # Hide Lyrics
            if self.lyrics_label:
                self.lyrics_label.hide()
            
            # Start mic polling
            settings = QSettings("SpotifySync", "App")
            mic_index = settings.value("mic_input_index", type=int)
            if mic_index == -1: mic_index = None # Use default
            
            # --- UPDATE THIS LINE TO PASS THE SPOTIFY CLIENT ---
            self.listen_worker = ListenModeWorker(mic_index, self.sp)
            # ---------------------------------------------------
            
            # Route it directly into Spotify's handler so caching and lights trigger!
            self.listen_worker.signals.track_changed.connect(self._on_spotify_track_changed)
            self.listen_worker.signals.status.connect(lambda msg: print(f"[Listen Mode] {msg}"))
            self.threadpool.start(self.listen_worker)
            
            self.title.setText("Starting Microphone...")
            self.artist.setText("Listen Mode")
            self.album_name.setText("Waiting for music...")
        else:
            if hasattr(self, 'listen_worker') and self.listen_worker:
                self.listen_worker.is_running = False
                self.listen_worker = None
                
            # Bring lyrics back
            if self.lyrics_label:
                self.lyrics_label.show()
                
            self.title.setText("Listen Mode Disabled")
            self._configure_media_workers() # Restarts Spotify/Windows processes

    def _enter_borderless_fullscreen(self, preferred_screen=None):
        """Use monitor-sized frameless geometry instead of native fullscreen state."""
        screen = self._screen_for_fullscreen(preferred_screen)
        self._clear_native_fullscreen_state()
        if self.windowHandle() and screen:
            self.windowHandle().setScreen(screen)
        if screen:
            self.setGeometry(screen.geometry())
        self.show()

    def _begin_mode_switch_transition(self):
        self._mode_switch_in_progress = True
        self._suspend_layout_updates = True
        self.setUpdatesEnabled(False)
        if self.background_renderer and self.background_renderer.uses_opengl:
            self.background_renderer.set_active(False)

    def _finalize_mode_switch_transition(self):
        self._suspend_layout_updates = False
        self.setUpdatesEnabled(True)
        if self.background_renderer and self.background_renderer.uses_opengl:
            self.background_renderer.set_active(True)
            self.background_renderer.tick()
        self.update_layout()
        self._update_text_properties()
        self._force_playlist_panel_relayout()
        self._update_native_titlebar_color()
        self.update()
        self._mode_switch_in_progress = False

    def _apply_window_mode_flags(self):
        if self.is_wallpaper_mode:
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnBottomHint | Qt.Tool)
        elif self._is_windowed_mode():
            self.setWindowFlags(Qt.Window | Qt.WindowSystemMenuHint | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        else:
            self.setWindowFlags(Qt.FramelessWindowHint)

        use_translucent = self.is_wallpaper_mode
        self.setAttribute(Qt.WA_TranslucentBackground, use_translucent)
        self._sync_background_renderer_mode()


    def _current_blended_bg_color(self):
        lerp = max(0.0, min(1.0, float(self._bg_crossfade_lerp)))
        if lerp >= 1.0:
            return QColor(self._current_bg_color)
        if lerp <= 0.0:
            return QColor(self._old_bg_color)

        r = int(self._old_bg_color.red() + (self._current_bg_color.red() - self._old_bg_color.red()) * lerp)
        g = int(self._old_bg_color.green() + (self._current_bg_color.green() - self._old_bg_color.green()) * lerp)
        b = int(self._old_bg_color.blue() + (self._current_bg_color.blue() - self._old_bg_color.blue()) * lerp)
        return QColor(r, g, b)

    def _derive_background_tone_color(self):
        """Derive the background tone from current theme colors instead of forcing pure black."""
        if self._current_ui_palette and len(self._current_ui_palette[0]) >= 3:
            return QColor(*self._current_ui_palette[0])
        if self._current_blob_palette and len(self._current_blob_palette[0]) >= 3:
            return QColor(*self._current_blob_palette[0])
        return QColor("black")

    def _update_native_titlebar_color(self):
        if not IS_WINDOWS:
            return
        if not self._is_windowed_mode() or self._is_custom_frameless_windowed_mode():
            self._last_native_caption_rgb = None
            return

        hwnd = int(self.winId()) if self.winId() else 0
        if not hwnd:
            return

        bg = self._current_blended_bg_color()
        rgb_tuple = (bg.red(), bg.green(), bg.blue())
        if self._last_native_caption_rgb == rgb_tuple:
            return

        colorref = ctypes.c_int(bg.red() | (bg.green() << 8) | (bg.blue() << 16))
        luminance = (0.299 * bg.red()) + (0.587 * bg.green()) + (0.114 * bg.blue())
        text_is_white = luminance < 150
        text_colorref = ctypes.c_int(0x00FFFFFF if text_is_white else 0x00000000)

        DWMWA_BORDER_COLOR = 34
        DWMWA_CAPTION_COLOR = 35
        DWMWA_TEXT_COLOR = 36

        try:
            dwmapi = ctypes.windll.dwmapi
            dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(colorref), ctypes.sizeof(colorref))
            dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(colorref), ctypes.sizeof(colorref))
            dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_TEXT_COLOR, ctypes.byref(text_colorref), ctypes.sizeof(text_colorref))
            self._last_native_caption_rgb = rgb_tuple
        except Exception:
            pass

    def _check_for_first_run(self):
        """Shows a welcome message with instructions on the first launch."""
        settings = QSettings("SpotifySync", "App")
        if settings.value("first_run", "true") == "true":
            tutorial_text = """
            <h2>Welcome to Dynamic Player!</h2>
            <p>Here are some quick tips to get you started:</p>
            <ul>
                <li><b>Play Music:</b> Start playing a song on Spotify, Windows Media Player, or any compatible media source. The display will update automatically.</li>
                <li><b>Media Support:</b> You can use Spotify (with API credentials), Windows Media Player, Apple Music, or other Windows media sources.</li>
                <li><b>Settings:</b> Press the <b>C</b> key to open the settings panel. Here you can customize colors, fonts, light effects, and more for each album.</li>
                <li><b>Fullscreen:</b> Press <b>F</b> to toggle fullscreen mode.</li>
                <li><b>Multi-Monitor:</b> Press <b>F11</b> to span across all your monitors. Use the <b>&larr;</b> and <b>&rarr;</b> arrow keys to shift the content between screens.</li>
                <li><b>Wallpaper Mode:</b> Press <b>F12</b> to enter a 'wallpaper' mode that sits behind your desktop icons. A tray icon will appear to let you exit this mode or open settings.</li>
                <li><b>Exit:</b> Assign a close shortcut in the <b>Shortcuts</b> tab if you want one.</li>
            </ul>
            <p>Enjoy the vibes!</p>
            """
            ThemedMessageBox("Welcome!", tutorial_text, [("Let's Go!", QDialog.Accepted)], self, self._current_bg_color, QColor(*self._current_text_color), QColor(100, 100, 100), self._current_text_border_enabled, QColor(*self._current_text_border_color), self._current_text_border_size).exec_()
            settings.setValue("first_run", False)

    def _show_idle_screen(self):
        """Displays a default idle screen when no music is playing."""
        if self._prev_track_data: # Don't show if a track was just playing and we are fading out
            return  # Early exit if a track was just playing

        self._current_ui_palette = [[0, 0, 0], [255, 255, 255]]
        self._current_blob_palette = [
            [SPOTIFY_GREEN[0], SPOTIFY_GREEN[1], SPOTIFY_GREEN[2]],
            [10, 100, 40],
            [15, 150, 60],
        ]
        self._update_blobs()
        self.art.setAspectRatio(1.0)
        if self._idle_pil_img:
            self._set_album_art(self._idle_pil_img)
        self.art.setBorderColor(QColor("transparent"))
        self.art.setLoadingState(False)

        self._current_lyrics = []
        self._current_lyric_index = -1
        if self.lyrics_label:
            self.lyrics_label.reset()
            self.lyrics_label.show()

        self.title.setText("Dynamic Player")
        self.artist.setText("Play music on any device to begin")
        self.album_name.setText("Press 'C' for settings & controls")
        self._last_display_state = {
            "title": self.title.text(),
            "artist": self.artist.text(),
            "album": self.album_name.text(),
        }
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

    def _compute_preferred_art_size(self, content_w, content_h, is_vertical):
        if is_vertical:
            text_reserve = 300
            max_size = int(min(content_w - 40, content_h - text_reserve))
        else:
            horizontal_gap = 20
            max_size = int(min(content_h - 40, (content_w - horizontal_gap) * 0.45))

        return max(180, max_size)

    def _sync_art_and_lyrics_bounds(self, content_w, content_h, is_vertical, preferred_art_size):
        if is_vertical:
            text_line_width = int(content_w * 0.9)
            lyrics_width = int(content_w * 0.85)
            art_size = int(min(content_w * 0.8, content_h * 0.45))
        else:
            # WIDESCREEN BALANCE: Give art and text equal footing
            art_size = int(min(content_h * 0.8, content_w * 0.4))
            art_size = max(200, min(800, art_size))
            
            # Match the text lane width directly to the art size for perfect visual symmetry
            details_lane_width = art_size
            text_line_width = int(details_lane_width * 0.95)
            lyrics_width = text_line_width

        self._current_art_size_px = art_size
        self.art.setFixedSize(art_size, art_size)
        self.art_container.setFixedSize(art_size, art_size)
        self._content_line_width_px = text_line_width
        self._lyrics_line_width_px = lyrics_width

        self.title.setFixedWidth(text_line_width)
        self.album_name.setFixedWidth(text_line_width)
        self.artist.setFixedWidth(text_line_width)
        self.progress_bar.setFixedWidth(text_line_width)
        if self.lyrics_label:
            self.lyrics_label.setFixedWidth(lyrics_width)

    def _load_govee_settings(self):
        settings = QSettings("SpotifySync", "App")
        # Force conversion to string to prevent type errors
        self.govee_api_key = str(settings.value("govee_api_key", ""))  # Ensure API key is a string
        
        dev_val = settings.value("govee_devices", "[]")
        try:
            # Handle case where QSettings returns bytes or other types
            if isinstance(dev_val, (bytes, bytearray)):
                dev_val = dev_val.decode('utf-8')
            
            if isinstance(dev_val, str):
                self.govee_devices = json.loads(dev_val)
            else:
                # If it's not a string, it might be junk data or already parsed
                self.govee_devices = []
            
            # Final validation: Govee devices must be a list
            if not isinstance(self.govee_devices, list):
                self.govee_devices = []
                
        except (json.JSONDecodeError, TypeError, ValueError):
            self.govee_devices = []

    def _has_spotify_credentials(self):
        settings = QSettings("SpotifySync", "App")
        client_id = str(settings.value("spotify_client_id", "") or "").strip()
        client_secret = str(settings.value("spotify_client_secret", "") or "").strip()
        return bool(client_id and client_secret)

    def _has_apple_music_credentials(self):
        settings = QSettings("SpotifySync", "App")
        team_id = str(settings.value("apple_music_team_id", "") or "").strip()
        key_id = str(settings.value("apple_music_key_id", "") or "").strip()
        private_key = str(settings.value("apple_music_private_key", "") or "").strip()
        return bool(team_id and key_id and private_key)

    def _is_media_method_enabled(self, source):
        if source == 'spotify':
            return bool(self.spotify_method_enabled and self.sp)
        if source == 'apple_music':
            return bool(self.apple_music_method_enabled and IS_WINDOWS)
        if source == 'windows':
            return bool(self.windows_media_method_enabled and IS_WINDOWS)
        return False

    def _is_lights_source_allowed(self, source):
        return source in {'spotify', 'apple_music'} and self._is_media_method_enabled(source)

    def _stop_media_workers(self):
        if getattr(self, 'spotify_worker', None):
            self.spotify_worker.stop()
            self.spotify_worker = None
        if IS_WINDOWS:
            if getattr(self, 'apple_music_worker', None):
                self.apple_music_worker.stop()
                self.apple_music_worker = None
            if getattr(self, 'windows_worker', None):
                self.windows_worker.stop()
                self.windows_worker = None

    def _configure_media_workers(self):
        self._stop_media_workers()

        if self._is_media_method_enabled('spotify'):
            self.spotify_worker = SpotifyPollingWorker(self.sp)
            self.spotify_worker.signals.track_changed.connect(self._on_spotify_track_changed)
            self.spotify_worker.signals.playback_state_changed.connect(self._on_playback_state_changed)
            self.spotify_worker.signals.no_playback.connect(self._on_spotify_no_playback)
            self.threadpool.start(self.spotify_worker)

        if IS_WINDOWS and self._is_media_method_enabled('apple_music'):
            self.apple_music_worker = AppleMusicPollingWorker(self.apple_music_client)
            self.apple_music_worker.signals.track_changed.connect(self._on_apple_music_track_changed)
            self.apple_music_worker.signals.no_playback.connect(self._on_apple_music_no_playback)
            self.threadpool.start(self.apple_music_worker)

        if IS_WINDOWS and self._is_media_method_enabled('windows'):
            self.windows_worker = WindowsMediaWorker()
            self.windows_worker.signals.track_changed.connect(self._on_windows_track_changed)
            self.windows_worker.signals.no_playback.connect(self._on_windows_no_playback)
            self.threadpool.start(self.windows_worker)

    def _validate_spotify_credentials(self, client_id, client_secret):
        """Validate Spotify credentials format and content."""
        # Convert to string and strip whitespace
        client_id = str(client_id).strip() if client_id else ""
        client_secret = str(client_secret).strip() if client_secret else ""
        
        # Check for minimum length and invalid patterns (e.g., placeholder text)
        if not client_id or not client_secret:
            return False, "Credentials are empty"
        
        # Check for common invalid patterns (too short, contains spaces that shouldn't be there, etc)
        if len(client_id) < 20 or len(client_secret) < 20:
            return False, "Credentials appear malformed (too short)"
        
        # Check if they look like they might contain QSettings artifacts or corruption
        if any(bad in str(client_id).lower() or bad in str(client_secret).lower() 
               for bad in ["@invalid", "@@", "qvariant", "null", "undefined", "none"]):
            return False, "Credentials appear corrupted"
        
        return True, None

    def _get_spotify_cache_path(self):
        """Return a stable token cache file path under AppData."""
        cache_dir = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        if not cache_dir:
            cache_dir = os.path.join(os.path.expanduser("~"), ".dynamic-player")

        try:
            os.makedirs(cache_dir, exist_ok=True)
        except OSError:
            # Final fallback if AppData path creation fails.
            return os.path.join(os.path.abspath("."), ".spotipy-token-cache")

        return os.path.join(cache_dir, "spotipy-token-cache")

    def _build_spotify_auth_manager(self, client_id, client_secret):
        cache_handler = CacheFileHandler(cache_path=self._get_spotify_cache_path())
        return SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=SPOTIPY_REDIRECT_URI,
            scope=SPOTIFY_SCOPE,
            open_browser=True,
            cache_handler=cache_handler,
        )

    def _setup_spotify(self):
        settings = QSettings("SpotifySync", "App")
        did_show_setup_dialog = False
        self.sp = None  # Initialize to None; will be set if credentials provided
        
        # Check if user previously chose to skip Spotify setup
        if settings.value("spotify_setup_skipped", "false") == "true":
            return False
        
        while True:
            # Check if we should force Spotify setup (e.g., after reset with keep_data)
            # This is inside the loop so it gets re-evaluated after the dialog closes
            force_setup = settings.value("force_spotify_setup", "false") == "true"
            
            client_id = settings.value("spotify_client_id")
            client_secret = settings.value("spotify_client_secret")
            
            # Validate credential format - catch corrupted/incomplete saved credentials
            is_valid, validation_error = self._validate_spotify_credentials(client_id, client_secret)
            if not is_valid:
                print(f"Spotify credentials validation failed: {validation_error}. Clearing corrupted credentials.")
                settings.remove("spotify_client_id")
                settings.remove("spotify_client_secret")
                settings.sync()
                client_id = None
                client_secret = None
                force_setup = True  # Force setup dialog to show

            if (not client_id or not client_secret) or force_setup:
                did_show_setup_dialog = True
                # Clear the force flag so it doesn't show again on next startup
                settings.remove("force_spotify_setup")
                settings.sync()
                
                dialog = SpotifySetupDialog()
                result = dialog.exec_()
                if result == SpotifySetupDialog.SKIP_CODE:
                    # User chose to skip Spotify setup - remember this decision
                    settings.setValue("spotify_setup_skipped", "true")
                    settings.sync()
                    self.sp = None
                    break
                elif result != QDialog.Accepted:
                    # User cancelled, exit app
                    sys.exit(0)
                continue # Loop again to load the new settings

            try:
                auth_manager = self._build_spotify_auth_manager(client_id, client_secret)
                self.sp = Spotify(auth_manager=auth_manager)
                # Avoid blocking startup in frozen builds. spotipy can fall back to console-style
                # auth input if callback handling fails, which deadlocks windowed executables.
                if not getattr(sys, "frozen", False):
                    # In dev, keep eager validation to catch credential issues early.
                    self.sp.me()
                else:
                    print("Frozen build: skipping eager Spotify auth check during startup.")
                # Clear skip flag since user successfully configured Spotify
                settings.remove("spotify_setup_skipped")
                settings.sync()
                break # Success, exit loop
            except Exception as e:
                print(f"Failed to initialize Spotify. Please check credentials. Error: {e}")
                
                # Determine if this is likely a credential corruption issue vs a transient network issue
                error_str = str(e).lower()
                is_likely_corruption = any(keyword in error_str for keyword in 
                    ["invalid_client", "unauthorized", "invalid_grant", "malformed", "400"])
                
                # Auto-recover from credential corruption by clearing credentials and retrying
                if is_likely_corruption:
                    print("Detected credential corruption. Clearing credentials and retrying...")
                    settings.remove("spotify_client_id")
                    settings.remove("spotify_client_secret")
                    settings.sync()
                    continue  # Loop will show setup dialog again with fresh credentials
                
                # For network issues, ask user what to do
                msg = ThemedMessageBox("Spotify Authentication Error",
                    f"Spotify authentication failed.\n\nError: {e}\n\n"
                    "Do you want to reset your saved Client ID and Secret?\n"
                    "(Yes to reset and retry, No to retry with current details, Skip to use Windows Media Player instead)",
                    [("Yes", QDialog.Accepted), ("No", QDialog.Rejected), ("Skip", 2)], self, self._current_bg_color, self._current_text_color, QColor(100, 100, 100), self._current_text_border_enabled, QColor(*self._current_text_border_color), self._current_text_border_size)

                res = msg.exec_()
                if res == QDialog.Accepted:
                    settings.remove("spotify_client_id")
                    settings.remove("spotify_client_secret")
                    settings.sync()
                    continue  # Loop again to show setup dialog
                elif res == 2:
                    # User chose to skip Spotify - remember this decision
                    settings.setValue("spotify_setup_skipped", "true")
                    settings.sync()
                    self.sp = None
                    break
                # If "No", loop continues and retries with same credentials
        return did_show_setup_dialog

    def _setup_apple_music(self):
        """Setup Apple Music API client with developer credentials."""
        settings = QSettings("SpotifySync", "App")
        did_show_setup_dialog = False
        self.apple_music_client = None  # Initialize to None
        
        # Check if user previously chose to skip Apple Music setup
        if settings.value("apple_music_setup_skipped", "false") == "true":
            return False
        
        while True:
            # Check if we should force Apple Music setup
            force_setup = settings.value("force_apple_music_setup", "false") == "true"
            
            team_id = settings.value("apple_music_team_id")
            key_id = settings.value("apple_music_key_id")
            private_key = settings.value("apple_music_private_key")
            
            if (not team_id or not key_id or not private_key) or force_setup:
                did_show_setup_dialog = True
                # Clear the force flag
                settings.remove("force_apple_music_setup")
                settings.sync()
                
                dialog = AppleMusicSetupDialog()
                result = dialog.exec_()
                if result == AppleMusicSetupDialog.SKIP_CODE:
                    # User chose to skip Apple Music setup - remember this decision
                    settings.setValue("apple_music_setup_skipped", "true")
                    settings.sync()
                    self.apple_music_client = None
                    break
                elif result != QDialog.Accepted:
                    # User cancelled - continue with basic integration
                    self.apple_music_client = None
                    break
                continue  # Loop again to load the new settings
            
            try:
                # Create Apple Music client
                self.apple_music_client = AppleMusicClient(
                    team_id=team_id,
                    key_id=key_id,
                    private_key=private_key
                )
                
                # Set user token if available
                user_token = settings.value("apple_music_user_token")
                if user_token:
                    self.apple_music_client.set_user_token(user_token)
                
                # Test if token generation works
                if not self.apple_music_client.developer_token:
                    raise Exception("Failed to generate developer token. Check credentials and ensure PyJWT is installed.")
                
                # Clear skip flag since user successfully configured Apple Music
                settings.remove("apple_music_setup_skipped")
                settings.sync()
                print("Apple Music API initialized successfully")
                break  # Success, exit loop
            except Exception as e:
                print(f"Failed to initialize Apple Music API: {e}")
                
                msg = ThemedMessageBox("Apple Music API Error",
                    f"Apple Music API initialization failed.\n\nError: {e}\n\n"
                    "Do you want to reset your saved credentials?\n"
                    "(Yes to reset and retry, No to retry with current details, Skip to use basic integration)",
                    [("Yes", QDialog.Accepted), ("No", QDialog.Rejected), ("Skip", 2)], 
                    self, self._current_bg_color, QColor(*self._current_text_color), QColor(100, 100, 100), 
                    self._current_text_border_enabled, QColor(*self._current_text_border_color), self._current_text_border_size)
                
                res = msg.exec_()
                if res == QDialog.Accepted:
                    settings.remove("apple_music_team_id")
                    settings.remove("apple_music_key_id")
                    settings.remove("apple_music_private_key")
                    settings.remove("apple_music_user_token")
                elif res == 2:
                    # User chose to skip Apple Music API - remember this decision
                    settings.setValue("apple_music_setup_skipped", "true")
                    settings.sync()
                    self.apple_music_client = None
                    break
        return did_show_setup_dialog

    def _load_settings(self):
        settings = QSettings("SpotifySync", "App")
        
        # --- Helper for safe casting ---
        def safe_cast(val, type_func, default):
            try:
                if val is None: return default
                return type_func(val)
            except (ValueError, TypeError):
                return default

        def as_bool(val, default):
            if val is None: return default
            if isinstance(val, bool): return val
            return str(val).lower() == 'true'
        # -------------------------------

        # Geometry
        val = settings.value("geometry")
        if isinstance(val, QRect):
            self.setGeometry(val)
        else:
            self.setGeometry(QRect(100, 100, 600, 700))

        # Booleans
        self.is_fullscreen = as_bool(settings.value("fullscreen"), True)
        self.multi_monitor_mode = as_bool(settings.value("multi_monitor_mode"), False)
        self._start_in_wallpaper = as_bool(settings.value("start_in_wallpaper_mode"), False)
        self.lights_enabled = as_bool(settings.value("lights_enabled"), True)
        self.govee_brightness_override = as_bool(settings.value("govee_brightness_override"), False)
        self.minimize_to_notification_only = as_bool(settings.value("minimize_to_notification_only"), True)
        self.background_only_mode = as_bool(settings.value("background_only_mode"), False)
        self.spotify_method_enabled = as_bool(
            settings.value("spotify_method_enabled"),
            self._has_spotify_credentials()
        )
        self.apple_music_method_enabled = as_bool(
            settings.value("apple_music_method_enabled"),
            self._has_apple_music_credentials()
        )
        self.windows_media_method_enabled = as_bool(
            settings.value("windows_media_method_enabled"),
            True
        )

        # Numbers
        self.default_govee_brightness = safe_cast(settings.value("default_govee_brightness"), float, 1.0)
        # Fallback to legacy key if needed
        if settings.value("default_govee_brightness") is None:
             self.default_govee_brightness = safe_cast(settings.value("govee_brightness"), float, 1.0)

        self.blob_density = int(safe_cast(settings.value("blob_density"), float, 200000))
        self.lava_lamp_preset = "color_pop"
        
        sound_vol = safe_cast(settings.value("sound_volume"), float, 0.5)
        self.sound_manager.set_master_volume(sound_vol)

        # Fonts & Defaults
        self.default_font_family = str(settings.value("default_font_family", "Trebuchet MS"))
        self.default_font_style = str(settings.value("default_font_style", "Bold"))
        self.default_font_size_scale = int(safe_cast(settings.value("default_font_size_scale"), float, 100))
        self.default_progress_bar_enabled = as_bool(settings.value("default_progress_bar_enabled"), False)
        self.default_text_border_enabled = as_bool(settings.value("default_text_border_enabled"), False)
        self.default_text_border_size = int(safe_cast(settings.value("default_text_border_size"), float, 3))
        self.track_transition_duration_ms = int(max(250, min(2200, safe_cast(settings.value("track_transition_duration_ms"), int, 800))))
        self.track_transition_easing = str(settings.value("track_transition_easing", "Out Cubic") or "Out Cubic")
        saved_art_side = str(settings.value("player_art_side", "left")).strip().lower()
        self.player_art_side = "right" if saved_art_side == "right" else "left"

        # Player controls bar settings
        self.default_show_player_controls = as_bool(settings.value("default_show_player_controls"), False)
        self.default_controls_play_pause  = as_bool(settings.value("default_controls_play_pause"),  True)
        self.default_controls_shuffle     = as_bool(settings.value("default_controls_shuffle"),     True)
        self.default_controls_repeat      = as_bool(settings.value("default_controls_repeat"),      True)
        self.default_controls_add_playlist = as_bool(settings.value("default_controls_add_playlist"), True)
        self.default_controls_liked       = as_bool(settings.value("default_controls_liked"),       True)

        # Recent Colors (JSON)
        recent_colors_str = settings.value("recent_colors", "[]")
        try:
            if isinstance(recent_colors_str, str):
                loaded = json.loads(recent_colors_str)
            else:
                loaded = [] 
            
            if isinstance(loaded, list):
                self.recent_colors = [QColor(name) for name in loaded]
            else:
                self.recent_colors = []
        except (json.JSONDecodeError, TypeError, ValueError):
            self.recent_colors = []

        # Multi-monitor Logic
        if self.multi_monitor_mode:
            target_geo = settings.value("target_monitor_geo")
            if isinstance(target_geo, QRect):
                self.target_monitor_geo = target_geo
                screens = QApplication.screens()
                if screens:
                    total_rect = QRect()
                    for screen in screens: total_rect = total_rect.united(screen.geometry())
                    self.total_screens_geo = total_rect
                    
                    # Validate that target_geo is actually within total_screens_geo
                    if not total_rect.intersects(target_geo):
                        self.multi_monitor_mode = False
                        self.setGeometry(QRect(100, 100, 600, 700))
                    else:
                        self.setWindowFlags(Qt.FramelessWindowHint)
                        self.setGeometry(total_rect)
            else:
                self.multi_monitor_mode = False
                self.setWindowFlags(Qt.FramelessWindowHint)
                self.setGeometry(self.geometry())
        else:
            self.setGeometry(self.geometry())

        self._load_shortcuts(settings)

    def get_shortcut_definitions(self):
        return [dict(item) for item in self.SHORTCUT_DEFINITIONS]

    def get_shortcut_bindings(self):
        return dict(self.shortcut_bindings)

    def _default_shortcut_bindings(self):
        return {item["id"]: str(item.get("default", "")) for item in self.SHORTCUT_DEFINITIONS}

    def _normalize_shortcut_text(self, key_text):
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

    def _sanitize_shortcut_bindings(self, bindings):
        sanitized = {}
        used_keys = set()
        defaults = self._default_shortcut_bindings()

        for definition in self.SHORTCUT_DEFINITIONS:
            action_id = definition["id"]
            raw_key = bindings.get(action_id, defaults.get(action_id, "")) if isinstance(bindings, dict) else defaults.get(action_id, "")
            key_text = self._normalize_shortcut_text(raw_key)

            if key_text and key_text not in used_keys:
                sanitized[action_id] = key_text
                used_keys.add(key_text)
            else:
                sanitized[action_id] = ""

        return sanitized

    def _rebuild_shortcut_lookup(self):
        self._shortcut_key_to_action = {}
        for action_id, key_text in self.shortcut_bindings.items():
            normalized = self._normalize_shortcut_text(key_text)
            if normalized:
                self._shortcut_key_to_action[normalized] = action_id

    def _load_shortcuts(self, settings):
        defaults = self._default_shortcut_bindings()
        loaded = {}

        raw = settings.value("keyboard_shortcuts", "")
        if isinstance(raw, dict):
            loaded = raw
        elif isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    loaded = parsed
            except (json.JSONDecodeError, TypeError, ValueError):
                loaded = {}

        merged = defaults.copy()
        for action_id, value in (loaded.items() if isinstance(loaded, dict) else []):
            merged[action_id] = value

        self.shortcut_bindings = self._sanitize_shortcut_bindings(merged)
        self._rebuild_shortcut_lookup()

    def apply_shortcut_bindings(self, bindings, persist=True):
        merged = self._default_shortcut_bindings()
        if isinstance(bindings, dict):
            merged.update(bindings)

        self.shortcut_bindings = self._sanitize_shortcut_bindings(merged)
        self._rebuild_shortcut_lookup()

        if persist:
            settings = QSettings("SpotifySync", "App")
            settings.setValue("keyboard_shortcuts", json.dumps(self.shortcut_bindings))

    def _event_to_shortcut_text(self, event):
        modifiers = int(event.modifiers()) & ~int(Qt.KeypadModifier)
        if modifiers:
            return ""

        key = event.key()
        if key in (Qt.Key_unknown, Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr):
            return ""

        return self._normalize_shortcut_text(QKeySequence(key).toString(QKeySequence.NativeText))

    def _handle_shift_shortcut(self, direction):
        if self.multi_monitor_mode or (self.is_wallpaper_mode and hasattr(self, '_was_multi_monitor') and self._was_multi_monitor):
            self.shift_multi_monitor_content(direction)
        elif self.is_fullscreen:
            self.shift_single_monitor_fullscreen(direction)

        if hasattr(self, 'playlist_panel') and self.playlist_panel:
            QTimer.singleShot(100, self.playlist_panel.relayout)

    def _trigger_shortcut_action(self, action_id):
        if action_id == "close_app":
            self.close()
            return True
        if action_id == "toggle_fullscreen":
            self._handle_fullscreen_hotkey()
            return True
        if action_id == "toggle_multi_monitor":
            if self.is_wallpaper_mode:
                return True
            self.toggle_multi_monitor_fullscreen()
            return True
        if action_id == "toggle_wallpaper":
            self.toggle_wallpaper_mode()
            return True
        if action_id == "shift_left":
            self._handle_shift_shortcut(-1)
            return True
        if action_id == "shift_right":
            self._handle_shift_shortcut(1)
            return True
        if action_id == "toggle_lights":
            self.toggle_lights()
            return True
        if action_id == "open_settings":
            self.open_settings_dialog()
            return True
        return False

    def _save_settings(self):
        settings = QSettings("SpotifySync", "App")
        settings.setValue("geometry", self.geometry())
        settings.setValue("fullscreen", "true" if self.is_fullscreen else "false")
        settings.setValue("lights_enabled", "true" if self.lights_enabled else "false")
        settings.setValue("default_govee_brightness", self.default_govee_brightness)
        
        # --- NEW: Save Override ---
        settings.setValue("govee_brightness_override", "true" if self.govee_brightness_override else "false")
        geom = getattr(self, '_saved_geometry', None) or self.geometry()
        settings.setValue("geometry", geom)
        settings.setValue("blob_density", self.blob_density)
        settings.setValue("start_in_wallpaper_mode", "true" if self.is_wallpaper_mode else "false")
        settings.setValue("background_only_mode", "true" if self.background_only_mode else "false")
        settings.setValue("spotify_method_enabled", "true" if self.spotify_method_enabled else "false")
        settings.setValue("apple_music_method_enabled", "true" if self.apple_music_method_enabled else "false")
        settings.setValue("windows_media_method_enabled", "true" if self.windows_media_method_enabled else "false")

        if self.is_wallpaper_mode:
            settings.setValue("geometry", self._saved_geometry)
            settings.setValue("fullscreen", "true" if self._was_fullscreen else "false")
            settings.setValue("multi_monitor_mode", "true" if self._was_multi_monitor else "false")
            if self._was_multi_monitor:
                settings.setValue("target_monitor_geo", self._saved_target_monitor_geo)
        else:
            settings.setValue("geometry", self.geometry())
            settings.setValue("fullscreen", "true" if self.is_fullscreen else "false")
            settings.setValue("multi_monitor_mode", "true" if self.multi_monitor_mode else "false")
            if self.multi_monitor_mode:
                settings.setValue("target_monitor_geo", self.target_monitor_geo)

        recent_colors_names = [c.name(QColor.HexRgb) for c in self.recent_colors]
        settings.setValue("recent_colors", json.dumps(recent_colors_names))
        settings.setValue("lava_lamp_preset", "color_pop")

    def _setup_ui(self):
        self.setWindowTitle("Dynamic Player")
        self.setWindowIcon(QIcon(resource_path('icon.ico')))
        self.setMinimumSize(400, 500)
        
        self.container = QWidget(self)
        self.container.setStyleSheet("background-color: transparent;")
        self.setCentralWidget(self.container)
        
        # Enable mouse tracking for hover detection
        self.setMouseTracking(True)
        self.container.setMouseTracking(True)
        
        self.main_layout = QBoxLayout(QBoxLayout.TopToBottom)
        self.main_layout.setSpacing(20)
        self.container.setLayout(self.main_layout)

        # Art and details widgets
        self.art_container = QWidget()
        self.art_container.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        art_container_layout = QVBoxLayout(self.art_container)
        art_container_layout.setContentsMargins(0,0,0,0)
        self.title_shadow = QGraphicsDropShadowEffect(self)
        self.artist_shadow = QGraphicsDropShadowEffect(self)
        self.art = ResponsiveAlbumArtLabel(radius=15)
        self.art.setFixedSize(self.album_art_target_size_px, self.album_art_target_size_px)
        self.art_container.setFixedSize(self.album_art_target_size_px, self.album_art_target_size_px)

        # --- Details layout must be created before use ---
        self.details_widget = QWidget()
        self.details_layout = QVBoxLayout(self.details_widget)
        self.details_layout.setSpacing(15)
        self.details_layout.setContentsMargins(20, 0, 20, 0)

        font_family = "Trebuchet MS" if "Trebuchet MS" in QFontDatabase().families() else "Sans Serif"
        self.title = ScrollingTextLabel("–")
        self.title.setFont(QFont(font_family, 23, QFont.Bold))
        self.title.setGraphicsEffect(self.title_shadow) 
        self.title.setStyleSheet("background: transparent;")
        self.title.setMaxLines(2)
        self.title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.album_name = ScrollingTextLabel("–")
        self.album_name.setFont(QFont(font_family, 16))
        self.album_name.setGraphicsEffect(QGraphicsDropShadowEffect(self))
        self.album_name.setStyleSheet("background: transparent;")
        self.album_name.setMaxLines(2)
        self.album_name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.artist = ScrollingTextLabel("–")
        self.artist.setFont(QFont(font_family, 18))
        self.artist.setGraphicsEffect(self.artist_shadow) 
        self.artist.setStyleSheet("background: transparent;")
        self.artist.setMaxLines(2)
        self.artist.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.progress_bar = SmoothProgressBar()

        self.lyrics_shadow = QGraphicsDropShadowEffect(self)
        self.lyrics_label = LyricsLabel()
        self.lyrics_label.setFont(QFont(font_family, 18))
        self.lyrics_label.setStyleSheet("background: transparent;")
        self.lyrics_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.lyrics_label.setMaxLines(2)
        self.lyrics_label.setFixedHeight(56)
        self.lyrics_label.setGraphicsEffect(self.lyrics_shadow)
        # Keep visible so lyrics space is always reserved and layout does not jitter.
        self.lyrics_label.show()

        # Player controls bar (below lyrics)
        self.player_controls_bar = PlayerControlsBar()
        self.player_controls_bar.play_pause_clicked.connect(self._action_play_pause)
        self.player_controls_bar.shuffle_clicked.connect(self._action_shuffle)
        self.player_controls_bar.repeat_clicked.connect(self._action_repeat)
        self.player_controls_bar.add_playlist_clicked.connect(self._action_add_to_playlist)
        self.player_controls_bar.liked_clicked.connect(self._action_liked)

        self.details_layout.addWidget(self.title)
        self.details_layout.insertWidget(1, self.album_name)
        self.details_layout.addWidget(self.artist)
        self.details_layout.addWidget(self.progress_bar)
        self.details_layout.addWidget(self.lyrics_label)
        self.details_layout.addWidget(self.player_controls_bar, 0, Qt.AlignCenter)

        art_container_layout.addWidget(self.art, 0, Qt.AlignCenter)

        self.main_layout.addStretch(1)
        self.main_layout.addWidget(self.art_container, 5)
        self.main_layout.addWidget(self.details_widget, 2, Qt.AlignCenter)
        self.main_layout.addStretch(1)

        self.title.setAlignment(Qt.AlignCenter)
        self.artist.setAlignment(Qt.AlignCenter)
        self.details_layout.setAlignment(Qt.AlignCenter)
        
        self.update_art_shadow_properties()
        self.setTextAlpha(self._text_alpha)

        self._content_fade_anim = QVariantAnimation(self)
        self._content_fade_anim.setDuration(260)
        self._content_fade_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._content_fade_anim.valueChanged.connect(self._set_player_content_opacity)
        self._content_fade_anim.finished.connect(self._on_content_fade_finished)
        self._set_player_content_opacity(1.0)

    def _apply_controls_bar_settings(self):
        """Show/hide individual player control buttons based on saved settings."""
        visible = set()
        if getattr(self, 'default_controls_play_pause', True):
            visible.add("play_pause")
        if getattr(self, 'default_controls_shuffle', True):
            visible.add("shuffle")
        if getattr(self, 'default_controls_repeat', True):
            visible.add("repeat")
        if getattr(self, 'default_controls_add_playlist', True):
            visible.add("add_playlist")
        if getattr(self, 'default_controls_liked', True):
            visible.add("liked")
        show_bar = getattr(self, 'default_show_player_controls', False)
        if not show_bar:
            visible = set()
        self.player_controls_bar.set_visible_buttons(visible)

    def _setup_background_renderer(self):
        self.background_renderer = BackgroundRendererController(self)
        self.background_renderer.set_style_preset("color_pop")
        self._sync_background_renderer_mode()
        if self.background_renderer.supports_gl:
            print(f"Background renderer: OpenGL available ({self.background_renderer.support_reason})")
        else:
            print(f"Background renderer: Raster fallback ({self.background_renderer.support_reason})")

    def _sync_background_renderer_mode(self):
        if not self.background_renderer:
            return
        changed = self.background_renderer.update_mode(
            is_wallpaper_mode=self.is_wallpaper_mode,
            is_custom_windowed_mode=self._is_custom_frameless_windowed_mode(),
        )
        if not self.background_renderer.uses_opengl:
            self._gl_focus_stabilizing = False
            self._gl_stabilize_until_ms = 0
            self._gl_stabilize_timer.stop()
        self.background_renderer.resize(self.rect())
        if changed:
            self._update_blobs()
            self.update()

    def _start_gl_focus_stabilization(self):
        if not (IS_WINDOWS and self.background_renderer and self.background_renderer.uses_opengl):
            return
        # Briefly pause GL updates when focus changes to reduce capture-hook flicker bursts.
        self._gl_focus_stabilizing = True
        self._gl_stabilize_until_ms = QDateTime.currentMSecsSinceEpoch() + 220
        self.background_renderer.set_active(False)
        self._gl_stabilize_timer.start()

    def _end_gl_focus_stabilization(self):
        self._gl_focus_stabilizing = False
        self._gl_stabilize_until_ms = 0
        if self.background_renderer and self.background_renderer.uses_opengl:
            self.background_renderer.set_active(True)
            self.background_renderer.tick()

    def _on_minimize_requested(self):
        if self.tray_icon:
            if not self.notification_only_mode:
                if self.isMinimized():
                    self.showNormal()
                self.toggle_notification_only_mode()
            return
        self.showMinimized()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            if self.isMinimized() and self.tray_icon and not self.notification_only_mode:
                QTimer.singleShot(0, self._on_minimize_requested)
        elif event.type() == QEvent.WindowActivate:
            self._start_gl_focus_stabilization()
        elif event.type() == QEvent.WindowDeactivate:
            if self._gl_focus_stabilizing:
                self._end_gl_focus_stabilization()

    def _load_saved_playlists(self):
        """Load saved playlists and albums from QSettings and display them."""
        settings = QSettings("SpotifySync", "App")
        saved = settings.value("user_playlists", "[]")
        try:
            if isinstance(saved, str):
                items = json.loads(saved)
            else:
                items = saved if isinstance(saved, list) else []
            
            # Always initialize self.playlists
            self.playlists = items if items else []
            
            if items:
                print(f"Loaded {len(items)} playlists/albums from settings")
                # Ensure cover art and item_type for each item
                for item in items:
                    if item.get('id'):
                        item_type = item.get('item_type', 'playlist')
                        if not item.get('uri'):
                            item['uri'] = f"spotify:{item_type}:{item.get('id')}"
                    if not item.get('cover_art_b64'):
                        item['cover_art_b64'] = self._fetch_and_encode_cover_art(item)
                # Store items for later application after panel is created
                self.playlists = items
                if hasattr(self, 'playlist_panel'):
                    self.playlist_panel.set_playlists(items, skip_save=True)
        except Exception as e:
            print(f"Error loading saved playlists: {e}")
            self.playlists = []

    def _get_user_playlists(self):
        """Fetch user playlists from all configured services (Spotify + Apple Music)."""
        all_playlists = []
        
        # Fetch from Spotify
        if self._user_playlists and not any(p.get('source') == 'apple_music' for p in self._user_playlists):
            # Only return cached if it doesn't contain Apple Music items
            return self._user_playlists
        
        try:
            if self.sp:
                sp = self._get_spotify_client()
                playlists = []
                limit = 50
                offset = 0
                while True:
                    resp = sp.current_user_playlists(limit=limit, offset=offset)
                    for pl in resp.get('items', []):
                        playlist_data = {
                            'name': pl['name'],
                            'id': pl['id'],
                            'uri': pl.get('uri') or f"spotify:playlist:{pl['id']}",
                            'images': pl.get('images', []),
                            'item_type': 'playlist',
                            'source': 'spotify'
                        }
                        playlists.append(playlist_data)
                    if resp.get('next'):
                        offset += limit
                    else:
                        break
                all_playlists.extend(playlists)
                print(f"Fetched {len(playlists)} Spotify playlists")
        except Exception as e:
            print(f"Error fetching Spotify playlists: {e}")
        
        # Fetch from Apple Music
        try:
            if self.apple_music_client and self.apple_music_client.developer_token:
                am_playlists = self.apple_music_client.get_user_playlists(limit=100)
                for pl in am_playlists:
                    attrs = pl.get('attributes', {})
                    artwork = attrs.get('artwork', {})
                    images = []
                    if artwork and artwork.get('url'):
                        # Apple Music uses template URLs
                        art_url = artwork['url'].replace('{w}', '300').replace('{h}', '300')
                        images = [{'url': art_url, 'width': 300, 'height': 300}]
                    
                    playlist_data = {
                        'name': attrs.get('name', 'Unknown Playlist'),
                        'id': pl.get('id', ''),
                        'uri': f"applemusic:playlist:{pl.get('id', '')}",
                        'images': images,
                        'item_type': 'playlist',
                        'source': 'apple_music'
                    }
                    all_playlists.append(playlist_data)
                print(f"Fetched {len(am_playlists)} Apple Music playlists")
        except Exception as e:
            print(f"Error fetching Apple Music playlists: {e}")
        
        self._user_playlists = all_playlists
        return all_playlists

    def _get_user_albums(self):
        """Fetch user albums from all configured services (Spotify + Apple Music)."""
        all_albums = []
        
        # Fetch from Spotify
        if self._user_albums and not any(a.get('source') == 'apple_music' for a in self._user_albums):
            # Only return cached if it doesn't contain Apple Music items
            return self._user_albums
        
        try:
            if self.sp:
                sp = self._get_spotify_client()
                albums = []
                limit = 50
                offset = 0
                while True:
                    resp = sp.current_user_saved_albums(limit=limit, offset=offset)
                    for item in resp.get('items', []):
                        album = item.get('album', {})
                        album_data = {
                            'name': album['name'],
                            'id': album['id'],
                            'uri': album.get('uri') or f"spotify:album:{album['id']}",
                            'images': album.get('images', []),
                            'item_type': 'album',
                            'source': 'spotify'
                        }
                        albums.append(album_data)
                    if resp.get('next'):
                        offset += limit
                    else:
                        break
                all_albums.extend(albums)
                print(f"Fetched {len(albums)} Spotify albums")
        except Exception as e:
            print(f"Error fetching Spotify albums: {e}")
        
        # Fetch from Apple Music
        try:
            if self.apple_music_client and self.apple_music_client.developer_token:
                am_albums = self.apple_music_client.get_user_albums(limit=100)
                for alb in am_albums:
                    attrs = alb.get('attributes', {})
                    artwork = attrs.get('artwork', {})
                    images = []
                    if artwork and artwork.get('url'):
                        art_url = artwork['url'].replace('{w}', '300').replace('{h}', '300')
                        images = [{'url': art_url, 'width': 300, 'height': 300}]
                    
                    album_data = {
                        'name': attrs.get('name', 'Unknown Album'),
                        'id': alb.get('id', ''),
                        'uri': f"applemusic:album:{alb.get('id', '')}",
                        'images': images,
                        'item_type': 'album',
                        'source': 'apple_music'
                    }
                    all_albums.append(album_data)
                print(f"Fetched {len(am_albums)} Apple Music albums")
        except Exception as e:
            print(f"Error fetching Apple Music albums: {e}")
        
        self._user_albums = all_albums
        return all_albums

    def _get_spotify_client(self):
        # Helper to get a valid spotipy.Spotify client (with token refresh if needed)
        if hasattr(self, 'sp') and self.sp:
            return self.sp
        # Fallback: build a client from saved settings or environment variables.
        settings = QSettings("SpotifySync", "App")
        client_id = str(settings.value("spotify_client_id") or os.environ.get('SPOTIPY_CLIENT_ID') or "").strip()
        client_secret = str(settings.value("spotify_client_secret") or os.environ.get('SPOTIPY_CLIENT_SECRET') or "").strip()
        if not client_id or not client_secret:
            raise RuntimeError("Spotify credentials are not configured.")
        return Spotify(auth_manager=self._build_spotify_auth_manager(client_id, client_secret))

    def _resolve_playlist_context(self, playlist_ref):
        """Resolve context URI for both playlists and albums."""
        if not playlist_ref:
            return None, None
        if isinstance(playlist_ref, dict):
            playlist_ref = playlist_ref.get('uri') or playlist_ref.get('id')
        if not playlist_ref:
            return None, None
        # Check if it's already a Spotify URI
        if playlist_ref.startswith('spotify:playlist:'):
            return playlist_ref, playlist_ref.split(':')[-1]
        if playlist_ref.startswith('spotify:album:'):
            return playlist_ref, playlist_ref.split(':')[-1]
        # Check for web links
        if 'open.spotify.com/playlist/' in playlist_ref or 'spotify.com/playlist/' in playlist_ref:
            import re
            match = re.search(r'playlist[/:]([a-zA-Z0-9]+)', playlist_ref)
            if match:
                playlist_id = match.group(1)
                return f"spotify:playlist:{playlist_id}", playlist_id
        if 'open.spotify.com/album/' in playlist_ref or 'spotify.com/album/' in playlist_ref:
            import re
            match = re.search(r'album[/:]([a-zA-Z0-9]+)', playlist_ref)
            if match:
                album_id = match.group(1)
                return f"spotify:album:{album_id}", album_id
        # Default to playlist
        return f"spotify:playlist:{playlist_ref}", playlist_ref

    def _get_active_device_id(self, sp):
        try:
            devices = sp.devices().get('devices', [])
        except Exception as e:
            print(f"Error fetching Spotify devices: {e}")
            return None
        if not devices:
            print("No active Spotify devices found. Please open Spotify on a device first.")
            return None
        active_device = next((d for d in devices if d.get('is_active')), None)
        return (active_device or devices[0]).get('id')

    def _set_shuffle_state(self, sp, enabled, device_id=None, retries=3, retry_delay=0.25):
        """Best-effort shuffle toggle with verification to handle Spotify timing quirks."""
        desired_state = bool(enabled)
        for attempt in range(1, retries + 1):
            try:
                if device_id:
                    sp.shuffle(desired_state, device_id=device_id)
                else:
                    sp.shuffle(desired_state)
            except Exception as e:
                print(f"Shuffle set attempt {attempt} failed: {e}")

            try:
                playback = sp.current_playback() or {}
                if playback.get('shuffle_state') is desired_state:
                    return True
            except Exception as e:
                print(f"Shuffle verify attempt {attempt} failed: {e}")

            time.sleep(retry_delay)

        return False

    def _on_playlist_selected(self, playlist_ref):
        # Play the selected playlist or album from the start with shuffle OFF
        print(f"Playing playlist/album with ID: {playlist_ref}")
        if not self.sp:
            print("Error: Spotify API not configured. Cannot play playlists/albums.")
            ThemedMessageBox("Spotify Not Configured",
                "Spotify API is not configured.\n\nTo play playlists/albums, please set up Spotify credentials in Settings.",
                [("OK", QDialog.Accepted)], self, self._current_bg_color, self._current_text_color, 
                QColor(100, 100, 100), self._current_text_border_enabled, 
                QColor(*self._current_text_border_color), self._current_text_border_size).exec_()
            return
        try:
            sp = self._get_spotify_client()
            context_uri, playlist_id = self._resolve_playlist_context(playlist_ref)
            if not context_uri:
                print("Error: Could not resolve playlist URI for playback")
                return
            device_id = self._get_active_device_id(sp)
            # Start playback first, then force shuffle OFF.
            # Some devices ignore shuffle changes until playback context is active.
            if device_id:
                sp.start_playback(device_id=device_id, context_uri=context_uri, offset={"position": 0})
            else:
                sp.start_playback(context_uri=context_uri, offset={"position": 0})
            self._set_shuffle_state(sp, False, device_id=device_id)
            print(f"Successfully started playback for playlist: {playlist_id or playlist_ref} (shuffle OFF)")
        except Exception as e:
            print(f"Error playing playlist: {e}")
            # Check if it's a device issue
            try:
                devices = sp.devices()
                if not devices.get('devices'):
                    print("No active Spotify devices found. Please open Spotify on a device first.")
                else:
                    print(f"Available devices: {[d['name'] for d in devices.get('devices', [])]}")
            except:
                pass

    def _on_shuffle_playlist(self, playlist_ref):
        # Play the selected playlist or album from the beginning with shuffle enabled.
        # Spotify handles shuffled order after playback starts.
        print(f"Shuffling and playing playlist/album with ID: {playlist_ref}")
        if not self.sp:
            print("Error: Spotify API not configured. Cannot play playlists/albums.")
            ThemedMessageBox("Spotify Not Configured",
                "Spotify API is not configured.\n\nTo play playlists/albums, please set up Spotify credentials in Settings.",
                [("OK", QDialog.Accepted)], self, self._current_bg_color, self._current_text_color, 
                QColor(100, 100, 100), self._current_text_border_enabled, 
                QColor(*self._current_text_border_color), self._current_text_border_size).exec_()
            return
        try:
            sp = self._get_spotify_client()
            context_uri, playlist_id = self._resolve_playlist_context(playlist_ref)
            if not context_uri:
                print("Error: Could not resolve playlist URI for shuffle playback")
                return
            device_id = self._get_active_device_id(sp)
            # Start playback first, then force shuffle ON.
            # Some devices ignore shuffle changes until playback context is active.
            if device_id:
                sp.start_playback(device_id=device_id, context_uri=context_uri, offset={"position": 0})
            else:
                sp.start_playback(context_uri=context_uri, offset={"position": 0})
            shuffle_applied = self._set_shuffle_state(sp, True, device_id=device_id)
            if not shuffle_applied:
                print("Warning: Playback started, but Spotify did not confirm shuffle ON after retries.")
            print(f"Successfully started shuffled playback for playlist: {playlist_id or playlist_ref} (shuffle ON)")
        except Exception as e:
            print(f"Error shuffling playlist: {e}")
            # Check if it's a device issue
            try:
                devices = sp.devices()
                if not devices.get('devices'):
                    print("No active Spotify devices found. Please open Spotify on a device first.")
                else:
                    print(f"Available devices: {[d['name'] for d in devices.get('devices', [])]}")
            except:
                pass

    def on_playlists_updated(self, items):
        """Save playlists and albums, and update UI when list changes."""
        # Enforce cover art and item_type for every item before saving
        for item in items:
            if 'item_type' not in item:
                item['item_type'] = 'playlist'
            if 'cover_art_b64' not in item or not item['cover_art_b64']:
                item['cover_art_b64'] = self._fetch_and_encode_cover_art(item)
        self.playlists = items
        settings = QSettings("SpotifySync", "App")
        settings.setValue("user_playlists", json.dumps(self.playlists))
        print(f"Saved {len(items)} playlists/albums to settings")
        # Update UI without causing infinite loop
        self.playlist_panel.set_playlists(self.playlists, skip_save=True)
        # Reposition overlay if it's currently visible (in case size changed)
        self._reposition_overlay_if_visible()

    def _fetch_and_encode_cover_art(self, item):
        import base64
        import requests
        url = None
        item_name = item.get('name', 'Unknown')
        item_type = item.get('item_type', 'playlist')
        item_id = item.get('id')
        
        # Return cached if already present
        if 'cover_art_b64' in item and item['cover_art_b64']:
            return item['cover_art_b64']
        
        # Return empty if already marked as unavailable (404 error)
        if item.get('_unavailable'):
            return None
        
        # Prefer any images already present in the item dict
        if 'images' in item and item['images']:
            url = item['images'][0].get('url')
        elif 'cover_url' in item:
            url = item['cover_url']

        # If no URL available, try to fetch details from Spotify API
        if not url and item_id:
            try:
                sp = self._get_spotify_client()
                if item_type == 'album':
                    details = sp.album(item_id)
                else:
                    details = sp.playlist(item_id)
                
                images = details.get('images', [])
                if images:
                    url = images[0].get('url')
                    # Cache the images array for future use
                    item['images'] = images
                    print(f"Fetched image URL from Spotify for: {item_name}")
            except Exception as e:
                error_str = str(e)
                # Silently skip 404 errors (deleted/unavailable items)
                if '404' not in error_str and 'not found' not in error_str.lower():
                    print(f"Error fetching {item_type} details from Spotify for {item_name}: {e}")
                # Mark as unavailable to avoid retrying repeatedly
                item['_unavailable'] = True
                return None

        if url:
            try:
                print(f"Downloading cover art from: {url[:50]}...")
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    b64 = base64.b64encode(resp.content).decode('utf-8')
                    # Cache on item object for persistence
                    item['cover_art_b64'] = b64
                    item['cover_url'] = url
                    print(f"Successfully encoded cover art for: {item_name}")
                    return b64
                else:
                    print(f"Failed to download cover art (status {resp.status_code}) for: {item_name}")
            except Exception as e:
                print(f"Error downloading cover art for {item_name}: {e}")
        
        return None

    def _transition_easing_curve(self):
        easing_map = {
            "Out Cubic": QEasingCurve.OutCubic,
            "In Out Cubic": QEasingCurve.InOutCubic,
            "Out Quad": QEasingCurve.OutQuad,
            "In Out Quad": QEasingCurve.InOutQuad,
            "Linear": QEasingCurve.Linear,
        }
        return easing_map.get(str(self.track_transition_easing), QEasingCurve.OutCubic)

    def _apply_track_transition_animation_settings(self):
        duration = int(max(250, min(2200, int(self.track_transition_duration_ms or 800))))
        curve = self._transition_easing_curve()

        if hasattr(self, "_art_anim_in") and self._art_anim_in:
            self._art_anim_in.setDuration(duration)
            self._art_anim_in.setEasingCurve(curve)
        if hasattr(self, "_art_anim_out") and self._art_anim_out:
            self._art_anim_out.setDuration(duration)
            self._art_anim_out.setEasingCurve(curve)
        if hasattr(self, "_text_anim_in") and self._text_anim_in:
            self._text_anim_in.setDuration(duration)
            self._text_anim_in.setEasingCurve(curve)
        if hasattr(self, "_text_anim_out") and self._text_anim_out:
            self._text_anim_out.setDuration(duration)
            self._text_anim_out.setEasingCurve(curve)
        if hasattr(self, "_bg_fade_out_anim") and self._bg_fade_out_anim:
            self._bg_fade_out_anim.setDuration(duration)
            self._bg_fade_out_anim.setEasingCurve(curve)

        if hasattr(self, "bg_fade_anim") and self.bg_fade_anim:
            self.bg_fade_anim.setDuration(duration)
            self.bg_fade_anim.setEasingCurve(curve)

    def _setup_animations(self):
        EASING_OUT = QEasingCurve.OutCubic
        EASING_IN_OUT = QEasingCurve.InOutCubic
        self.fade_in_group = QParallelAnimationGroup(self)
        self.fade_out_group = QParallelAnimationGroup(self)
        
        # Art Opacity Animations - Entrance
        self._art_anim_in = QPropertyAnimation(self, b"artOpacity")
        self._art_anim_in.setDuration(800)
        self._art_anim_in.setStartValue(0.0)
        self._art_anim_in.setEndValue(1.0)
        self._art_anim_in.setEasingCurve(QEasingCurve.OutCubic)
        self.fade_in_group.addAnimation(self._art_anim_in)

        self._text_anim_in = QPropertyAnimation(self, b"textAlpha")
        self._text_anim_in.setDuration(800)
        self._text_anim_in.setStartValue(0)
        self._text_anim_in.setEndValue(255)
        self._text_anim_in.setEasingCurve(QEasingCurve.OutCubic)
        self.fade_in_group.addAnimation(self._text_anim_in)
        
        # Art Opacity Animations - Exit
        self._art_anim_out = QPropertyAnimation(self, b"artOpacity")
        self._art_anim_out.setDuration(800)
        self._art_anim_out.setStartValue(1.0)
        self._art_anim_out.setEndValue(0.0)
        self._art_anim_out.setEasingCurve(QEasingCurve.OutCubic)
        self.fade_out_group.addAnimation(self._art_anim_out)

        self._text_anim_out = QPropertyAnimation(self, b"textAlpha")
        self._text_anim_out.setDuration(800)
        self._text_anim_out.setStartValue(255)
        self._text_anim_out.setEndValue(0)
        self._text_anim_out.setEasingCurve(QEasingCurve.OutCubic)
        self.fade_out_group.addAnimation(self._text_anim_out)
        
        # Color and background fade animations
        self.fade_out_group.finished.connect(self._on_fade_out_finished)
        
        self.text_color_anim = QVariantAnimation(self)
        self.text_color_anim.setDuration(1200)
        self.text_color_anim.setEasingCurve(EASING_IN_OUT)
        self.text_color_anim.valueChanged.connect(self.setTextColor)
        
        self.bg_fade_anim = QPropertyAnimation(self, b"bgCrossfadeLerp")
        self.bg_fade_anim.setDuration(1200)
        self.bg_fade_anim.setStartValue(0.0)
        self.bg_fade_anim.setEndValue(1.0)
        self.bg_fade_anim.setEasingCurve(EASING_IN_OUT)

        # Background fade out animation
        self._bg_fade_out_anim = QPropertyAnimation(self, b"bgCrossfadeLerp")
        self._bg_fade_out_anim.setDuration(800)
        self._bg_fade_out_anim.setStartValue(1.0)
        self._bg_fade_out_anim.setEndValue(0.0)
        self._bg_fade_out_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.fade_out_group.addAnimation(self._bg_fade_out_anim)

        self._apply_track_transition_animation_settings()
        
        # Art scale animation
        self.art_scale_anim = QPropertyAnimation(self.art, b"scale")
        self.art_scale_anim.setDuration(600)
        self.art_scale_anim.setStartValue(0.9)
        self.art_scale_anim.setEndValue(1.0)
        self.art_scale_anim.setEasingCurve(EASING_OUT)

    def _current_spotify_progress_ms(self, now_ms=None):
        if now_ms is None:
            now_ms = QDateTime.currentMSecsSinceEpoch()
        if self._is_paused or self.active_media_source != 'spotify':
            return self._last_progress_val

        elapsed = max(0, now_ms - self._last_progress_sync_time)
        return min(self._last_progress_val + elapsed, self._current_track_duration)

    def _sync_spotify_progress(self, progress_ms, duration_ms=None):
        if duration_ms is not None:
            self._current_track_duration = duration_ms

        now_ms = QDateTime.currentMSecsSinceEpoch()
        progress_ms = max(0, int(progress_ms or 0))
        estimated_ms = self._current_spotify_progress_ms(now_ms)

        if self._last_progress_sync_time and abs(progress_ms - estimated_ms) <= 350:
            self._last_progress_val = estimated_ms
        else:
            self._last_progress_val = progress_ms

        self._last_reported_progress_val = progress_ms
        self._last_progress_sync_time = now_ms

    def _apply_spotify_playback_state(self, is_playing, allow_source_switch=True):
        is_paused = not bool(is_playing)
        if is_paused == self._is_paused:
            if is_playing and allow_source_switch and self.active_media_source != 'spotify' and self._last_spotify_track_data and self._is_media_method_enabled('spotify'):
                self._last_spotify_track_data['is_playing'] = True
                self._on_spotify_track_changed(self._last_spotify_track_data)
            return

        self._is_paused = is_paused

        if is_playing and allow_source_switch and self.active_media_source != 'spotify' and self._last_spotify_track_data and self._is_media_method_enabled('spotify'):
            self._last_spotify_track_data['is_playing'] = True
            self._on_spotify_track_changed(self._last_spotify_track_data)

    def _update_controls_bar_state(self, data: dict):
        """Sync controls bar button states from a Spotify playback data dict."""
        if not hasattr(self, 'player_controls_bar'):
            return
        is_playing = bool(data.get("is_playing", False))
        self.player_controls_bar.set_is_playing(is_playing)

        shuffle = bool(data.get("shuffle_state", False))
        self._shuffle_state = shuffle
        self.player_controls_bar.set_shuffle(shuffle)

        repeat_raw = data.get("repeat_state", "off")
        repeat_map = {"off": "off", "context": "context", "track": "track"}
        repeat_mode = repeat_map.get(repeat_raw, "off")
        self._repeat_mode = repeat_mode
        self.player_controls_bar.set_repeat_mode(repeat_mode)

        # Liked state: check asynchronously to avoid blocking the UI thread
        track_id = (data.get("item") or {}).get("id")
        if track_id and self.sp and track_id != self._controls_track_id:
            self._controls_track_id = track_id
            try:
                sp = self._get_spotify_client()
                results = sp.current_user_saved_tracks_contains([track_id])
                liked = bool(results[0]) if results else False
                self._is_liked = liked
                self.player_controls_bar.set_liked(liked)
            except Exception as e:
                print(f"Error checking liked state: {e}")

    def _action_play_pause(self):
        if not self.sp:
            return
        try:
            sp = self._get_spotify_client()
            if self._is_paused:
                sp.start_playback()
            else:
                sp.pause_playback()
        except Exception as e:
            print(f"Error toggling play/pause: {e}")

    def _action_shuffle(self):
        if not self.sp:
            return
        try:
            sp = self._get_spotify_client()
            new_state = not self._shuffle_state
            device_id = self._get_active_device_id(sp)
            self._set_shuffle_state(sp, new_state, device_id=device_id)
            self._shuffle_state = new_state
            self.player_controls_bar.set_shuffle(new_state)
        except Exception as e:
            print(f"Error toggling shuffle: {e}")

    def _action_repeat(self):
        if not self.sp:
            return
        try:
            sp = self._get_spotify_client()
            cycle = {"off": "context", "context": "track", "track": "off"}
            new_mode = cycle.get(self._repeat_mode, "off")
            device_id = self._get_active_device_id(sp)
            if device_id:
                sp.repeat(new_mode, device_id=device_id)
            else:
                sp.repeat(new_mode)
            self._repeat_mode = new_mode
            self.player_controls_bar.set_repeat_mode(new_mode)
        except Exception as e:
            print(f"Error cycling repeat mode: {e}")

    def _action_add_to_playlist(self):
        if not self.sp:
            return
        track_data = self._prev_track_data.get("item") if self._prev_track_data else None
        if not track_data:
            return
        track_uri = track_data.get("uri")
        if not track_uri:
            return
        # Open the playlist panel so the user can pick a destination
        if hasattr(self, 'playlist_panel'):
            self._reposition_overlay_if_visible()
            self.playlist_panel.show()

    def _action_liked(self):
        if not self.sp:
            return
        track_data = self._prev_track_data.get("item") if self._prev_track_data else None
        if not track_data:
            return
        track_id = track_data.get("id")
        if not track_id:
            return
        try:
            sp = self._get_spotify_client()
            new_liked = not self._is_liked
            if new_liked:
                sp.current_user_saved_tracks_add([track_id])
            else:
                sp.current_user_saved_tracks_delete([track_id])
            self._is_liked = new_liked
            self.player_controls_bar.set_liked(new_liked)
        except Exception as e:
            print(f"Error toggling liked state: {e}")

    def _finish_text_animation(self, animation):
        if animation in self._active_text_animations:
            self._active_text_animations.remove(animation)

    def _animate_text_field_change(self, widget, new_text, delay_ms=0):
        if widget.text() == new_text:
            widget.setProperty("opacity", 1.0)
            widget.setProperty("textScale", 1.0)
            return False

        # During track transitions, just set text immediately without animations
        # This keeps the transition clean with only opacity fading
        if self._is_track_transitioning:
            widget.setText(new_text)
            widget.setProperty("opacity", 1.0)
            widget.setProperty("textScale", 1.0)
            return True

        def start_transition():
            current_opacity = float(widget.property("opacity") if widget.property("opacity") is not None else 1.0)

            fade_out = QParallelAnimationGroup(self)

            out_opacity = QPropertyAnimation(widget, b"opacity")
            out_opacity.setDuration(140)
            out_opacity.setStartValue(current_opacity)
            out_opacity.setEndValue(0.0)
            out_opacity.setEasingCurve(QEasingCurve.InOutQuad)
            fade_out.addAnimation(out_opacity)

            out_scale = QPropertyAnimation(widget, b"textScale")
            out_scale.setDuration(140)
            out_scale.setStartValue(float(widget.property("textScale") or 1.0))
            out_scale.setEndValue(0.97)
            out_scale.setEasingCurve(QEasingCurve.InCubic)
            fade_out.addAnimation(out_scale)

            def fade_in_new_text():
                widget.setText(new_text)
                widget.setProperty("opacity", 0.0)
                widget.setProperty("textScale", 0.97)

                fade_in = QParallelAnimationGroup(self)

                in_opacity = QPropertyAnimation(widget, b"opacity")
                in_opacity.setDuration(260)
                in_opacity.setStartValue(0.0)
                in_opacity.setEndValue(1.0)
                in_opacity.setEasingCurve(QEasingCurve.InOutQuad)
                fade_in.addAnimation(in_opacity)

                in_scale = QPropertyAnimation(widget, b"textScale")
                in_scale.setDuration(260)
                in_scale.setStartValue(0.97)
                in_scale.setEndValue(1.0)
                in_scale.setEasingCurve(QEasingCurve.OutCubic)
                fade_in.addAnimation(in_scale)

                fade_in.finished.connect(lambda: self._finish_text_animation(fade_in))
                self._active_text_animations.append(fade_in)
                fade_in.start()

            fade_out.finished.connect(fade_in_new_text)
            fade_out.finished.connect(lambda: self._finish_text_animation(fade_out))
            self._active_text_animations.append(fade_out)
            fade_out.start()

        if delay_ms > 0:
            QTimer.singleShot(delay_ms, start_transition)
        else:
            start_transition()

        return True

    def _apply_display_text_changes(self, title_text, album_text, artist_text):
        previous_state = self._last_display_state or {}
        changed_any = False
        changed_any = self._animate_text_field_change(self.title, title_text, 0) or changed_any
        changed_any = self._animate_text_field_change(self.album_name, album_text, 90) or changed_any
        changed_any = self._animate_text_field_change(self.artist, artist_text, 180) or changed_any

        if not changed_any:
            self.title.setText(title_text)
            self.album_name.setText(album_text)
            self.artist.setText(artist_text)

        self._last_display_state = {
            "title": title_text,
            "album": album_text,
            "artist": artist_text,
        }

        return previous_state != self._last_display_state

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
        self._configure_media_workers()

        # New timer to control the repaint rate for animations, reducing CPU usage.
        self.repaint_timer = QTimer(self)
        self.repaint_timer.setTimerType(Qt.PreciseTimer)
        target_fps = max(24, min(60, int(BACKGROUND_TARGET_FPS)))
        self.repaint_timer.setInterval(max(8, int(1000 / target_fps)))
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
        if not self._is_media_method_enabled(source):
            return
        if self.active_media_source == source:
            # The currently active media source has stopped.
            self.active_media_source = None
            self._current_track_duration = 0
            self.progress_bar.fade_out()
            self.art.setAspectRatio(1.0) # Revert to square
            self._current_lyrics = []
            self._current_lyric_index = -1
            if self.lyrics_label:
                self.lyrics_label.reset()
                self.lyrics_label.show()

            # If a non-Spotify source stopped and Spotify has a track (even paused), switch back to Spotify
            if source in ['windows', 'apple_music'] and self._last_spotify_track_data and self._is_media_method_enabled('spotify'):
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
    def _on_apple_music_no_playback(self):
        self._handle_no_playback('apple_music')

    @pyqtSlot()
    def _on_windows_no_playback(self):
        self._handle_no_playback('windows')

    def _on_frame_update(self):
        # Lyrics must tick regardless of window visibility so they stay in sync
        # when the player is unfocused, minimized, or behind other windows.
        if self._current_lyrics and not self._is_paused and self.active_media_source == 'spotify' and self.lyrics_label and self.lyrics_label.isVisible():
            current_ms = self._current_spotify_progress_ms()

            new_index = -1
            for i, (ts, _) in enumerate(self._current_lyrics):
                if ts <= current_ms:
                    new_index = i
                else:
                    break

            if new_index != self._current_lyric_index and new_index >= 0:
                self._current_lyric_index = new_index
                line_text = self._current_lyrics[new_index][1]
                if line_text:
                    self.lyrics_label.setLine(line_text)
                else:
                    self.lyrics_label.clearLine()

        if self.isMinimized() or self.isHidden(): return
        if self._current_progress_bar_enabled and self.active_media_source == 'spotify':
            if not self._is_paused and self._current_track_duration > 0:
                current = self._current_spotify_progress_ms()
                self.progress_bar.setTargetValue(current)
            elif self._is_paused:
                self.progress_bar.setTargetValue(self._last_progress_val)
            
            self.progress_bar.update_smooth_value()


        if self.background_renderer:
            self.background_renderer.set_background_color(self._current_blended_bg_color())
            self.background_renderer.set_global_opacity(self._global_fade)
            if self._gl_focus_stabilizing and self.background_renderer.uses_opengl:
                if QDateTime.currentMSecsSinceEpoch() < self._gl_stabilize_until_ms:
                    return
                self._end_gl_focus_stabilization()
            self.background_renderer.tick()

        if not (self.background_renderer and self.background_renderer.uses_opengl):
            self.update()

    @pyqtSlot(dict)
    def _on_spotify_track_changed(self, data):
        if not self._is_media_method_enabled('spotify'):
            return
        # If another media source is active and Spotify is not currently playing,
        # just update the last track data in the background without interrupting the UI.
        if self.active_media_source != 'spotify' and not data.get("is_playing"):
            self._last_spotify_track_data = data
            return

        self.idle_timer.stop()
        self.active_media_source = 'spotify'
        self._last_spotify_track_data = data

        self._sync_spotify_progress(data["progress_ms"], data["item"]["duration_ms"])
        self.progress_bar.setRange(0, self._current_track_duration)
        self.progress_bar.setTargetValue(self._last_progress_val, snap=True)

        item = data["item"]
        track_id = item["id"]

        # --- LISTEN MODE LYRICS BYPASS ---
        if getattr(self, 'listen_mode_enabled', False):
            # If Listen Mode is ON, hide the label and clear state so it doesn't process
            if hasattr(self, 'lyrics_label') and self.lyrics_label:
                self.lyrics_label.hide()
            self._current_lyrics = []
            self._current_lyric_index = -1
        else:
            # If Listen Mode is OFF, run normal Spotify lyrics routine.
            if hasattr(self, 'lyrics_label') and self.lyrics_label:
                self.lyrics_label.show() # Ensure it's visible again
            
            # --- Lyrics: reset state and fetch for new track ---
            self._current_lyrics = []
            self._current_lyric_index = -1
            
            if self.lyrics_label:
                self.lyrics_label.reset()
                
            if self.lyrics_cache.has(track_id):
                cached = self.lyrics_cache.get(track_id)
                if cached:
                    self._current_lyrics = cached
                    if self.lyrics_label:
                        # Visible at opacity=0; frame_update will call setLine -> fade in.
                        self.lyrics_label.show()
                else:
                    # Cached as False (no synced lyrics): keep reserved space, clear text.
                    if self.lyrics_label:
                        self.lyrics_label.reset()
                        self.lyrics_label.show()
            else:
                # Not yet fetched: keep reserved space until worker responds.
                if self.lyrics_label:
                    self.lyrics_label.reset()
                    self.lyrics_label.show()
                lyrics_worker = LyricsWorker(
                    track_id,
                    item.get("name", ""),
                    item.get("artists", [{}])[0].get("name", ""),
                    item.get("album", {}).get("name", ""),
                    item.get("duration_ms", 0),
                )
                lyrics_worker.signals.lyrics_ready.connect(self._on_lyrics_ready)
                lyrics_worker.signals.no_lyrics.connect(self._on_no_lyrics)
                self.threadpool.start(lyrics_worker)
        # ---------------------------------

        # Aspect ratio is now set after the fade-out to prevent a jarring switch.
        self._load_track_data(data["item"], data["is_playing"], data["progress_ms"], aspect_ratio=1.0)
        self._update_controls_bar_state(data)

    @pyqtSlot(str, list)
    def _on_lyrics_ready(self, track_id, lines):
        """Receives parsed synced lyrics from LyricsWorker."""
        if track_id != self._current_track_id:
            return  # Stale response for a previous track
        self.lyrics_cache.set(track_id, lines)
        self._current_lyrics = lines
        self._current_lyric_index = -1
        if self.lyrics_label:
            # reset() was already called during track_changed; opacity is 0.
            # show() makes the widget visible so frame_update can drive the fade-in.
            self.lyrics_label.show()

    @pyqtSlot(str)
    def _on_no_lyrics(self, track_id):
        """Called when no synced lyrics are available for the current track."""
        if track_id != self._current_track_id:
            return
        self.lyrics_cache.set(track_id, False)
        if self.lyrics_label:
            self.lyrics_label.reset()
            self.lyrics_label.show()

    @pyqtSlot(dict)
    def _on_windows_track_changed(self, data):
        if not self._is_media_method_enabled('windows'):
            return
        # Only process if spotify/apple_music are not the active source, or if they are paused.
        # This allows Windows media (YouTube, etc.) to take over when primary services are paused.
        if self.active_media_source not in ['spotify', 'apple_music'] or self._is_paused:
            self.idle_timer.stop()
            self._current_track_duration = 0 # Disable progress bar for generic media
            self.active_media_source = 'windows'
            
            item = data["item"]
            thumbnail_data = data.get("thumbnail_data")

            # Process the thumbnail
            pil_img = None
            if thumbnail_data:
                try:
                    pil_img = Image.open(io.BytesIO(thumbnail_data)).convert("RGB")
                except Exception:
                    pil_img = None

            if not pil_img:
                # Fallback placeholder if no art is found
                pil_img = Image.new("RGB", (640, 640), "black")

            # Pass the constructed item (which now contains our synthetic hash IDs)
            # This ensures _load_track_data looks up the correct "Album ID" in your cache.
            self._load_track_data(
                item, 
                data["is_playing"], 
                data["progress_ms"], 
                preloaded_image=pil_img, 
                aspect_ratio=1.0 # Keep square for music, change to 16:9 only if you detect video
            )
    
    @pyqtSlot(dict)
    def _on_apple_music_track_changed(self, data):
        if not self._is_media_method_enabled('apple_music'):
            return
        # Apple Music takes priority over Windows generic media, but not over Spotify
        if self.active_media_source == 'spotify' and not self._is_paused:
            # Spotify is actively playing, don't interrupt
            return
        
        self.idle_timer.stop()
        self._current_track_duration = 0  # Apple Music doesn't provide duration via system controls
        self.active_media_source = 'apple_music'
        
        item = data["item"]
        thumbnail_data = data.get("thumbnail_data")
        
        # Process the thumbnail
        pil_img = None
        if thumbnail_data:
            try:
                pil_img = Image.open(io.BytesIO(thumbnail_data)).convert("RGB")
            except Exception:
                pil_img = None
        
        if not pil_img:
            # Fallback placeholder if no art is found
            pil_img = Image.new("RGB", (640, 640), "black")
        
        # Load track data with the enriched Apple Music metadata
        self._load_track_data(
            item,
            data["is_playing"],
            data["progress_ms"],
            preloaded_image=pil_img,
            aspect_ratio=1.0
        )

    def _load_track_data(self, item, is_playing, progress_ms, preloaded_image=None, aspect_ratio=1.0):
        self._pending_track_data = None

        self._prev_track_data = {"item": item, "is_playing": is_playing, "progress_ms": progress_ms, "aspect_ratio": aspect_ratio}
        self.load_token += 1
        images_data = item["album"]["images"]
        album_obj = item.get("album") or {}
        incoming_album_id = (
            item.get("album_id")
            or album_obj.get("id")
            or album_obj.get("name")
            or f"track-{item.get('id', 'unknown')}"
        )
        self._incoming_album_changed = incoming_album_id != self._last_applied_album_id
        self._current_album_id = incoming_album_id
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

    def _freeze_widget_geometry(self):
        """Lock widget sizes to prevent layout shifts during fade transitions."""
        self.art.setFixedSize(self.art.width(), self.art.height())
        self.title.setFixedHeight(self.title.height())
        self.artist.setFixedHeight(self.artist.height())
        self.album_name.setFixedHeight(self.album_name.height())
        self.details_widget.setFixedSize(self.details_widget.width(), self.details_widget.height())

    def _unfreeze_widget_geometry(self):
        """Allow widgets to resize normally after transitions complete."""
        # Keep album art locked to computed size to avoid reflow jitter.
        self.art.setFixedSize(self._current_art_size_px, self._current_art_size_px)
        self.art_container.setFixedSize(self._current_art_size_px, self._current_art_size_px)
        self.title.setMinimumHeight(0)
        self.title.setMaximumHeight(16777215)
        self.artist.setMinimumHeight(0)
        self.artist.setMaximumHeight(16777215)
        self.album_name.setMinimumHeight(0)
        self.album_name.setMaximumHeight(16777215)
        self.details_widget.setMinimumSize(0, 0)
        self.details_widget.setMaximumSize(16777215, 16777215)

    def _unfreeze_and_update_layout(self):
        """Unfreeze geometry and trigger final layout update after fade-in completes."""
        self._unfreeze_widget_geometry()
        self._is_track_transitioning = False  # Clear transition flag when done
        self.textAlpha = 255  # Restore text alpha after fade-in completes
        self.update_layout()
        # Now apply all visual property updates that were deferred during the animation
        self._update_text_properties()
        # Animate text color change if needed
        if hasattr(self, '_pending_text_color') and self._pending_text_color:
            if self._pending_text_color != self._cur_text_color:
                self.text_color_anim.setStartValue(self._cur_text_color)
                self.text_color_anim.setEndValue(self._pending_text_color)
                self.text_color_anim.start()
            else:
                self.text_color_anim.stop()
            self._pending_text_color = None

    @pyqtSlot(dict)
    def _on_track_data_loaded(self, result_data):
        if result_data['token'] != self.load_token: return

        self._pending_track_data = result_data
        self._pending_track_data["high_res_loaded"] = False
        self._pending_track_data["album_changed"] = bool(self._incoming_album_changed)
        is_visible = self.artOpacity > 0.01 or self.textAlpha > 1
        self._pending_track_data["needs_fade_transition"] = bool(is_visible)
        
        if is_visible:
            if self.fade_in_group.state() == QAbstractAnimation.Running:
                self.fade_in_group.stop()
            self._old_bg_color = self._current_bg_color
            if self.fade_out_group.state() != QAbstractAnimation.Running:
                self._is_track_transitioning = True  # Flag that we're in a transition
                self._freeze_widget_geometry()  # Lock positions before fading out
                self.fade_out_group.start()
        else:
            self._is_track_transitioning = False
            self._apply_pending_track_data()

        # Update Dialog if visible
        if self._should_live_reload_settings_dialog():
            if self._prev_track_data and "item" in self._prev_track_data:
                item = self._prev_track_data["item"]
                a_name = item["album"]["name"]
                art_name = ", ".join(a["name"] for a in item["artists"])
            else:
                a_name = "Unknown"; art_name = "Unknown"

            self.settings_dialog.start_content_fade_and_reload(
                self._current_album_id,
                self._current_track_id,
                self.art.pixmap(),
                album_name=a_name, # Pass name
                artist_name=art_name # Pass artist
            )

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
        album_changed = bool(result_data.get("album_changed", True))
        transition_active = bool(result_data.get("needs_fade_transition", False))

        # Set the aspect ratio here, after the old art has faded out.
        new_aspect_ratio = self._prev_track_data.get("aspect_ratio", 1.0)
        self.art.setAspectRatio(new_aspect_ratio)

        self._current_pil_img = result_data["pil_img"]
        self._set_album_art(self._current_pil_img)
        self.art.setLoadingState(not result_data.get("high_res_loaded", False))

        item = self._prev_track_data["item"]
        album_cache = self.color_cache.get_album_data(self._current_album_id) or {}
        track_cache = self.color_cache.get_album_data(self._current_track_id) or {}
        color_override_keys = {
            "ui_palette",
            "blob_palette",
            "lights_config",
            "text_color",
            "text_border_color",
            "title_gradient_enabled",
            "title_gradient_color",
            "title_gradient_direction",
        }
        cached_data = album_cache.copy() if isinstance(album_cache, dict) else {}
        if isinstance(track_cache, dict):
            for key, value in track_cache.items():
                if key not in color_override_keys:
                    cached_data[key] = value
        
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
        self._current_title_gradient_enabled = result_data.get("title_gradient_enabled", False)
        self._current_title_gradient_color = result_data.get("title_gradient_color") or [255, 255, 255]
        self._current_title_gradient_direction = result_data.get("title_gradient_direction", "Left to Right")
        self._current_album_border_enabled = result_data.get("album_art_border_enabled", True)
        
        track_brightness = cached_data.get("govee_brightness")
        if track_brightness is not None:
            self.govee_brightness = float(track_brightness)
        else:
            self.govee_brightness = self.default_govee_brightness
        
        player_bg_rgb = cached_data.get("player_bg_color")
        if player_bg_rgb:
            primary_qcolor = QColor(*player_bg_rgb)
        else:
            primary_qcolor = self._derive_background_tone_color()

        if album_changed:
            self._current_bg_color = primary_qcolor
        else:
            self._current_bg_color = self._old_bg_color
        

        self._update_blobs() 
        border_color = QColor(*self._current_ui_palette[1]) if len(self._current_ui_palette) > 1 else primary_qcolor.lighter(150)
        self.art.setBorderColor(border_color if self._current_album_border_enabled else QColor("transparent"))
        
        self.progress_bar.set_color(new_text_rgb)
        if self._current_progress_bar_enabled and self.active_media_source == 'spotify':
            self.progress_bar.fade_in()
        else:
            self.progress_bar.fade_out()

        album_text = self._apply_case_transform(item["album"]["name"], self._current_artist_case)
        title_text = self._apply_case_transform(item["name"], self._current_title_case)
        artist_text = self._apply_case_transform(", ".join(a["name"] for a in item["artists"]), self._current_artist_case)
        self._apply_display_text_changes(title_text, album_text, artist_text)

        if album_changed:
            self.art.scale = 0.9
            self.art_scale_anim.setStartValue(0.9)
            self.art_scale_anim.setEndValue(1.0)
            self.art_scale_anim.start()
        else:
            self.art_scale_anim.stop()
            self.art.scale = 1.0

        # Update lights for the currently active media source using the same palette/brightness logic.
        lights_config = result_data.get("lights_config") or {}
        if lights_config.get("mode") == "custom" and lights_config.get("palette"):
            lights_palette_to_send = lights_config["palette"]
        else:
            lights_palette_to_send = self._current_lights_palette

        source_name = self.active_media_source
        lights_enabled = bool(self.lights_enabled and self.govee_devices and self._is_lights_source_allowed(source_name))
        palette_signature = tuple(tuple(int(c) for c in color) for color in (lights_palette_to_send or []))
        devices_signature = tuple((d.get("device"), d.get("model")) for d in (self.govee_devices if lights_enabled else []))
        new_lights_config = {
            "palette": palette_signature,
            "devices": devices_signature,
            "brightness": self.govee_brightness,
        }
        if new_lights_config != self._last_sent_lights_config:
            self._last_sent_lights_config = new_lights_config
            worker = GoveeWorker(self._govee, lights_palette_to_send, lights_enabled, self.govee_brightness)
            worker.signals.error.connect(self._on_govee_error)
            self.threadpool.start(worker)
        self.notification_widget.fade_out()
        # Don't set textAlpha to 255 here - keep it at 0 during fade animations
        # It will be restored in _unfreeze_and_update_layout after fade-in completes
        if album_changed:
            self._bg_crossfade_lerp = 0.0  # Ensure it starts from the "from" state
            self.bg_fade_anim.setStartValue(0.0)
            self.bg_fade_anim.setEndValue(1.0)
            self.bg_fade_anim.start()
        else:
            self.bg_fade_anim.stop()
            self.setBgCrossfadeLerp(1.0)
        self._trigger_notification(title_text, artist_text, self._current_pil_img, QColor(*new_text_rgb))
        if transition_active:
            # Connect fade_in to unfreeze AFTER animation completes, not before
            try:
                self.fade_in_group.finished.disconnect()
            except TypeError:
                pass
            self.fade_in_group.finished.connect(lambda: self._unfreeze_and_update_layout())
            self.fade_in_group.start()
        else:
            self._is_track_transitioning = False
            self.artOpacity = 1.0
            self.textAlpha = 255
        self._apply_spotify_playback_state(self._prev_track_data.get("is_playing", False), allow_source_switch=False)
        
        # Layout update happens while frozen during transitions; widgets won't shift.
        self.update_layout()
        
        # DON'T update text properties or animate colors yet - wait until fade-in completes
        # Store the new text color to apply after fade-in
        self._pending_text_color = QColor(*new_text_rgb)

        self._last_applied_album_id = self._current_album_id

        
        if self._should_live_reload_settings_dialog():
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
            
            # Update Dialog image and metadata
            if self._should_live_reload_settings_dialog():
                if self._prev_track_data and "item" in self._prev_track_data:
                    item = self._prev_track_data["item"]
                    a_name = item["album"]["name"]
                    art_name = ", ".join(a["name"] for a in item["artists"])
                else:
                    a_name = "Unknown"; art_name = "Unknown"

                self.settings_dialog.load_track_state(
                    self._current_album_id,
                    self._current_track_id,
                    self.art.pixmap(),
                    animate=False,
                    album_name=a_name, # Pass name
                    artist_name=art_name # Pass artist
                )

    def _apply_and_refresh_ui(self):
        if not self._current_ui_palette or not self._prev_track_data:
            return
        
        item = self._prev_track_data["item"]
        
        album_cache = self.color_cache.get_album_data(self._current_album_id) or {}
        track_cache = self.color_cache.get_album_data(self._current_track_id) or {}
        color_override_keys = {
            "ui_palette",
            "blob_palette",
            "lights_config",
            "text_color",
            "text_border_color",
            "title_gradient_enabled",
            "title_gradient_color",
            "title_gradient_direction",
        }
        cached_data = album_cache.copy() if isinstance(album_cache, dict) else {}
        if isinstance(track_cache, dict):
            for key, value in track_cache.items():
                if key not in color_override_keys:
                    cached_data[key] = value

        self._current_ui_palette = album_cache.get("ui_palette", self._current_ui_palette)
        self._current_blob_palette = album_cache.get("blob_palette", self._current_blob_palette)
        self._current_progress_bar_enabled = cached_data.get("progress_bar_enabled", self.default_progress_bar_enabled) if isinstance(cached_data, dict) else self.default_progress_bar_enabled
        self._current_lights_palette = cached_data.get("original_lights_palette", self._current_lights_palette)
        
        player_bg_rgb = cached_data.get("player_bg_color", self._current_ui_palette[0])
        text_rgb = album_cache.get("text_color")
        if not text_rgb:
            accent_rgb = self._current_ui_palette[1] if len(self._current_ui_palette) > 1 else None
            text_rgb = get_best_text_color(player_bg_rgb, accent_rgb)
        self._current_text_color = text_rgb

        lights_config = album_cache.get("lights_config", {})
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
        self._current_title_gradient_enabled = cached_data.get("title_gradient_enabled", False)
        self._current_title_gradient_color = album_cache.get("title_gradient_color") or cached_data.get("title_gradient_color", [255, 255, 255])
        self._current_title_gradient_direction = cached_data.get("title_gradient_direction", "Left to Right")
        self._current_album_border_enabled = cached_data.get("album_art_border_enabled", True)
        # Note: auto_border_enabled logic is handled in TrackLoaderWorker, so text_border_enabled here is the final result
        self._current_text_border_size = cached_data.get("text_border_size", self.default_text_border_size)
        
        track_brightness = cached_data.get("govee_brightness")
        if track_brightness is not None:
            self.govee_brightness = float(track_brightness)
        else:
            self.govee_brightness = self.default_govee_brightness
        
        # Auto-detect border color if enabled but not cached
        cached_border_color = album_cache.get("text_border_color")
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
        self.art.setBorderColor(border_color if self._current_album_border_enabled else QColor("transparent"))
        self._old_bg_color = self._current_bg_color
        self._current_bg_color = primary_qcolor
        
        self.progress_bar.set_color(text_rgb)
        if self._current_progress_bar_enabled and self.active_media_source == 'spotify':
            self.progress_bar.fade_in()
        else:
            self.progress_bar.fade_out()

        self._update_blobs()
        # Only change lights for Spotify tracks
        # Only change lights for Spotify tracks
        if self._is_lights_source_allowed(self.active_media_source):
            # --- FIX: Determine brightness to send ---
            brightness_to_send = None if self.govee_brightness_override else self.govee_brightness
            
            new_lights_config = {
                "palette": lights_palette,
                "devices": self.lights_enabled and self.govee_devices,
                "brightness": brightness_to_send # Use the override-aware value
            }
            
            if new_lights_config != self._last_sent_lights_config:
                self._last_sent_lights_config = new_lights_config
                worker = GoveeWorker(self._govee, lights_palette, self.lights_enabled and self.govee_devices, brightness_to_send)
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
        
        # Master Override: Check if notifications are globally enabled
        if settings.value("notification_enabled", "false") != "true":
            if self.notification_widget.isVisible(): self.notification_widget.fade_out()
            return
        
        # Master Override: Check if notifications are globally enabled
        if settings.value("notification_enabled", "false") != "true":
            # If disabled, ensure any existing notification hides immediately
            if self.notification_widget.isVisible():
                self.notification_widget.fade_out()
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
        notif_title_gradient_enabled = bool(self._current_title_gradient_enabled)
        notif_title_gradient_color = QColor(*self._current_title_gradient_color).name()
        notif_title_gradient_direction = self._current_title_gradient_direction
        
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
            "border_size": self._current_text_border_size,
            "title_gradient_enabled": notif_title_gradient_enabled,
            "title_gradient_color": notif_title_gradient_color,
            "title_gradient_direction": notif_title_gradient_direction
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
        self.default_show_player_controls = str(settings.value("default_show_player_controls", "false")).lower() == "true"
        self.default_controls_play_pause  = str(settings.value("default_controls_play_pause",  "true")).lower() == "true"
        self.default_controls_shuffle     = str(settings.value("default_controls_shuffle",     "true")).lower() == "true"
        self.default_controls_repeat      = str(settings.value("default_controls_repeat",      "true")).lower() == "true"
        self.default_controls_add_playlist= str(settings.value("default_controls_add_playlist","true")).lower() == "true"
        self.default_controls_liked       = str(settings.value("default_controls_liked",       "true")).lower() == "true"
        self._apply_controls_bar_settings()
        self.track_transition_duration_ms = int(max(250, min(2200, int(settings.value("track_transition_duration_ms", 800)))))
        self.track_transition_easing = str(settings.value("track_transition_easing", "Out Cubic") or "Out Cubic")
        val = settings.value("default_govee_brightness")
        if val is not None:
            self.default_govee_brightness = float(val)
        self.minimize_to_notification_only = str(settings.value("minimize_to_notification_only", "true")).lower() == "true"
        self.spotify_method_enabled = str(settings.value("spotify_method_enabled", "true")).lower() == "true"
        self.apple_music_method_enabled = str(settings.value("apple_music_method_enabled", "true")).lower() == "true"
        self.windows_media_method_enabled = str(settings.value("windows_media_method_enabled", "true")).lower() == "true"
        saved_art_side = str(settings.value("player_art_side", "left")).strip().lower()
        self.player_art_side = "right" if saved_art_side == "right" else "left"
        self.lava_lamp_preset = "color_pop"
        if self.background_renderer:
            self.background_renderer.set_style_preset(self.lava_lamp_preset)

        self._configure_media_workers()
        if self.active_media_source and not self._is_media_method_enabled(self.active_media_source):
            self.active_media_source = None
            if self._is_media_method_enabled('spotify') and self._last_spotify_track_data:
                self._on_spotify_track_changed(self._last_spotify_track_data)
            else:
                self._show_idle_screen()
        self.update_layout()

        if new_config.get("_reload_art") and self._prev_track_data and self._prev_track_data.get("item"):
            self._load_track_data(
                self._prev_track_data["item"],
                self._prev_track_data.get("is_playing", False),
                self._prev_track_data.get("progress_ms", 0),
                aspect_ratio=self._prev_track_data.get("aspect_ratio", 1.0)
            )
            return

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
        settings = QSettings("SpotifySync", "App")
        
        if self.notification_only_mode:
            # --- EXITING MODE ---
            self.notification_only_mode = False
            
            # Restore previous notification setting state
            if hasattr(self, '_was_notif_enabled_before_mode'):
                # Convert boolean back to string for QSettings
                prev_state = "true" if self._was_notif_enabled_before_mode else "false"
                settings.setValue("notification_enabled", prev_state)
            
            if self.is_fullscreen and not self.multi_monitor_mode:
                self._enter_borderless_fullscreen()
            else:
                self.show()
            
            self.raise_()
            self.activateWindow()
            self.setWindowOpacity(1.0)
            if self.tray_icon and not self.is_wallpaper_mode:
                self.tray_icon.hide()
        else:
            # --- ENTERING MODE ---
            if not self.tray_icon: return # Cannot enter this mode without tray to restore
            
            # Save current state
            current_state = settings.value("notification_enabled", "false") == "true"
            self._was_notif_enabled_before_mode = current_state
            
            # Force Notifications ON
            settings.setValue("notification_enabled", "true")
            
            self.notification_only_mode = True
            self.tray_icon.show()
            
            self.exit_anim = QPropertyAnimation(self, b"windowOpacity")
            self.exit_anim.setDuration(600)
            self.exit_anim.setStartValue(self.windowOpacity())
            self.exit_anim.setEndValue(0.0)
            self.exit_anim.setEasingCurve(QEasingCurve.OutQuad)
            self.exit_anim.finished.connect(self._hide_for_notif_mode)
            self.exit_anim.start()
            
            # Show a toast confirming the mode
            if self.tray_icon:
                self.tray_icon.showMessage("Notification Mode", 
                                           "Player hidden. Notifications forced ON.", 
                                           QSystemTrayIcon.Information, 2000)

    def _hide_for_notif_mode(self):
        if self.notification_only_mode:
            self.hide()
            try: self.exit_anim.finished.disconnect(self._hide_for_notif_mode)
            except: pass

    def _set_player_content_opacity(self, value):
        opacity = max(0.0, min(1.0, float(value)))
        if hasattr(self, 'art') and self.art:
            self.art.setOpacity(opacity)
        if hasattr(self, 'title') and self.title:
            self.title.set_opacity(opacity)
        if hasattr(self, 'album_name') and self.album_name:
            self.album_name.set_opacity(opacity)
        if hasattr(self, 'artist') and self.artist:
            self.artist.set_opacity(opacity)
        if hasattr(self, 'progress_bar') and self.progress_bar and hasattr(self.progress_bar, 'opacity_effect') and self.progress_bar.opacity_effect:
            self.progress_bar.opacity_effect.setOpacity(opacity)
            self.progress_bar.update()

    def _set_player_content_visible(self, visible):
        if hasattr(self, 'art_container') and self.art_container:
            self.art_container.setVisible(visible)
        if hasattr(self, 'details_widget') and self.details_widget:
            self.details_widget.setVisible(visible)

    def _on_content_fade_finished(self):
        if self._background_only_target_state:
            self._set_player_content_visible(False)
        else:
            self._set_player_content_visible(True)
            self._set_player_content_opacity(1.0)
        self.update_layout()
        self.update()

    def _apply_background_only_mode(self, enabled, animate=True):
        enabled = bool(enabled)
        self.background_only_mode = enabled
        self._background_only_target_state = enabled

        if not hasattr(self, '_content_fade_anim'):
            return

        self._content_fade_anim.stop()
        self._set_player_content_visible(True)

        start_opacity = self.art._opacity if hasattr(self, 'art') and self.art else (0.0 if enabled else 1.0)
        end_opacity = 0.0 if enabled else 1.0

        if animate and abs(start_opacity - end_opacity) > 0.001:
            self._content_fade_anim.setStartValue(start_opacity)
            self._content_fade_anim.setEndValue(end_opacity)
            self._content_fade_anim.start()
            return

        self._set_player_content_opacity(end_opacity)
        if enabled:
            self._set_player_content_visible(False)
        self.update_layout()
        self.update()

    def toggle_background_only_mode(self):
        """Toggle a background-only mode that hides player content while keeping the app interactive."""
        self._apply_background_only_mode(not self.background_only_mode, animate=True)

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

        if self.background_renderer:
            self.background_renderer.set_palette(blob_colors)

        if self.background_renderer and self.background_renderer.uses_opengl:
            if self.blob_manager:
                self.blob_manager.stop_all()
                self.blob_manager = None
            return

        if self.blob_manager:
            # Manager exists, just update its palette. This will handle adding/removing/recoloring blobs smoothly.
            self.blob_manager.update_palette(blob_colors)
        else:
            # First time setup for blobs
            self.blob_manager = BlobManager(self, self.size(), blob_colors)
            self.blob_manager.density = self.blob_density
            self.blob_manager.adjust_blob_count()

    def paintEvent(self, event):
        gl_active = bool(self.background_renderer and self.background_renderer.uses_opengl)
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing)

            is_rounded = self._is_custom_frameless_windowed_mode()
            path = QPainterPath()
            if is_rounded:
                rect = QRectF(self.rect())
                radius = 20.0
                left = rect.left()
                top = rect.top()
                right = rect.right()
                bottom = rect.bottom()

                path.moveTo(left, top)
                path.lineTo(right, top)
                path.lineTo(right, bottom - radius)
                path.quadTo(right, bottom, right - radius, bottom)
                path.lineTo(left + radius, bottom)
                path.quadTo(left, bottom, left, bottom - radius)
                path.lineTo(left, top)
                path.closeSubpath()
            else:
                path.addRect(QRectF(self.rect()))

            painter.setClipPath(path)
            scene_opacity = max(0.0, min(1.0, float(getattr(self, '_global_fade', 1.0))))

            # Always paint a solid fallback so transient GL hiccups do not show transparent flashes.
            if self._bg_crossfade_lerp >= 1.0:
                painter.setOpacity(scene_opacity)
                painter.fillPath(path, self._current_bg_color)
            else:
                painter.setOpacity(scene_opacity)
                painter.fillPath(path, self._old_bg_color)
                painter.setOpacity(scene_opacity * self._bg_crossfade_lerp)
                painter.fillPath(path, self._current_bg_color)
                painter.setOpacity(1.0)

            if self.blob_manager and not gl_active:
                # SmoothPixmapTransform is a good quality/performance tradeoff for the blobs.
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                for blob in self.blob_manager.blobs + self.blob_manager.dying_blobs:
                    if not blob.pixmap or blob.opacity <= 0.01: continue
                    painter.setOpacity(blob.opacity * scene_opacity)
                    
                    r = blob.radius * blob.scale
                    target_rect = QRectF(blob.center.x() - r, blob.center.y() - r, r * 2, r * 2)
                    painter.drawPixmap(target_rect, blob.pixmap, QRectF(blob.pixmap.rect()))

            painter.setOpacity(1.0)
        finally:
            painter.end() 
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._suspend_layout_updates:
            if self.background_renderer:
                self.background_renderer.resize(self.rect())
            if self.blob_manager:
                self.blob_manager.resize(self.size())
            return
        self.update_layout() 
        self._update_text_properties() 
        if hasattr(self, 'playlist_panel') and self.playlist_panel:
            self.playlist_panel.request_relayout(0)
        if self.title and self.artist:
            self.album_name.update_scroll() # Update scroll for album name
            self.title.update_scroll()
            self.artist.update_scroll()

        if self.blob_manager:
            self.blob_manager.resize(self.size())

        if self.background_renderer:
            self.background_renderer.resize(self.rect())

        if hasattr(self, 'overlay'):
            self.overlay.resize(self.container.size())
            # Reposition overlay if it's visible
            self._reposition_overlay_if_visible()

        self._bg_crossfade_lerp = 1.0 
        self.update()
    
    def moveEvent(self, event):
        """Handle window move events to reposition overlay on different monitors."""
        super().moveEvent(event)
        # Reposition overlay if it's visible when window moves
        if hasattr(self, 'overlay'):
            self._reposition_overlay_if_visible()

    def update_layout(self):
        width = self.width()
        height = self.height()
        if width == 0 or height == 0 or not self.details_widget:
            return

        effective_w = width
        effective_h = height
        extra_left = extra_top = extra_right = extra_bottom = 0

        from PyQt5.QtWidgets import QApplication
        screens = QApplication.screens()

        is_multi_monitor_layout = self.multi_monitor_mode and self.target_monitor_geo and self.total_screens_geo

        # --- NEW WALLPAPER MONITOR ISOLATION ---
        if self.is_wallpaper_mode and screens:
            # Ensure the index exists, default to 0
            if not hasattr(self, 'wallpaper_monitor_index'):
                self.wallpaper_monitor_index = 0
            
            # Keep index safely within bounds
            self.wallpaper_monitor_index = self.wallpaper_monitor_index % len(screens)
            
            target_geo = screens[self.wallpaper_monitor_index].geometry()
            
            # Find the total bounding box of the massive wallpaper window
            min_x = min([s.geometry().x() for s in screens])
            min_y = min([s.geometry().y() for s in screens])
            
            # Calculate offsets to push the UI specifically into the target screen's area
            rel_x = target_geo.x() - min_x
            rel_y = target_geo.y() - min_y
            target_w = target_geo.width()
            target_h = target_geo.height()
            
            effective_w = target_w
            effective_h = target_h
            
            # These "extra" margins physically shove the UI block out of the dead space
            extra_left = rel_x
            extra_top = rel_y
            extra_right = width - (rel_x + target_w)
            extra_bottom = height - (rel_y + target_h)

        elif is_multi_monitor_layout:
            target_geo = self.target_monitor_geo
            total_geo = self.total_screens_geo
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

        m = self.VERTICAL_ORIENTATION_MARGINS if is_vertical else self.NORMAL_MARGINS
        content_w = max(260, effective_w - m[0] - m[2])
        content_h = max(260, effective_h - m[1] - m[3])

        should_recompute_art_size = (
            self._cached_art_size_px is None
            or self._cached_art_is_vertical != is_vertical
            or content_w > (self._cached_content_w + 180)
            or content_h > (self._cached_content_h + 180)
        )
        if should_recompute_art_size:
            self._cached_art_size_px = self._compute_preferred_art_size(content_w, content_h, is_vertical)
            self._cached_art_is_vertical = is_vertical
            self._cached_content_w = content_w
            self._cached_content_h = content_h

        preferred_art_size = self._cached_art_size_px if self._cached_art_size_px is not None else self._compute_preferred_art_size(content_w, content_h, is_vertical)
        self._sync_art_and_lyrics_bounds(content_w, content_h, is_vertical, preferred_art_size)

        details_width = min(content_w, self._content_line_width_px + 40)
        self.details_widget.setFixedWidth(details_width)

        # Simplified vertical gap calculation (removed manual top_space math for perfect stretch centering)
        vertical_gap = max(24, min(64, int(content_h * 0.06)))

        if is_vertical:
            self.main_layout.setDirection(QBoxLayout.TopToBottom)
            self.main_layout.setContentsMargins(m[0] + extra_left, m[1] + extra_top, m[2] + extra_right, m[3] + extra_bottom)
            self.main_layout.setSpacing(vertical_gap)
            details_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
            self.title.setAlignment(Qt.AlignCenter)
            self.artist.setAlignment(Qt.AlignCenter)
            self.album_name.setAlignment(Qt.AlignCenter)
        else:
            self.main_layout.setDirection(QBoxLayout.LeftToRight)
            self.main_layout.setContentsMargins(m[0] + extra_left, m[1] + extra_top, m[2] + extra_right, m[3] + extra_bottom)
            self.main_layout.setSpacing(20)
            details_layout.setAlignment(Qt.AlignCenter)
            self.title.setAlignment(Qt.AlignCenter)
            self.album_name.setAlignment(Qt.AlignCenter)
            self.artist.setAlignment(Qt.AlignCenter)

        while self.main_layout.count():
            self.main_layout.takeAt(0)

        if is_vertical:
            details_layout.insertWidget(1, self.album_name)
            
            self.main_layout.addStretch(1) 
            self.main_layout.addWidget(self.art_container, 0, Qt.AlignHCenter)
            self.main_layout.addWidget(self.details_widget, 0, Qt.AlignHCenter)
            self.main_layout.addStretch(1)
            
            details_layout.setAlignment(self.progress_bar, Qt.AlignHCenter)
            if self.lyrics_label:
                details_layout.setAlignment(self.lyrics_label, Qt.AlignHCenter)
            if self.player_controls_bar:
                details_layout.setAlignment(self.player_controls_bar, Qt.AlignHCenter)
        else:
            details_layout.removeWidget(self.album_name)
            details_layout.insertWidget(0, self.album_name)
            
            # Calculate a fixed spacing gap to keep them clustered nicely together
            gap_between_art_and_text = max(30, int(content_w * 0.05))
            
            self.main_layout.addStretch(1)
            if self.player_art_side == "right":
                # Notice we removed the "4" and "5" stretch values, replacing them with "0" so they cluster
                self.main_layout.addWidget(self.details_widget, 0, Qt.AlignVCenter)
                self.main_layout.addSpacing(gap_between_art_and_text)
                self.main_layout.addWidget(self.art_container, 0, Qt.AlignVCenter)
            else:
                self.main_layout.addWidget(self.art_container, 0, Qt.AlignVCenter)
                self.main_layout.addSpacing(gap_between_art_and_text)
                self.main_layout.addWidget(self.details_widget, 0, Qt.AlignVCenter)
            self.main_layout.addStretch(1)
            
            details_layout.addWidget(self.progress_bar, 0, Qt.AlignCenter)
            if self.lyrics_label:
                details_layout.setAlignment(self.lyrics_label, Qt.AlignCenter)
            if self.player_controls_bar:
                details_layout.setAlignment(self.player_controls_bar, Qt.AlignCenter)

        self.details_widget.setContentsMargins(20 if is_vertical else 40, 0, 20, 0)
        self.update() 
        self._update_text_properties()

    @pyqtSlot(dict)
    def _on_playback_state_changed(self, data):
        if not self._is_media_method_enabled('spotify'):
            return
        is_playing = data.get("is_playing", False)
        self._last_progress_val = data.get("progress_ms", 0)
        self._last_progress_sync_time = QDateTime.currentMSecsSinceEpoch()
        
        is_paused = not is_playing
        if is_paused == self._is_paused:
            return
        self._is_paused = is_paused

        # If Spotify starts playing (was paused, now playing) while we are viewing
        # another media source, we should switch back to Spotify.
        if is_playing and self.active_media_source != 'spotify' and self._last_spotify_track_data and self._is_media_method_enabled('spotify'):
            # A spotify track exists and has just started playing. Re-assert it as the active source.
            self._last_spotify_track_data['is_playing'] = True
            self._on_spotify_track_changed(self._last_spotify_track_data)
        
    def setBgCrossfadeLerp(self, value):
        self._bg_crossfade_lerp = value
        self._update_native_titlebar_color()
        self.update()

    def setTextAlpha(self, alpha): 
        if self.title and self.artist and self.album_name: 
            self._text_alpha=int(alpha)
            self.setTextColor(self._cur_text_color)
            
    def setTextColor(self, color):
        self._cur_text_color = color
        text_with_alpha = QColor(color)
        text_with_alpha.setAlpha(self._text_alpha) # Apply alpha to text color
        title_gradient_enabled = self._current_title_gradient_enabled
        title_gradient_color = QColor(*self._current_title_gradient_color)
        title_gradient_direction = self._current_title_gradient_direction

        border_c = QColor(*self._current_text_border_color)
        border_c.setAlpha(self._text_alpha)

        shadow_color = QColor(0, 0, 0) 
        shadow_color.setAlpha(int((100 / 255) * self._text_alpha)) 

        # Apply alpha to album name and lyrics shadow and text
        if self.album_name.graphicsEffect(): self.album_name.graphicsEffect().setColor(shadow_color)
        if self.lyrics_label and self.lyrics_label.graphicsEffect(): self.lyrics_label.graphicsEffect().setColor(shadow_color)
        self.album_name.setTextColor(text_with_alpha)
        self.album_name.setGradient(title_gradient_enabled, title_gradient_color, title_gradient_direction)
        self.album_name.setBorder(self._current_text_border_enabled, border_c)
        self.album_name.setBorder(self._current_text_border_enabled, border_c, self._current_text_border_size)
        
        if self.title.graphicsEffect(): self.title.graphicsEffect().setColor(shadow_color)
        if self.artist.graphicsEffect(): self.artist.graphicsEffect().setColor(shadow_color)

        self.title.setTextColor(text_with_alpha)
        self.title.setGradient(title_gradient_enabled, title_gradient_color, title_gradient_direction)
        self.title.setBorder(self._current_text_border_enabled, border_c)
        self.title.setBorder(self._current_text_border_enabled, border_c, self._current_text_border_size)
        self.artist.setTextColor(text_with_alpha)
        self.artist.setGradient(title_gradient_enabled, title_gradient_color, title_gradient_direction)
        self.artist.setBorder(self._current_text_border_enabled, border_c)
        self.artist.setBorder(self._current_text_border_enabled, border_c, self._current_text_border_size)
        self.progress_bar.set_color(text_with_alpha)
        if self.lyrics_label:
            self.lyrics_label.setTextColor(text_with_alpha)
            self.lyrics_label.setGradient(title_gradient_enabled, title_gradient_color, title_gradient_direction)
            self.lyrics_label.setBorder(self._current_text_border_enabled, border_c, self._current_text_border_size)
        if self.player_controls_bar:
            self.player_controls_bar.set_text_color(text_with_alpha)

    def update_art_shadow_properties(self):
        if not self.art_shadow: return
        self.art_shadow.setBlurRadius(40)
        self.art_shadow.setColor(QColor(0, 0, 0, 80))
        self.art_shadow.setOffset(0, 8)
        self.art_shadow.setEnabled(self.art._opacity > 0)

    def _resolve_safe_font_family(self, family: str) -> str:
        """Return *family* if available on this system, otherwise fall back to a safe default."""
        if not family:
            return "Trebuchet MS"
        available = QFontDatabase().families()
        if family in available:
            return family
        fallbacks = ["Trebuchet MS", "Segoe UI", "Arial", "Sans Serif"]
        for fb in fallbacks:
            if fb in available:
                return fb
        return fallbacks[0]

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
        safe_family = self._resolve_safe_font_family(self._current_font_family)
        if safe_family != self._current_font_family:
            self._current_font_family = safe_family

        title_font = db.font(safe_family, self._current_font_style, -1)
        title_font.setPixelSize(int(max(12, 28 * scale_factor * user_scale)))
        self.title.setFont(title_font)

        artist_font = db.font(safe_family, self._current_font_style, -1)
        artist_font.setPixelSize(int(max(10, 22 * scale_factor * user_scale)))
        self.artist.setFont(artist_font)
        
        # New: Album name font size
        album_font = db.font(safe_family, self._current_font_style, -1)
        album_font.setPixelSize(int(max(9, 18 * scale_factor * user_scale))) # Slightly smaller than artist
        self.album_name.setFont(album_font)

        lyrics_font = db.font(safe_family, self._current_font_style, -1)
        lyrics_font.setPixelSize(int(max(9, 18 * scale_factor * user_scale)))
        if self.lyrics_label:
            self.lyrics_label.setFont(lyrics_font)
            self.lyrics_label.setMaxLines(2)

        self.title.setFixedHeight(max(34, QFontMetrics(title_font).lineSpacing() * 2 + 6))
        self.artist.setFixedHeight(max(28, QFontMetrics(artist_font).lineSpacing() * 2 + 4))
        self.album_name.setFixedHeight(max(26, QFontMetrics(album_font).lineSpacing() * 2 + 4))
        if self.lyrics_label:
            lyric_metrics = QFontMetrics(lyrics_font)
            self.lyrics_label.setFixedHeight(max(42, lyric_metrics.lineSpacing() * 2 + 8))

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
        if self.lyrics_label and self.lyrics_label.graphicsEffect():
            self.lyrics_label.graphicsEffect().setBlurRadius(max(6, 13 * scale_factor))
            self.lyrics_label.graphicsEffect().setOffset(offset_val, offset_val)
            self.lyrics_label.graphicsEffect().setEnabled(self._current_shadow_enabled)

        self.title.setContentsMargins(0, 0, 0, int(offset_val) + 2)
        self.setTextColor(self._cur_text_color)

    def open_settings_dialog(self):
        """Shows the pre-loaded settings/color editor dialog."""
        if not self.settings_dialog:
            self._setup_settings_dialog()

        if hasattr(self.settings_dialog, "_is_closing_via_save"):
            self.settings_dialog._is_closing_via_save = False

        pixmap = self.art.pixmap()
        if not pixmap or pixmap.isNull():
            pixmap = QPixmap(resource_path('icon.ico')).scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        album_id = self._current_album_id or "no-album"
        track_id = self._current_track_id or "no-track"
        media_source = self.active_media_source or 'none'

        # --- GET METADATA ---
        current_album = self.album_name.text() if self.album_name else "Unknown Album"
        current_artist = self.artist.text() if self.artist else "Unknown Artist"
        
        self.settings_dialog.media_source = media_source
        # Pass metadata
        self.settings_dialog.load_track_state(
            album_id, 
            track_id, 
            pixmap, 
            animate=False, 
            album_name=current_album, 
            artist_name=current_artist
        )

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

    def _start_close_fade(self):
        if self._close_fade_started:
            return
        self._close_fade_started = True

        # Keep content visible while fading out so the whole player transition is obvious.
        self._set_player_content_visible(True)

        content_start = self.art._opacity if hasattr(self, 'art') and self.art else 1.0
        self._close_content_anim = QVariantAnimation(self)
        self._close_content_anim.setDuration(420)
        self._close_content_anim.setStartValue(float(content_start))
        self._close_content_anim.setEndValue(0.0)
        self._close_content_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._close_content_anim.valueChanged.connect(self._set_player_content_opacity)

        self._close_window_anim = QPropertyAnimation(self, b"windowOpacity")
        self._close_window_anim.setDuration(560)
        self._close_window_anim.setStartValue(float(self.windowOpacity()))
        self._close_window_anim.setEndValue(0.0)
        self._close_window_anim.setEasingCurve(QEasingCurve.OutQuad)

        self._close_bg_anim = QPropertyAnimation(self, b"globalFade")
        self._close_bg_anim.setDuration(560)
        self._close_bg_anim.setStartValue(float(self._global_fade))
        self._close_bg_anim.setEndValue(0.0)
        self._close_bg_anim.setEasingCurve(QEasingCurve.OutQuad)

        self._close_anim_group = QParallelAnimationGroup(self)
        self._close_anim_group.addAnimation(self._close_content_anim)
        self._close_anim_group.addAnimation(self._close_window_anim)
        self._close_anim_group.addAnimation(self._close_bg_anim)
        self._close_anim_group.finished.connect(self._finalize_close_after_fade)
        self._close_anim_group.start()

    def _finalize_close_after_fade(self):
        if self._is_closing:
            return
        self._is_closing = True
        self.close()

    def closeEvent(self, event):
        if not self._is_closing:
            event.ignore()
            self._start_close_fade()
            return

        self.threadpool.clear()

        if hasattr(self, 'spotify_worker') and self.spotify_worker: 
            self.spotify_worker.stop()
        if IS_WINDOWS:
            if hasattr(self, 'apple_music_worker') and self.apple_music_worker: 
                self.apple_music_worker.stop()
            if hasattr(self, 'windows_worker') and self.windows_worker: 
                self.windows_worker.stop()
        
        
        # Wait for running tasks to finish. With the improved worker sleep, this should be fast.
        if not self.threadpool.waitForDone(2000): # Wait up to 2 seconds
            print("Warning: Background threads did not finish gracefully.")
        
        # Clean up worker references
        if hasattr(self, 'spotify_worker'):
            del self.spotify_worker
        if IS_WINDOWS:
            if hasattr(self, 'apple_music_worker'):
                del self.apple_music_worker
            if hasattr(self, 'windows_worker'):
                del self.windows_worker
        if hasattr(self, 'background_renderer') and self.background_renderer:
            self.background_renderer.teardown()
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
        
    def toggle_fullscreen_mode(self):
        """Toggle between borderless fullscreen and windowed mode."""
        self._handle_fullscreen_hotkey()

    def _can_start_monitor_hop(self):
        now_ms = QDateTime.currentMSecsSinceEpoch()
        if self._monitor_shift_animating:
            return False
        if (now_ms - self._last_monitor_shift_ms) < self._monitor_shift_cooldown_ms:
            return False
        self._monitor_shift_animating = True
        self._last_monitor_shift_ms = now_ms
        return True

    def _finish_monitor_hop(self):
        self._monitor_shift_animating = False
        self._restore_overlay_visibility()

    def _run_invisible_monitor_hop(self, apply_change):
        if not self._can_start_monitor_hop():
            return False

        # Lazy-create the veil overlay on first use.
        if not hasattr(self, '_hop_overlay') or self._hop_overlay is None:
            self._hop_overlay = _MonitorHopOverlay(self)

        self._remember_overlay_visibility()
        self.notification_widget.fade_out()

        # Use a child-widget black veil instead of setWindowOpacity so the window
        # stays at opacity 1.0 throughout — avoids DWM / OpenGL compositing flicker.
        overlay = self._hop_overlay
        overlay.setGeometry(self.rect())
        overlay.set_alpha(0)
        overlay.raise_()
        overlay.show()

        fade_out = QPropertyAnimation(overlay, b"alpha")
        fade_out.setDuration(120)
        fade_out.setStartValue(0)
        fade_out.setEndValue(255)
        fade_out.setEasingCurve(QEasingCurve.OutCubic)

        def apply_change_and_settle():
            apply_change()
            overlay.setGeometry(self.rect())
            self.update_layout()
            self._update_text_properties()
            if hasattr(self, 'playlist_panel') and self.playlist_panel:
                self.playlist_panel.request_relayout(0)
            if self.background_renderer:
                self.background_renderer.resize(self.rect())
                self.background_renderer.tick()

            QTimer.singleShot(max(60, int(self._monitor_shift_settle_ms)), start_fade_in)

        def start_fade_in():
            overlay.setGeometry(self.rect())
            self.update_layout()
            self._update_text_properties()
            if hasattr(self, 'playlist_panel') and self.playlist_panel:
                self.playlist_panel.request_relayout(0)
            if self.background_renderer:
                self.background_renderer.resize(self.rect())
                self.background_renderer.tick()

            fade_in = QPropertyAnimation(overlay, b"alpha")
            fade_in.setDuration(180)
            fade_in.setStartValue(255)
            fade_in.setEndValue(0)
            fade_in.setEasingCurve(QEasingCurve.InOutCubic)
            fade_in.finished.connect(finish)
            self._monitor_hop_fade_in_anim = fade_in
            fade_in.start()

        def finish():
            overlay.hide()
            self._finish_monitor_hop()

        fade_out.finished.connect(apply_change_and_settle)
        self._monitor_hop_fade_out_anim = fade_out
        fade_out.start()
        return True
    
    def switch_monitor(self):
        """Cycle to the next monitor."""
        screens = QApplication.screens()
        if len(screens) < 2:
            return  # Only one monitor, do nothing
        
        screens.sort(key=lambda s: (s.geometry().x(), s.geometry().y()))
        self._remember_overlay_visibility()
        
        current_screen = QApplication.screenAt(self.geometry().center())
        if not current_screen:
            current_screen = screens[0]
        
        try:
            index = screens.index(current_screen)
        except ValueError:
            index = 0
        
        # Cycle to next monitor
        new_index = (index + 1) % len(screens)
        new_screen = screens[new_index]

        def apply_change():
            if self.is_fullscreen and not self.multi_monitor_mode:
                if self.windowHandle() and new_screen:
                    self.windowHandle().setScreen(new_screen)
                self.setGeometry(new_screen.geometry())
            else:
                geo = new_screen.availableGeometry()
                w, h = self.width(), self.height()
                x = geo.x() + (geo.width() - w) // 2
                y = geo.y() + (geo.height() - h) // 2
                self.setGeometry(x, y, w, h)

        self._run_invisible_monitor_hop(apply_change)
    
    def toggle_multi_monitor_fullscreen(self):
        self._remember_overlay_visibility()
        screens = QApplication.screens()
        if not screens:
            return  # Handle case with no screens

        total_rect = QRect()
        for screen in screens:
            total_rect = total_rect.united(screen.geometry())

        if self.multi_monitor_mode:
            self.multi_monitor_mode = False
            self._apply_window_mode_flags()
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
            self._apply_window_mode_flags()
            self.setGeometry(total_rect)
            self.show()
            self.is_fullscreen = True
        
        # Trigger playlist panel relayout after multi-monitor toggle
        if hasattr(self, 'playlist_panel') and self.playlist_panel:
            QTimer.singleShot(50, self.playlist_panel.relayout)

        self._update_native_titlebar_color()
        
        QTimer.singleShot(0, self._restore_overlay_visibility)
            
    def shift_multi_monitor_content(self, direction):
        # Allow shifting if in multi-monitor OR in wallpaper that came from multi-monitor
        is_in_valid_state = self.multi_monitor_mode or (self.is_wallpaper_mode and hasattr(self, '_was_multi_monitor') and self._was_multi_monitor)
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
            new_geo = screens[new_index].geometry()

            def apply_change():
                self.target_monitor_geo = new_geo
                if self.is_wallpaper_mode:
                    self._saved_target_monitor_geo = new_geo

            self._run_invisible_monitor_hop(apply_change)

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

        def apply_change():
            if self.is_fullscreen and not self.multi_monitor_mode and not self.is_wallpaper_mode:
                if self.windowHandle() and new_screen:
                    self.windowHandle().setScreen(new_screen)
                self.setGeometry(new_screen.geometry())
            else:
                self.setGeometry(new_screen.geometry())

        self._run_invisible_monitor_hop(apply_change)

    def _find_workerw_for_wallpaper(self):
        if not IS_WINDOWS:
            return None
        try:
            user32 = ctypes.windll.user32
            SMTO_NORMAL = 0x0000
            progman = user32.FindWindowW("Progman", None)
            if progman:
                result = ctypes.c_ulong(0)
                user32.SendMessageTimeoutW(progman, 0x052C, 0, 0, SMTO_NORMAL, 1000, ctypes.byref(result))

            workerw = ctypes.c_void_p(0)

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def enum_windows_proc(hwnd, _lparam):
                def_view = user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None)
                if def_view:
                    candidate = user32.FindWindowExW(0, hwnd, "WorkerW", None)
                    if candidate:
                        workerw.value = candidate
                        return False
                return True

            user32.EnumWindows(enum_windows_proc, 0)
            if workerw.value:
                return int(workerw.value)
        except Exception as e:
            print(f"Wallpaper mode: failed to locate WorkerW host ({e})")
        return None

    def _attach_to_desktop_wallpaper_layer(self):
        if not (IS_WINDOWS and self.is_wallpaper_mode):
            return False
        try:
            hwnd = int(self.winId()) if self.winId() else 0
            if not hwnd:
                return False

            target_parent = self._find_workerw_for_wallpaper()
            if not target_parent:
                target_parent = ctypes.windll.user32.FindWindowW("Progman", None)
            if not target_parent:
                return False

            ctypes.windll.user32.SetParent(hwnd, target_parent)
            self._desktop_parent_hwnd = target_parent
            return True
        except Exception as e:
            print(f"Wallpaper mode: desktop attach failed ({e})")
            return False

    def _detach_from_desktop_wallpaper_layer(self):
        if not IS_WINDOWS:
            self._desktop_parent_hwnd = None
            return
        try:
            hwnd = int(self.winId()) if self.winId() else 0
            if hwnd and self._desktop_parent_hwnd:
                ctypes.windll.user32.SetParent(hwnd, 0)
        except Exception as e:
            print(f"Wallpaper mode: desktop detach failed ({e})")
        finally:
            self._desktop_parent_hwnd = None

    def toggle_wallpaper_mode(self):
        self._remember_overlay_visibility()
        
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import Qt, QTimer

        if self.is_wallpaper_mode:
            # --- EXITING WALLPAPER MODE ---
            self.is_wallpaper_mode = False
            if self.tray_icon: self.tray_icon.hide()
            
            # Reapply correct window flags based on the restored mode
            if getattr(self, '_was_multi_monitor', False):
                self.multi_monitor_mode = True
                self.is_fullscreen = True
                self.target_monitor_geo = self._saved_target_monitor_geo
                self.total_screens_geo = self._saved_total_screens_geo
                self._apply_window_mode_flags()
                self.setGeometry(self._saved_geometry)
                self.show()
            elif getattr(self, '_was_fullscreen', False):
                self.is_fullscreen = True
                self._apply_window_mode_flags()
                self.setGeometry(self._saved_geometry)
                self._enter_borderless_fullscreen()
            else:
                self.is_fullscreen = False
                self._apply_window_mode_flags()
                if hasattr(self, '_saved_geometry') and self._saved_geometry:
                    self.setGeometry(self._saved_geometry)
                self.showNormal()
                self.show()
                
            self.update_layout()
            
        else:
            # --- ENTERING WALLPAPER MODE ---
            # 1. Save current state so we can restore it later
            self._saved_geometry = self.geometry()
            self._was_fullscreen = self.is_fullscreen
            self._was_multi_monitor = self.multi_monitor_mode
            if self.multi_monitor_mode:
                self._saved_target_monitor_geo = self.target_monitor_geo
                self._saved_total_screens_geo = self.total_screens_geo

            # 2. Set Wallpaper Mode State
            self.is_wallpaper_mode = True
            self.multi_monitor_mode = False
            self.is_fullscreen = False
            
            # 3. Apply Wallpaper Window Flags
            self._apply_window_mode_flags()
            
            # 4. Stretch across all monitors
            min_x = min([screen.geometry().x() for screen in QApplication.screens()])
            min_y = min([screen.geometry().y() for screen in QApplication.screens()])
            max_x = max([screen.geometry().x() + screen.geometry().width() for screen in QApplication.screens()])
            max_y = max([screen.geometry().y() + screen.geometry().height() for screen in QApplication.screens()])
            
            self.setGeometry(min_x, min_y, max_x - min_x, max_y - min_y)
            
            # 5. Set active UI monitor to the Primary Screen
            for i, s in enumerate(QApplication.screens()):
                if s == QApplication.primaryScreen():
                    self.wallpaper_monitor_index = i
                    break
            
            self.showNormal()
            self.show()
            
            if self.tray_icon: self.tray_icon.show()
            
            if hasattr(self, 'overlay') and not self.overlay.isHidden():
                self.overlay.fade_out()
                
        # Update UI components
        if hasattr(self, 'playlist_panel') and self.playlist_panel:
            QTimer.singleShot(50, self.playlist_panel.relayout)

        self._sync_background_renderer_mode()
        self._update_native_titlebar_color()
        QTimer.singleShot(0, self._restore_overlay_visibility)

    def _position_overlay_at_monitor_bottom(self):
        """Position the overlay centered at the bottom of the current monitor.
        Handles sizing to fit within monitor bounds.
        """
        # Determine which monitor the player is on
        monitor_geo = None
        if self.multi_monitor_mode and self.target_monitor_geo:
            monitor_geo = self.target_monitor_geo
        else:
            # In single monitor or fullscreen, use the player's current screen
            screen = QApplication.screenAt(self.geometry().center())
            if screen:
                monitor_geo = screen.geometry()
            else:
                screens = QApplication.screens()
                if screens:
                    monitor_geo = screens[0].geometry()
        
        if monitor_geo:
            overlay_width = self.overlay.width()
            overlay_height = self.overlay.height()
            window_geo = self.geometry()
            
            # Check if overlay fits in monitor
            available_height = monitor_geo.height() - 100  # 100px margin
            available_width = monitor_geo.width()
            
            # Constrain if too large
            if overlay_height > available_height:
                constrained_height = max(available_height, 150)
                self.overlay.resize(overlay_width, constrained_height)
                overlay_height = constrained_height
            
            if overlay_width > available_width:
                constrained_width = available_width - 40
                self.overlay.resize(constrained_width, overlay_height)
                overlay_width = constrained_width
            
            # Center within the monitor using window-local coordinates
            local_left = monitor_geo.left() - window_geo.left()
            local_top = monitor_geo.top() - window_geo.top()
            x = local_left + (monitor_geo.width() - overlay_width) // 2
            y = local_top + monitor_geo.height() - overlay_height - 60  # 60px margin
            self.overlay.move(x, y)

    def _position_overlay_at_window_bottom(self):
        """Position the overlay centered at the bottom of the player window.
        Handles all window orientations (portrait/landscape) and ensures content fits.
        """
        if not self.overlay:
            return

        win_geo = self.geometry()
        overlay_width = self.overlay.width()
        overlay_height = self.overlay.height()
        
        # Calculate available space
        available_height = win_geo.height() - 100  # 100px margin from top/bottom
        available_width = win_geo.width()
        
        # If overlay is too tall, we need to constrain it
        if overlay_height > available_height:
            # Reduce overlay height to fit with some margin
            constrained_height = max(available_height, 150)  # Minimum 150px
            self.overlay.resize(overlay_width, constrained_height)
            overlay_height = constrained_height
        
        # If overlay is wider than window, constrain width
        if overlay_width > available_width:
            constrained_width = available_width - 40  # 20px margin on each side
            self.overlay.resize(constrained_width, overlay_height)
            overlay_width = constrained_width
        
        # Center horizontally within window
        x = win_geo.left() + (win_geo.width() - overlay_width) // 2
        
        # Position near bottom with margin, but ensure it fits
        margin = 16
        y = win_geo.bottom() - overlay_height - margin
        
        # Ensure overlay does not go above the top of the window
        if y < win_geo.top() + 50:
            y = win_geo.top() + 50
        
        self.overlay.move(x, y)

    def _should_live_reload_settings_dialog(self):
        if not self.settings_dialog:
            return False
        if not self.settings_dialog.isVisible():
            return False
        if getattr(self.settings_dialog, "_is_closing_via_save", False):
            return False
        return True

    def _get_corner_at_position(self, pos):
        """
        Determine if position is within a circular corner region and return which corner.
        The resizable area is a circle that fits within the window's rounded corner.
        """
        radius = 40  # Circular resize area radius
        width = self.width()
        height = self.height()
        
        # Calculate distance from each corner
        # Top-left corner
        dist_tl = ((pos.x() - 0) ** 2 + (pos.y() - 0) ** 2) ** 0.5
        if dist_tl < radius:
            return "TL"
        
        # Top-right corner
        dist_tr = ((pos.x() - width) ** 2 + (pos.y() - 0) ** 2) ** 0.5
        if dist_tr < radius:
            return "TR"
        
        # Bottom-left corner
        dist_bl = ((pos.x() - 0) ** 2 + (pos.y() - height) ** 2) ** 0.5
        if dist_bl < radius:
            return "BL"
        
        # Bottom-right corner
        dist_br = ((pos.x() - width) ** 2 + (pos.y() - height) ** 2) ** 0.5
        if dist_br < radius:
            return "BR"
        
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            # Only show the overlay on right-click
            if self.overlay.isHidden():
                # --- NEW: Force playlist panel to recount its grid for the active monitor ---
                if hasattr(self, 'playlist_panel') and self.playlist_panel:
                    self.playlist_panel.relayout()
                # --------------------------------------------------------------------------
                
                self.overlay.update_size()
                if not (self.is_fullscreen or self.multi_monitor_mode or self.is_wallpaper_mode):
                    self._position_overlay_at_window_bottom()
                else:
                    self._position_overlay_at_monitor_bottom()
                self.overlay.fade_in()
            else:
                self.overlay.fade_out()
            event.accept()
            return
            
        elif event.button() == Qt.LeftButton:
            if self._is_custom_frameless_windowed_mode():
                corner = self._get_corner_at_position(event.pos())
                if corner:
                    self.resize_corner = corner
                    self.resize_start_rect = self.geometry()
                    self.resize_start_pos = event.globalPos()
                    event.accept()
                else:
                    self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
                    event.accept()
            else:
                super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)
    
    def _reposition_overlay_if_visible(self, force_show=False):
        """Reposition the overlay if it's visible; optionally force-show it."""
        if not self.overlay:
            return
        if not self._is_overlay_mode_allowed():
            if not self.overlay.isHidden():
                self.overlay.fade_out()
                self._overlay_restore_pending = True
            return
        if self.overlay.isHidden():
            if not force_show:
                return
            self.overlay.show()
            self.overlay.raise_()
            if self.overlay.playlist_panel:
                self.overlay.playlist_panel.show()

        self.overlay.update_size()
        if not (self.is_fullscreen or self.multi_monitor_mode or self.is_wallpaper_mode):
            self._position_overlay_at_window_bottom()
        else:
            self._position_overlay_at_monitor_bottom()

    def _force_playlist_panel_relayout(self):
        if not hasattr(self, 'playlist_panel') or not self.playlist_panel:
            return
        self.playlist_panel.request_relayout(0)
        if hasattr(self, 'overlay') and self.overlay:
            self.overlay.update_size()
        if self.overlay and self.overlay.isVisible():
            if not (self.is_fullscreen or self.multi_monitor_mode or self.is_wallpaper_mode):
                self._position_overlay_at_window_bottom()
            else:
                self._position_overlay_at_monitor_bottom()

    def _remember_overlay_visibility(self):
        """Remember whether the overlay was visible before a mode change."""
        currently_visible = bool(self.overlay and not self.overlay.isHidden())
        pending_restore = bool(getattr(self, "_overlay_restore_pending", False))
        self._overlay_was_visible = currently_visible or pending_restore

    def _is_overlay_mode_allowed(self):
        return bool(self.is_fullscreen or self.multi_monitor_mode or self.is_wallpaper_mode)

    def _restore_overlay_visibility(self):
        """Restore overlay visibility after a mode change if it was visible."""
        if not self.overlay:
            return

        should_restore = bool(
            getattr(self, "_overlay_was_visible", False)
            or getattr(self, "_overlay_restore_pending", False)
        )

        if not self._is_overlay_mode_allowed():
            if should_restore and not self.overlay.isHidden():
                self.overlay.fade_out()
            self._overlay_restore_pending = should_restore
            return

        if not should_restore:
            return

        if hasattr(self, 'playlist_panel') and self.playlist_panel:
            self.playlist_panel.request_relayout(0)

        self.overlay.update_size()
        self._position_overlay_at_monitor_bottom()
        if self.overlay.isHidden():
            self.overlay.fade_in()
        else:
            self.overlay.raise_()

        self._overlay_restore_pending = False
        self._overlay_was_visible = False

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            if self.resize_corner:
                # Handle window resizing based on corner
                current_global_pos = event.globalPos()
                delta_x = current_global_pos.x() - self.resize_start_pos.x()
                delta_y = current_global_pos.y() - self.resize_start_pos.y()
                
                min_width = 300
                min_height = 300
                
                # Calculate new geometry based on which corner is being dragged
                new_x = self.resize_start_rect.x()
                new_y = self.resize_start_rect.y()
                new_width = self.resize_start_rect.width()
                new_height = self.resize_start_rect.height()
                
                if self.resize_corner == "BR":
                    # Bottom-right: only width and height change
                    new_width = max(min_width, self.resize_start_rect.width() + delta_x)
                    new_height = max(min_height, self.resize_start_rect.height() + delta_y)
                elif self.resize_corner == "BL":
                    # Bottom-left: x and width change left, height changes bottom
                    new_x = self.resize_start_rect.x() + delta_x
                    new_width = max(min_width, self.resize_start_rect.width() - delta_x)
                    new_height = max(min_height, self.resize_start_rect.height() + delta_y)
                elif self.resize_corner == "TR":
                    # Top-right: y and height change up, width changes right
                    new_y = self.resize_start_rect.y() + delta_y
                    new_width = max(min_width, self.resize_start_rect.width() + delta_x)
                    new_height = max(min_height, self.resize_start_rect.height() - delta_y)
                elif self.resize_corner == "TL":
                    # Top-left: x,y and both width,height change
                    new_x = self.resize_start_rect.x() + delta_x
                    new_y = self.resize_start_rect.y() + delta_y
                    new_width = max(min_width, self.resize_start_rect.width() - delta_x)
                    new_height = max(min_height, self.resize_start_rect.height() - delta_y)
                
                # Just set geometry without updating layout - layout update happens in mouseReleaseEvent
                self.setGeometry(new_x, new_y, new_width, new_height)
                # If overlay is visible, keep it anchored to the bottom-center of the window
                if self.overlay and self.overlay.isVisible():
                    # Only use window-bottom positioning for windowed mode
                    if not (self.is_fullscreen or self.multi_monitor_mode or self.is_wallpaper_mode):
                        self._position_overlay_at_window_bottom()
                    else:
                        self._position_overlay_at_monitor_bottom()
                event.accept()
            elif self.drag_pos:
                # Handle window dragging
                if self._is_custom_frameless_windowed_mode():
                    self.move(event.globalPos() - self.drag_pos)
                event.accept()
            else:
                super().mouseMoveEvent(event)
        else:
            # Update cursor when hovering over corners
            if self._is_custom_frameless_windowed_mode():
                corner = self._get_corner_at_position(event.pos())
                if corner == "TL" or corner == "BR":
                    self.setCursor(Qt.SizeFDiagCursor)
                elif corner == "TR" or corner == "BL":
                    self.setCursor(Qt.SizeBDiagCursor)
                else:
                    self.setCursor(Qt.ArrowCursor)
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # Update layout only after resize is complete (not during dragging)
        if self.resize_corner:
            self.update_layout()
            # If overlay visible, ensure it's repositioned after the final resize
            if self.overlay and self.overlay.isVisible():
                if not (self.is_fullscreen or self.multi_monitor_mode or self.is_wallpaper_mode):
                    self._position_overlay_at_window_bottom()
                else:
                    self._position_overlay_at_monitor_bottom()
        self.drag_pos = None
        self.resize_corner = None
        self.resize_start_rect = None
        self.resize_start_pos = None
        super().mouseReleaseEvent(event)

    def _handle_fullscreen_hotkey(self):
        """Run the exact fullscreen/windowed flow used by the F key handler."""
        if self._mode_switch_in_progress:
            return
        self._remember_overlay_visibility()
        if self.is_wallpaper_mode:
            return
        self._begin_mode_switch_transition()
        if self.multi_monitor_mode:
            self.multi_monitor_mode = False
            self.is_fullscreen = True
            self._apply_window_mode_flags()
            target_screen = QApplication.screenAt(self.target_monitor_geo.center()) if self.target_monitor_geo else None
            self._enter_borderless_fullscreen(target_screen)
        elif self.is_fullscreen:
            self.is_fullscreen = False
            # Windowed mode: use native window decorations for proper snap layouts and edge resizing
            self._apply_window_mode_flags()
            self._clear_native_fullscreen_state()
            # Set a reasonable windowed size (80% of screen)
            screen = QApplication.screenAt(self.geometry().center())
            if not screen:
                screens = QApplication.screens()
                if screens:
                    screen = screens[0]
            if screen:
                screen_geo = screen.availableGeometry()
                new_width = int(screen_geo.width() * 0.8)
                new_height = int(screen_geo.height() * 0.8)
                new_x = screen_geo.x() + (screen_geo.width() - new_width) // 2
                new_y = screen_geo.y() + (screen_geo.height() - new_height) // 2
                self.setGeometry(new_x, new_y, new_width, new_height)
            self.show()
        else:
            self.is_fullscreen = True
            # Get the screen and set geometry to fill it completely
            screen = QApplication.screenAt(self.geometry().center())
            if not screen:
                screens = QApplication.screens()
                if screens:
                    screen = screens[0]
            if screen:
                self._apply_window_mode_flags()
                self._enter_borderless_fullscreen(screen)
            else:
                self._apply_window_mode_flags()
                self._enter_borderless_fullscreen()

        QTimer.singleShot(0, self._finalize_mode_switch_transition)
        QTimer.singleShot(0, self._restore_overlay_visibility)

    def keyPressEvent(self, event):
        from PyQt5.QtCore import Qt
        
        # 1. Handle Escape key
        if event.key() == Qt.Key_Escape:
            self.close()
            event.accept()
            return
            
        # 2. If in Wallpaper mode, intercept Left/Right arrow keys for monitor shifting
        if getattr(self, 'is_wallpaper_mode', False):
            if event.key() == Qt.Key_Left:
                self._shift_wallpaper_monitor(-1)
                event.accept()
                return
            elif event.key() == Qt.Key_Right:
                self._shift_wallpaper_monitor(1)
                event.accept()
                return

        # 3. RESTORED: Pass the key to the dynamic shortcut manager (Fixes F, C, F11, F12, L, etc.)
        action_id = self._shortcut_key_to_action.get(self._event_to_shortcut_text(event))
        if action_id and self._trigger_shortcut_action(action_id):
            event.accept()
            return
            
        # 4. Otherwise, pass the event along normally
        super().keyPressEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._startup_fade_done:
            self._startup_fade_done = True
            self.setWindowOpacity(0.0)
            self.globalFade = 0.0

            self._startup_window_anim = QPropertyAnimation(self, b"windowOpacity")
            self._startup_window_anim.setDuration(620)
            self._startup_window_anim.setStartValue(0.0)
            self._startup_window_anim.setEndValue(1.0)
            self._startup_window_anim.setEasingCurve(QEasingCurve.OutCubic)

            self._startup_bg_anim = QPropertyAnimation(self, b"globalFade")
            self._startup_bg_anim.setDuration(620)
            self._startup_bg_anim.setStartValue(0.0)
            self._startup_bg_anim.setEndValue(1.0)
            self._startup_bg_anim.setEasingCurve(QEasingCurve.OutCubic)

            self._startup_group = QParallelAnimationGroup(self)
            self._startup_group.addAnimation(self._startup_window_anim)
            self._startup_group.addAnimation(self._startup_bg_anim)
            self._startup_group.start()
        elif self.windowOpacity() < 0.999:
            self.setWindowOpacity(1.0)
        self._update_native_titlebar_color()

    @pyqtProperty(float)
    def globalFade(self):
        return self._global_fade

    @globalFade.setter
    def globalFade(self, value):
        self._global_fade = max(0.0, min(1.0, float(value)))
        if self.background_renderer:
            self.background_renderer.set_global_opacity(self._global_fade)
        self.update()

    def _shift_wallpaper_monitor(self, direction):
        from PyQt5.QtWidgets import QApplication
        screens = QApplication.screens()
        if not screens: return
        
        if not hasattr(self, 'wallpaper_monitor_index'):
            self.wallpaper_monitor_index = 0
            
        # Shift the index up or down, and wrap around if it goes past the ends
        self.wallpaper_monitor_index = (self.wallpaper_monitor_index + direction) % len(screens)
        
        # Recalculate margins and instantly snap the UI to the new monitor
        self.update_layout()

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
        player._enter_borderless_fullscreen()
    else:
        player.show()

    if hasattr(player, '_start_in_wallpaper') and player._start_in_wallpaper:
        QTimer.singleShot(100, player.toggle_wallpaper_mode)

    sys.exit(app.exec_())