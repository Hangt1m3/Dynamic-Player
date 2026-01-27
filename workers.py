# workers.py
import io
import asyncio
import traceback
import requests
import base64
import hashlib 
import json
from PIL import Image
from PyQt5.QtCore import QObject, pyqtSignal, QRunnable, pyqtSlot, QDateTime, Qt, QDir
from PyQt5.QtGui import QFontDatabase
from PyQt5.QtWidgets import QApplication
from utils import extract_palette_from_image, get_contrast_ratio, get_best_text_color, get_best_border_color
from config import GITHUB_OWNER, GITHUB_REPO, GITHUB_TOKEN

try:
    from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as MediaManager
    from winsdk.windows.storage.streams import DataReader
    IS_WINDOWS = True
except ImportError:
    IS_WINDOWS = False

class WorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(tuple)
    art_loaded = pyqtSignal(dict)
    result = pyqtSignal(dict)

class GoveeWorker(QRunnable):
    class Signals(QObject): error = pyqtSignal(str)
    def __init__(self, controller, palette, enabled, brightness=1.0):
        super().__init__(); self.signals = self.Signals(); self.controller = controller; self.palette = palette; self.enabled = enabled; self.brightness = brightness
    @pyqtSlot()
    def run(self):
        errors = self.controller.send_colors(self.palette, self.enabled, self.brightness)
        if errors: self.signals.error.emit("\n".join(list(set(errors))))

class GoveeDeviceFinderWorker(QRunnable):
    class Signals(QObject): result = pyqtSignal(list); error = pyqtSignal(str); finished = pyqtSignal()
    def __init__(self, api_key): super().__init__(); self.signals = self.Signals(); self.api_key = api_key
    @pyqtSlot()
    def run(self):
        headers = {"Govee-API-Key": self.api_key, "Content-Type": "application/json"}
        try:
            response = requests.get("https://developer-api.govee.com/v1/devices", headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            if response.status_code == 200 and data.get("data"): self.signals.result.emit(data["data"].get("devices", []))
            else: self.signals.error.emit(f"Unexpected response: {json.dumps(data)}")
        except Exception as err: self.signals.error.emit(str(err))
        finally: self.signals.finished.emit()

class TrackLoaderWorker(QRunnable):
    def __init__(self, images_data, token, album_id, track_id, color_cache, preloaded_image=None, defaults=None):
        super().__init__(); self.signals = WorkerSignals()
        self.images_data = images_data; self.token = token; self.album_id = album_id; self.track_id = track_id; self.color_cache = color_cache; self.preloaded_image = preloaded_image; self.defaults = defaults or {}
    @pyqtSlot()
    def run(self):
        try:
            track_cache = self.color_cache.get_album_data(self.track_id) or {}
            album_cache = self.color_cache.get_album_data(self.album_id) or {}
            custom_art_b64 = track_cache.get("custom_art_b64")
            
            low_res_pil_img = self.preloaded_image
            if not low_res_pil_img and custom_art_b64:
                low_res_pil_img = Image.open(io.BytesIO(base64.b64decode(custom_art_b64))).convert("RGB")
            if not low_res_pil_img and self.images_data:
                try: 
                    resp = requests.get(self.images_data[-1]["url"], timeout=10); resp.raise_for_status()
                    low_res_pil_img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                except: low_res_pil_img = Image.new("RGB", (640, 640), "black")
            
            if not low_res_pil_img: low_res_pil_img = Image.new("RGB", (640, 640), "black")

            # Logic extraction (simplified for brevity, keeps original logic)
            ui_palette = None; lights_palette = None; blob_palette = None; text_color = None; shadow_enabled = True
            cached_data = album_cache.copy()
            if track_cache: cached_data.update(track_cache)
            
            if cached_data:
                if isinstance(cached_data, dict):
                    ui_palette = cached_data.get("ui_palette"); text_color = cached_data.get("text_color")
                    blob_palette = cached_data.get("blob_palette"); lights_config = cached_data.get("lights_config")
                    if lights_config and lights_config.get("mode") == "custom": lights_palette = lights_config.get("palette")
            
            extracted_text_color = None; border_needed = False
            if not ui_palette:
                ui_palette, lights_palette, blob_palette, extracted_text_color, border_needed = extract_palette_from_image(low_res_pil_img, 3)
            elif not lights_palette:
                _, lights_palette, blob_palette, extracted_text_color, border_needed = extract_palette_from_image(low_res_pil_img, 3)

            text_border_enabled = cached_data.get("text_border_enabled") if cached_data else None
            if text_border_enabled is None:
                text_border_enabled = True if self.defaults.get("text_border_enabled") else border_needed

            if not text_color:
                text_color = extracted_text_color if extracted_text_color and not cached_data.get("ui_palette") else list(get_best_text_color(cached_data.get("player_bg_color") or ui_palette[0]))

            text_border_color = cached_data.get("text_border_color")
            if not text_border_color:
                candidates = []
                if len(ui_palette) > 1: candidates.append(ui_palette[1])
                if blob_palette: candidates.extend(blob_palette)
                text_border_color = list(get_best_border_color(cached_data.get("player_bg_color") or ui_palette[0], text_color, candidates))

            self.signals.result.emit({
                "pil_img": low_res_pil_img, "ui_palette": ui_palette, "original_lights_palette": lights_palette, "blob_palette": blob_palette,
                "text_color": text_color, "shadow_enabled": cached_data.get("shadow_enabled", shadow_enabled),
                "font_family": cached_data.get("font_family", self.defaults.get("font_family")),
                "font_style": cached_data.get("font_style", self.defaults.get("font_style")),
                "font_size_scale": cached_data.get("font_size_scale", self.defaults.get("font_size_scale")),
                "title_case": cached_data.get("title_case", "default"), "artist_case": cached_data.get("artist_case", "default"),
                "text_border_enabled": text_border_enabled, "text_border_color": text_border_color,
                "text_border_size": cached_data.get("text_border_size"), "token": self.token
            })

            high_res_pil_img = low_res_pil_img
            if self.images_data and not (self.preloaded_image or custom_art_b64):
                try:
                    resp = requests.get(self.images_data[0]["url"], timeout=10); resp.raise_for_status()
                    high_res_pil_img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                except: pass
            self.signals.art_loaded.emit({"pil_img": high_res_pil_img, "token": self.token})

        except Exception as e: self.signals.error.emit((type(e), e, traceback.format_exc()))
        finally: self.signals.finished.emit()

class GitHubUpdatesWorker(QRunnable):
    class Signals(QObject): result = pyqtSignal(dict); error = pyqtSignal(str) 
    def __init__(self, owner, repo, token=None, current_version="0.0.0"): 
        super().__init__()
        self.owner = owner
        self.repo = repo
        self.token = token
        self.current_version = current_version
        self.signals = self.Signals()

    @pyqtSlot()
    def run(self):
        # Fetch the LATEST RELEASE instead of just commits
        url = f"https://api.github.com/repos/{self.owner}/{self.repo}/releases/latest"
        headers = {}
        if self.token: headers["Authorization"] = f"Bearer {self.token}"
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            
            # Handle case where no releases exist yet
            if response.status_code == 404:
                self.signals.result.emit({
                    "update_available": False,
                    "latest_version": self.current_version,
                    "body": "No official releases found.",
                    "url": ""
                })
                return

            response.raise_for_status()
            release_data = response.json()
            
            # Strip 'v' if present (e.g. v1.0.0 -> 1.0.0)
            latest_tag = release_data.get("tag_name", "0.0.0").lstrip("v")
            html_url = release_data.get("html_url", "")
            body = release_data.get("body", "")

            # Simple string comparison (for now). 
            # If they differ, we assume it's an update.
            update_available = latest_tag != self.current_version

            self.signals.result.emit({
                "update_available": update_available,
                "latest_version": latest_tag,
                "current_version": self.current_version,
                "body": body,
                "url": html_url
            })

        except Exception as e: 
            self.signals.error.emit(f"Could not check for updates: {str(e)}")

class SpotifyPollingWorker(QRunnable):
    class Signals(QObject): track_changed = pyqtSignal(dict); playback_state_changed = pyqtSignal(dict); no_playback = pyqtSignal()
    def __init__(self, sp_client): super().__init__(); self.signals = self.Signals(); self.sp = sp_client; self.is_running = True; self.current_track_id = None
    def _sleep(self, duration_ms):
        for _ in range(duration_ms // 100):
            if not self.is_running: return False
            QApplication.instance().thread().msleep(100)
        return True
    def run(self):
        while self.is_running:
            try:
                data = self.sp.current_playback()
                if not data or not data.get("item"):
                    if self.current_track_id is not None: self.current_track_id = None; self.signals.no_playback.emit()
                    if not self._sleep(3000): return
                    continue
                item = data["item"]
                if item["id"] != self.current_track_id: self.current_track_id = item["id"]; self.signals.track_changed.emit(data)
                else: self.signals.playback_state_changed.emit(data)
                if not self._sleep(1000): return
            except Exception:
                if not self._sleep(5000): return

if IS_WINDOWS:
    class WindowsMediaWorker(QRunnable):
        class Signals(QObject): track_changed = pyqtSignal(dict); no_playback = pyqtSignal()
        def __init__(self): super().__init__(); self.signals = self.Signals(); self.is_running = True; self.current_media_id = None
        
        def _generate_id(self, text):
            """Generates a consistent MD5 hash ID from text to simulate a Spotify ID."""
            if not text: return "unknown_id"
            return hashlib.md5(text.encode('utf-8')).hexdigest()

        async def _get_media_info(self):
            try:
                manager = await MediaManager.request_async()
                if not manager: return None
                session = manager.get_current_session()
                
                # Filter out Spotify specifically to allow the main worker to handle it.
                # Allow Apple Music (often "AppleInc.AppleMusic...") and others.
                if not session: 
                    return None
                
                app_id = session.source_app_user_model_id.lower()
                if "spotify" in app_id: 
                    return None
                    
                info = await session.try_get_media_properties_async()
                if info and info.title:
                    # Extract Metadata
                    title = info.title
                    artist = info.artist or "Unknown Artist"
                    album_title = info.album_title or "Unknown Album"
                    
                    # --- GENERATE SYNTHETIC IDs ---
                    track_id = self._generate_id(f"{title}{artist}")
                    album_id = self._generate_id(f"{album_title}{artist}")
                    
                    # Fetch Thumbnail
                    thumbnail_data = None
                    # Try/Except block specifically for thumbnail reading, as this often fails 
                    # with Apple Music / iTunes streams on Windows.
                    if info.thumbnail:
                        try:
                            stream = await info.thumbnail.open_read_async()
                            if stream and stream.size > 0:
                                thumbnail_data = bytearray(stream.size)
                                data_reader = DataReader(stream)
                                await data_reader.load_async(stream.size)
                                data_reader.read_bytes(thumbnail_data)
                        except Exception:
                            # If thumbnail fails, we still want the track info
                            thumbnail_data = None
                    
                    # Construct an item dictionary
                    return {
                        "id": track_id, 
                        "item": {
                            "name": title, 
                            "artists": [{"name": artist}], 
                            "album": {
                                "name": album_title, 
                                "images": [],
                                "id": album_id 
                            }, 
                            "id": track_id, 
                            "duration_ms": 0 
                        }, 
                        "is_playing": True, 
                        "progress_ms": 0, 
                        "thumbnail_data": thumbnail_data
                    }
            except Exception: pass
            return None
            
        async def _main_loop(self):
            while self.is_running:
                info = await self._get_media_info()
                if info:
                    if info["id"] != self.current_media_id: 
                        self.current_media_id = info["id"]
                        self.signals.track_changed.emit(info)
                else:
                    if self.current_media_id is not None: 
                        self.current_media_id = None
                        self.signals.no_playback.emit()
                await asyncio.sleep(2)
                
        @pyqtSlot()
        def run(self): asyncio.run(self._main_loop())
        def stop(self): self.is_running = False

class FontLoaderWorker(QRunnable):
    class Signals(QObject): result = pyqtSignal(dict)
    def __init__(self): super().__init__(); self.signals = self.Signals()
    @pyqtSlot()
    def run(self):
        db = QFontDatabase(); custom_fonts = set()
        for filename in QDir(":/fonts/").entryList(["*.ttf", "*.otf"], QDir.Files):
            fid = QFontDatabase.addApplicationFont(f":/fonts/{filename}")
            if fid != -1: custom_fonts.update(QFontDatabase.applicationFontFamilies(fid))
        all_families = sorted(list(set(db.families()) | custom_fonts))
        font_styles_cache = {}; base_families = []
        for family in all_families:
            if QFontDatabase.WritingSystem.Latin in db.writingSystems(family):
                font_styles_cache[family] = sorted(db.styles(family)); base_families.append(family)
        self.signals.result.emit({"font_styles_cache": font_styles_cache, "base_font_families": base_families})