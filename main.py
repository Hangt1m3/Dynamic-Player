# main.py
import sys
import os
import json
import io
import multiprocessing
from services import ColorCache, GoveeController, SoundManager, GlobalSoundFilter, AppleMusicClient
from PIL import Image
from requests import get

# --- FIXED IMPORTS ---
# QRectF, QPropertyAnimation, and QVariantAnimation moved to QtCore
from PyQt5.QtCore import (
    Qt, QTimer, QThreadPool, QSettings, QRect, QDateTime, pyqtSlot, QProcess, 
    pyqtProperty, QEasingCurve, QParallelAnimationGroup, QSequentialAnimationGroup,
    QAbstractAnimation, QPoint, QRectF, QPropertyAnimation, QVariantAnimation
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QBoxLayout, QVBoxLayout, QHBoxLayout,
    QGraphicsDropShadowEffect, QSizePolicy, QSystemTrayIcon, QMenu, QDialog, QPushButton
)
from PyQt5.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPixmap
)

from spotipy import Spotify, SpotifyOAuth

from config import SPOTIPY_REDIRECT_URI, SPOTIFY_SCOPE, SPOTIFY_GREEN, APPLE_MUSIC_RED
from utils import resource_path
from services import ColorCache, GoveeController
from workers import SpotifyPollingWorker, WindowsMediaWorker, TrackLoaderWorker, FontLoaderWorker, GoveeWorker, AppleMusicPollingWorker, IS_WINDOWS
from ui.widgets import ResponsiveAlbumArtLabel, ScrollingTextLabel, SmoothProgressBar, BlobManager, BorderedLabel
from ui.playlist_panel import PlaylistPanel
from utils import get_best_text_color, get_best_border_color
from ui.overlays import OverlayWidget, NotificationWidget
from ui.dialogs import ColorEditorDialog, SpotifySetupDialog, AppleMusicSetupDialog, ThemedMessageBox


class CircularWindowButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setFixedSize(30, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setProperty("no_text_border", True)

class SpotifyPlayer(QMainWindow):
    artOpacity = pyqtProperty(float, fget=lambda self: self.art._opacity if hasattr(self, 'art') else 1.0, fset=lambda self, o: self.art.setOpacity(o) if hasattr(self, 'art') else None)
    textAlpha = pyqtProperty(float, fget=lambda self: self._text_alpha, fset=lambda self, a: self.setTextAlpha(a))
    bgCrossfadeLerp = pyqtProperty(float, fget=lambda self: self._bg_crossfade_lerp, fset=lambda self, v: self.setBgCrossfadeLerp(v))

    def __init__(self):
        super().__init__()
        self._user_playlists = []  # Preloaded user playlists
        self._user_albums = []  # Preloaded user albums
        self.playlists = []  # Currently displayed playlists/albums (saved + user)
        # --- NEW: Global Sound Engine Setup ---
        self.sound_manager = SoundManager(self)
        self.sound_filter = GlobalSoundFilter(self.sound_manager)
        # Install the filter on the global application instance so it catches EVERYTHING
        QApplication.instance().installEventFilter(self.sound_filter)
        # --------------------------------------
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
        self.resize_corner = None  # Track which corner is being dragged: TL, TR, BL, BR, None
        self.resize_start_rect = None  # Store the window rect when resize starts
        self.resize_start_pos = None  # Store the mouse position when resize starts
        self.RESIZE_CORNER_SIZE = 15  # Pixel size for corner detection

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
        self.minimize_to_notification_only = True
        
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

        # Setup music services - order matters for priority
        did_show_spotify_setup = self._setup_spotify()
        did_show_apple_music_setup = self._setup_apple_music()
        did_show_setup = did_show_spotify_setup or did_show_apple_music_setup
        
        self._load_govee_settings() 
        self.color_cache = ColorCache()
        self._govee = GoveeController(self.govee_api_key, self.govee_devices)
        self._load_settings()

        if not did_show_setup:
            self._check_for_first_run()

        self._setup_ui()
        self._setup_window_controls()
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
        self.overlay.lights_button.clicked.connect(self.toggle_lights)
        self.overlay.fullscreen_button.clicked.connect(self.toggle_fullscreen_mode)
        self.overlay.switch_monitor_button.clicked.connect(self.switch_monitor)
        self.overlay.multi_monitor_button.clicked.connect(self.toggle_multi_monitor_fullscreen)
        self.overlay.wallpaper_button.clicked.connect(self.toggle_wallpaper_mode)
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
                <li><b>Exit:</b> Press <b>Esc</b> to close the application.</li>
            </ul>
            <p>Enjoy the vibes!</p>
            """
            ThemedMessageBox("Welcome!", tutorial_text, [("Let's Go!", QDialog.Accepted)], self, self._current_bg_color, QColor(*self._current_text_color), QColor(100, 100, 100), self._current_text_border_enabled, QColor(*self._current_text_border_color), self._current_text_border_size).exec_()
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

        self.title.setText("Dynamic Player")
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
        # Force conversion to string to prevent type errors
        self.govee_api_key = str(settings.value("govee_api_key", ""))
        
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

        # Numbers
        self.default_govee_brightness = safe_cast(settings.value("default_govee_brightness"), float, 1.0)
        # Fallback to legacy key if needed
        if settings.value("default_govee_brightness") is None:
             self.default_govee_brightness = safe_cast(settings.value("govee_brightness"), float, 1.0)

        self.blob_density = int(safe_cast(settings.value("blob_density"), float, 200000))
        
        sound_vol = safe_cast(settings.value("sound_volume"), float, 0.5)
        self.sound_manager.set_master_volume(sound_vol)

        # Fonts & Defaults
        self.default_font_family = str(settings.value("default_font_family", "Trebuchet MS"))
        self.default_font_style = str(settings.value("default_font_style", "Bold"))
        self.default_font_size_scale = int(safe_cast(settings.value("default_font_size_scale"), float, 100))
        self.default_progress_bar_enabled = as_bool(settings.value("default_progress_bar_enabled"), False)
        self.default_text_border_enabled = as_bool(settings.value("default_text_border_enabled"), False)
        self.default_text_border_size = int(safe_cast(settings.value("default_text_border_size"), float, 3))

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

    def _save_settings(self):
        settings = QSettings("SpotifySync", "App")
        settings.setValue("geometry", self.geometry())
        settings.setValue("fullscreen", "true" if self.is_fullscreen else "false")
        settings.setValue("lights_enabled", "true" if self.lights_enabled else "false")
        settings.setValue("default_govee_brightness", self.default_govee_brightness)
        
        # --- NEW: Save Override ---
        settings.setValue("govee_brightness_override", "true" if self.govee_brightness_override else "false")
        
        settings.setValue("blob_density", self.blob_density)
        settings.setValue("start_in_wallpaper_mode", "true" if self.is_wallpaper_mode else "false")

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

    def _setup_ui(self):
        self.setWindowTitle("Spotify Sync")
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
        self.art_container.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        art_container_layout = QVBoxLayout(self.art_container)
        art_container_layout.setContentsMargins(0,0,0,0)
        self.title_shadow = QGraphicsDropShadowEffect(self)
        self.artist_shadow = QGraphicsDropShadowEffect(self)
        self.art = ResponsiveAlbumArtLabel(radius=15)

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

        self.album_name = ScrollingTextLabel("–")
        self.album_name.setFont(QFont(font_family, 16))
        self.album_name.setGraphicsEffect(QGraphicsDropShadowEffect(self))
        self.album_name.setStyleSheet("background: transparent;")

        self.artist = ScrollingTextLabel("–")
        self.artist.setFont(QFont(font_family, 18))
        self.artist.setGraphicsEffect(self.artist_shadow) 
        self.artist.setStyleSheet("background: transparent;")

        self.progress_bar = SmoothProgressBar()

        self.details_layout.addWidget(self.title)
        self.details_layout.insertWidget(1, self.album_name)
        self.details_layout.addWidget(self.artist)
        self.details_layout.addWidget(self.progress_bar)

        art_container_layout.addWidget(self.art)

        self.main_layout.addStretch(1)
        self.main_layout.addWidget(self.art_container, 5)
        self.main_layout.addWidget(self.details_widget, 2, Qt.AlignCenter)
        self.main_layout.addStretch(1)

        self.title.setAlignment(Qt.AlignCenter)
        self.artist.setAlignment(Qt.AlignCenter)
        self.details_layout.setAlignment(Qt.AlignCenter)
        
        self.update_art_shadow_properties()
        self.setTextAlpha(self._text_alpha)

    def _setup_window_controls(self):
        self.window_controls = QWidget(self)
        controls_layout = QHBoxLayout(self.window_controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)

        self.minimize_button = CircularWindowButton("−", self.window_controls)
        self.fullscreen_button = CircularWindowButton("□", self.window_controls)
        self.close_button = CircularWindowButton("×", self.window_controls)

        self.minimize_button.setToolTip("Minimize / Notification-only mode")
        self.fullscreen_button.setToolTip("Toggle fullscreen")
        self.close_button.setToolTip("Close")

        self.minimize_button.clicked.connect(self._on_minimize_requested)
        self.fullscreen_button.clicked.connect(self._handle_fullscreen_hotkey)
        self.close_button.clicked.connect(self.close)

        self.minimize_button.setStyleSheet(
            "QPushButton {"
            " border: 1px solid rgba(255,255,255,100);"
            " border-radius: 15px;"
            " background-color: rgba(255,255,255,35);"
            " color: rgba(255,255,255,0);"
            " font-size: 16px;"
            " font-weight: bold;"
            "}"
            "QPushButton:hover {"
            " background-color: rgba(255,255,255,70);"
            " color: rgba(255,255,255,255);"
            "}"
        )
        self.fullscreen_button.setStyleSheet(
            "QPushButton {"
            " border: 1px solid rgba(255,255,255,100);"
            " border-radius: 15px;"
            " background-color: rgba(255,255,255,35);"
            " color: rgba(255,255,255,0);"
            " font-size: 14px;"
            " font-weight: bold;"
            "}"
            "QPushButton:hover {"
            " background-color: rgba(120,180,255,120);"
            " color: rgba(255,255,255,255);"
            "}"
        )
        self.close_button.setStyleSheet(
            "QPushButton {"
            " border: 1px solid rgba(255,255,255,100);"
            " border-radius: 15px;"
            " background-color: rgba(255,255,255,35);"
            " color: rgba(255,255,255,0);"
            " font-size: 18px;"
            " font-weight: bold;"
            "}"
            "QPushButton:hover {"
            " background-color: rgba(255,80,80,180);"
            " color: rgba(255,255,255,255);"
            "}"
        )

        controls_layout.addWidget(self.minimize_button)
        controls_layout.addWidget(self.fullscreen_button)
        controls_layout.addWidget(self.close_button)

        self.window_controls.adjustSize()
        self._position_window_controls()
        self._update_window_controls_visibility()
        self.window_controls.raise_()

    def _position_window_controls(self):
        if not hasattr(self, 'window_controls') or not self.window_controls:
            return
        margin = 12
        self.window_controls.adjustSize()
        x = max(margin, self.width() - self.window_controls.width() - margin)
        self.window_controls.move(x, margin)

    def _update_window_controls_visibility(self):
        if not hasattr(self, 'window_controls') or not self.window_controls:
            return
        is_windowed = not (self.is_fullscreen or self.multi_monitor_mode or self.is_wallpaper_mode or self.notification_only_mode)
        self.window_controls.setVisible(is_windowed)
        if is_windowed:
            self.window_controls.raise_()

    def _on_minimize_requested(self):
        if self.minimize_to_notification_only and self.tray_icon:
            if not self.notification_only_mode:
                self.toggle_notification_only_mode()
            return
        self.showMinimized()

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
        # Fallback: try to create a new client
        return Spotify(auth_manager=SpotifyOAuth(
            client_id=os.environ.get('SPOTIPY_CLIENT_ID'),
            client_secret=os.environ.get('SPOTIPY_CLIENT_SECRET'),
            redirect_uri=SPOTIPY_REDIRECT_URI,
            scope=SPOTIFY_SCOPE
        ))

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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Trigger playlist panel relayout when window is resized
        if hasattr(self, 'playlist_panel') and self.playlist_panel:
            self.playlist_panel.relayout()

    def _on_add_playlist_requested(self):
        # No longer used, handled in PlaylistPanel
        pass

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
            # Turn off shuffle first to ensure sequential playback
            if device_id:
                sp.shuffle(False, device_id=device_id)
                # Start playback from the beginning (position 0)
                sp.start_playback(device_id=device_id, context_uri=context_uri, offset={"position": 0})
            else:
                sp.shuffle(False)
                sp.start_playback(context_uri=context_uri, offset={"position": 0})
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
        # Play the selected playlist or album with shuffle enabled from the start
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
            # Enable shuffle first, then start playback from the beginning
            if device_id:
                sp.shuffle(True, device_id=device_id)
                # Start playback from the beginning (position 0) with shuffle enabled
                sp.start_playback(device_id=device_id, context_uri=context_uri, offset={"position": 0})
            else:
                sp.shuffle(True)
                sp.start_playback(context_uri=context_uri, offset={"position": 0})
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

    def _setup_animations(self):
        EASING_OUT = QEasingCurve.OutCubic
        EASING_IN_OUT = QEasingCurve.InOutCubic
        self.fade_in_group = QParallelAnimationGroup(self)
        self.fade_out_group = QParallelAnimationGroup(self)
        
        # Art Opacity Animations - Entrance
        art_anim_in = QPropertyAnimation(self, b"artOpacity")
        art_anim_in.setDuration(800)
        art_anim_in.setStartValue(0.0)
        art_anim_in.setEndValue(1.0)
        art_anim_in.setEasingCurve(EASING_OUT)
        self.fade_in_group.addAnimation(art_anim_in)
        
        # Art Opacity Animations - Exit
        art_anim_out = QPropertyAnimation(self, b"artOpacity")
        art_anim_out.setDuration(800)
        art_anim_out.setStartValue(1.0)
        art_anim_out.setEndValue(0.0)
        art_anim_out.setEasingCurve(EASING_OUT)
        self.fade_out_group.addAnimation(art_anim_out)

        # Staggered Text Entrance
        def add_staggered_anim(target, delay):
            # Opacity animation - start at 0.0 (fully transparent)
            op_anim = QPropertyAnimation(target, b"opacity")
            op_anim.setDuration(800)
            op_anim.setStartValue(0.0)
            op_anim.setEndValue(1.0)
            op_anim.setEasingCurve(QEasingCurve.Linear)
            
            # Slide In (From Left) - start at -40.0 offset
            slide_anim = QPropertyAnimation(target, b"anim_offset_x")
            slide_anim.setDuration(800)
            slide_anim.setStartValue(-40.0)
            slide_anim.setEndValue(0.0)
            slide_anim.setEasingCurve(QEasingCurve.OutCubic)
            
            if delay > 0:
                seq_op = QSequentialAnimationGroup()
                seq_op.addPause(delay)
                seq_op.addAnimation(op_anim)
                self.fade_in_group.addAnimation(seq_op)
                
                seq_slide = QSequentialAnimationGroup()
                seq_slide.addPause(delay)
                seq_slide.addAnimation(slide_anim)
                self.fade_in_group.addAnimation(seq_slide)
            else:
                self.fade_in_group.addAnimation(op_anim)
                self.fade_in_group.addAnimation(slide_anim)

        add_staggered_anim(self.title, 0)
        add_staggered_anim(self.album_name, 100)
        add_staggered_anim(self.artist, 200)

        # Text Exit (Slide Out to -40 then fade)
        def add_exit_anim(target, delay):
            # Slide out - moves text left while fading
            slide_out = QPropertyAnimation(target, b"anim_offset_x")
            slide_out.setDuration(800)
            slide_out.setStartValue(0.0)
            slide_out.setEndValue(-40.0)
            slide_out.setEasingCurve(QEasingCurve.InCubic)

            # Opacity - fade to transparent
            op_out = QPropertyAnimation(target, b"opacity")
            op_out.setDuration(800)
            op_out.setStartValue(1.0)
            op_out.setEndValue(0.0)
            op_out.setEasingCurve(QEasingCurve.Linear)

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
        bg_fade_out_anim = QPropertyAnimation(self, b"bgCrossfadeLerp")
        bg_fade_out_anim.setDuration(800)
        bg_fade_out_anim.setStartValue(1.0)
        bg_fade_out_anim.setEndValue(0.0)
        bg_fade_out_anim.setEasingCurve(EASING_OUT)
        self.fade_out_group.addAnimation(bg_fade_out_anim)
        
        # Art scale animation
        self.art_scale_anim = QPropertyAnimation(self.art, b"scale")
        self.art_scale_anim.setDuration(600)
        self.art_scale_anim.setStartValue(0.9)
        self.art_scale_anim.setEndValue(1.0)
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
        # Start Spotify worker if configured
        if self.sp:
            self.spotify_worker = SpotifyPollingWorker(self.sp)
            self.spotify_worker.signals.track_changed.connect(self._on_spotify_track_changed)
            self.spotify_worker.signals.playback_state_changed.connect(self._on_playback_state_changed)
            self.spotify_worker.signals.no_playback.connect(self._on_spotify_no_playback)
            self.threadpool.start(self.spotify_worker)
        
        # Start Apple Music worker if on Windows (uses system media controls)
        if IS_WINDOWS:
            self.apple_music_worker = AppleMusicPollingWorker(self.apple_music_client)
            self.apple_music_worker.signals.track_changed.connect(self._on_apple_music_track_changed)
            self.apple_music_worker.signals.no_playback.connect(self._on_apple_music_no_playback)
            self.threadpool.start(self.apple_music_worker)
            
            # Windows Media Player as fallback for other apps
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

            # If a non-Spotify source stopped and Spotify has a track (even paused), switch back to Spotify
            if source in ['windows', 'apple_music'] and self._last_spotify_track_data:
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

        is_visible = self.artOpacity > 0.01 or self.textAlpha > 1
        
        if is_visible:
            if self.fade_in_group.state() == QAbstractAnimation.Running:
                self.fade_in_group.stop()
            self._old_bg_color = self._current_bg_color
            if self.fade_out_group.state() != QAbstractAnimation.Running:
                self.fade_out_group.start()
        else:
            self._apply_pending_track_data()

        # Update Dialog if visible
        if self.settings_dialog and self.settings_dialog.isVisible():
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
            
            # Update Dialog image and metadata
            if self.settings_dialog and self.settings_dialog.isVisible():
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
        # Only change lights for Spotify tracks
        if self.active_media_source == 'spotify':
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
        self.minimize_to_notification_only = str(settings.value("minimize_to_notification_only", "true")).lower() == "true"
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
            self._update_window_controls_visibility()
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
            self._update_window_controls_visibility()

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
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
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
        finally:
            painter.end() 
    
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
            # Reposition overlay if it's visible
            self._reposition_overlay_if_visible()

        self._position_window_controls()
        self._update_window_controls_visibility()

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
        """Toggle between fullscreen and windowed mode on current monitor."""
        self._remember_overlay_visibility()
        if self.is_fullscreen and not self.multi_monitor_mode and not self.is_wallpaper_mode:
            # Exit fullscreen to windowed mode
            self.is_fullscreen = False
            self.showNormal()
            # Restore to last windowed size/position if available
            if hasattr(self, '_windowed_geometry'):
                self.setGeometry(self._windowed_geometry)
            else:
                # Default windowed size
                screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
                geo = screen.availableGeometry()
                w, h = 800, 600
                self.setGeometry((geo.width() - w) // 2, (geo.height() - h) // 2, w, h)
        else:
            # Save windowed geometry before going fullscreen
            if not self.is_fullscreen:
                self._windowed_geometry = self.geometry()
            # Enter fullscreen on current monitor
            self.is_fullscreen = True
            self.multi_monitor_mode = False
            self.is_wallpaper_mode = False
            self.showFullScreen()
        
        # Trigger playlist panel relayout after fullscreen toggle
        if hasattr(self, 'playlist_panel') and self.playlist_panel:
            QTimer.singleShot(50, self.playlist_panel.relayout)

        self._update_window_controls_visibility()
        
        QTimer.singleShot(0, self._restore_overlay_visibility)
    
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
        
        self.notification_widget.hide()
        
        if self.is_fullscreen and not self.multi_monitor_mode:
            # Move fullscreen to new monitor
            self.showNormal()
            if self.windowHandle():
                self.windowHandle().setScreen(new_screen)
            self.setGeometry(new_screen.geometry())
            self.showFullScreen()
        else:
            # Move window to new monitor center
            geo = new_screen.availableGeometry()
            w, h = self.width(), self.height()
            x = geo.x() + (geo.width() - w) // 2
            y = geo.y() + (geo.height() - h) // 2
            self.setGeometry(x, y, w, h)
        
        QTimer.singleShot(100, lambda: (
            self.update_layout(),
            self._update_text_properties(),
            self.playlist_panel.relayout() if hasattr(self, 'playlist_panel') and self.playlist_panel else None,
            self._restore_overlay_visibility()
        ))
    
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
        
        # Trigger playlist panel relayout after multi-monitor toggle
        if hasattr(self, 'playlist_panel') and self.playlist_panel:
            QTimer.singleShot(50, self.playlist_panel.relayout)

        self._update_window_controls_visibility()
        
        QTimer.singleShot(0, self._restore_overlay_visibility)
            
    def shift_multi_monitor_content(self, direction):
        # Allow shifting if in multi-monitor OR in wallpaper that came from multi-monitor
        is_in_valid_state = self.multi_monitor_mode or (self.is_wallpaper_mode and hasattr(self, '_was_multi_monitor') and self._was_multi_monitor)
        if not is_in_valid_state:
            return

        self._remember_overlay_visibility()

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
            
            # Trigger playlist panel relayout after shifting monitors
            if hasattr(self, 'playlist_panel') and self.playlist_panel:
                QTimer.singleShot(50, self.playlist_panel.relayout)
            
            QTimer.singleShot(0, self._restore_overlay_visibility)

    def shift_single_monitor_fullscreen(self, direction):
        screens = QApplication.screens()
        if len(screens) < 2: return
        screens.sort(key=lambda s: (s.geometry().x(), s.geometry().y()))

        self._remember_overlay_visibility()
        
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
            self.playlist_panel.relayout() if hasattr(self, 'playlist_panel') and self.playlist_panel else None,
            self.title and self.artist and self._trigger_notification(self.title.text(), self.artist.text(), self._current_pil_img, self._cur_text_color),
            self._restore_overlay_visibility()
        ))

    def toggle_wallpaper_mode(self):
        self._remember_overlay_visibility()
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
        
        # Trigger playlist panel relayout after wallpaper mode toggle
        if hasattr(self, 'playlist_panel') and self.playlist_panel:
            QTimer.singleShot(50, self.playlist_panel.relayout)

        self._update_window_controls_visibility()
        
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
            # Toggle overlay visibility with right-click
            if self.overlay.isHidden():
                # Show overlay
                self.overlay.update_size()
                # Position overlay at bottom-center of window in windowed mode,
                # otherwise position it at the monitor bottom
                if not (self.is_fullscreen or self.multi_monitor_mode or self.is_wallpaper_mode):
                    self._position_overlay_at_window_bottom()
                else:
                    self._position_overlay_at_monitor_bottom()
                self.overlay.fade_in()
                event.accept()
            else:
                # Hide overlay
                self.overlay.fade_out()
                event.accept()
        elif event.button() == Qt.LeftButton:
            if not (self.is_fullscreen or self.multi_monitor_mode or self.is_wallpaper_mode):
                # Check if click is on a corner (for resizing)
                corner = self._get_corner_at_position(event.pos())
                if corner:
                    self.resize_corner = corner
                    self.resize_start_rect = self.geometry()
                    self.resize_start_pos = event.globalPos()
                    event.accept()
                else:
                    # Regular window drag from anywhere in the window
                    self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
                    event.accept()
            else:
                event.accept()
        else:
            # Pass other clicks to the parent
            super().mousePressEvent(event)
    
    def _reposition_overlay_if_visible(self, force_show=False):
        """Reposition the overlay if it's visible; optionally force-show it."""
        if not self.overlay:
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

    def _remember_overlay_visibility(self):
        """Remember whether the overlay was visible before a mode change."""
        self._overlay_was_visible = bool(self.overlay and not self.overlay.isHidden())

    def _restore_overlay_visibility(self):
        """Restore overlay visibility after a mode change if it was visible."""
        if getattr(self, "_overlay_was_visible", False):
            self._reposition_overlay_if_visible(force_show=True)

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
                if not (self.is_fullscreen or self.multi_monitor_mode or self.is_wallpaper_mode):
                    self.move(event.globalPos() - self.drag_pos)
                event.accept()
            else:
                super().mouseMoveEvent(event)
        else:
            # Update cursor when hovering over corners
            if not (self.is_fullscreen or self.multi_monitor_mode or self.is_wallpaper_mode):
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
        self._remember_overlay_visibility()
        if self.is_wallpaper_mode:
            return
        if self.multi_monitor_mode:
            self.multi_monitor_mode = False
            self.is_fullscreen = True
            self.setWindowFlags(Qt.FramelessWindowHint)
            if self.target_monitor_geo:
                self.setGeometry(self.target_monitor_geo)
            self.show()
            self.update_layout()
            self._update_window_controls_visibility()
            QTimer.singleShot(0, self._restore_overlay_visibility)
        elif self.is_fullscreen:
            self.is_fullscreen = False
            # Windowed mode: use frameless to remove decorations, but keep our custom drag/resize
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowSystemMenuHint)
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
            self.update_layout()
            self._update_window_controls_visibility()
            QTimer.singleShot(0, self._restore_overlay_visibility)
        else:
            self.is_fullscreen = True
            # Get the screen and set geometry to fill it completely
            screen = QApplication.screenAt(self.geometry().center())
            if not screen:
                screens = QApplication.screens()
                if screens:
                    screen = screens[0]
            if screen:
                # Set window flags first, then geometry, then show fullscreen
                self.setWindowFlags(Qt.FramelessWindowHint)
                self.setGeometry(screen.geometry())
            self.showFullScreen()
            self.update_layout()
            self._update_window_controls_visibility()
            QTimer.singleShot(0, self._restore_overlay_visibility)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape: self.close()
        elif event.key() == Qt.Key_F:
            self._handle_fullscreen_hotkey()
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
            # Trigger playlist panel relayout after arrow key navigation
            if hasattr(self, 'playlist_panel') and self.playlist_panel:
                QTimer.singleShot(100, self.playlist_panel.relayout)
        elif event.key() == Qt.Key_Right:
            if self.multi_monitor_mode or (self.is_wallpaper_mode and hasattr(self, '_was_multi_monitor') and self._was_multi_monitor):
                self.shift_multi_monitor_content(1)
            elif self.is_fullscreen:
                self.shift_single_monitor_fullscreen(1)
            # Trigger playlist panel relayout after arrow key navigation
            if hasattr(self, 'playlist_panel') and self.playlist_panel:
                QTimer.singleShot(100, self.playlist_panel.relayout)
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
        self._position_window_controls()
        self._update_window_controls_visibility()

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