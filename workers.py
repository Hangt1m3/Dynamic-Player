# workers.py
import io
import asyncio
import traceback
import requests
import base64
import hashlib 
import json
import re
import urllib.parse
from PIL import Image
from PyQt5.QtCore import QObject, pyqtSignal, QRunnable, pyqtSlot, QDateTime, Qt, QDir
from PyQt5.QtGui import QFontDatabase
from PyQt5.QtWidgets import QApplication
from utils import extract_palette_from_image, get_contrast_ratio, get_best_text_color, get_best_border_color
from config import GITHUB_OWNER, GITHUB_REPO, GITHUB_TOKEN
import sounddevice as sd
import numpy as np
import io
import wave
import asyncio
import ctypes
import os
import tempfile
import time
import subprocess
from ShazamAPI import Shazam
from PyQt5.QtCore import QRunnable, pyqtSignal, QObject, pyqtSlot

class ListenModeWorker(QRunnable):
    class Signals(QObject):
        track_changed = pyqtSignal(dict)
        status = pyqtSignal(str)
        error = pyqtSignal(str)

    def __init__(self, mic_index=None):
        super().__init__()
        self.signals = self.Signals()
        self.is_running = True
        
        # Memory variables for stabilizing physical media detection
        self.current_track_id = None
        self.pending_track_id = None
        self.pending_match_count = 0

    @pyqtSlot()
    def run(self):
        winmm = ctypes.windll.winmm
        temp_dir = tempfile.gettempdir()
        
        # We now use two files: the raw recording, and the clean 16kHz version
        wav_raw = os.path.join(temp_dir, "dynamic_player_raw.wav")
        wav_ready = os.path.join(temp_dir, "dynamic_player_ready.wav")
        
        while self.is_running:
            try:
                self.signals.status.emit("Listening to mic...")
                
                # 1. Record raw audio natively
                winmm.mciSendStringW("open new type waveaudio alias recsound", None, 0, None)
                winmm.mciSendStringW("record recsound", None, 0, None)
                
                # Listen for 7 seconds (better accuracy for Shazam)
                for _ in range(70):
                    if not self.is_running:
                        break
                    time.sleep(0.1)
                
                # 2. Stop and Save raw file
                winmm.mciSendStringW("stop recsound", None, 0, None)
                if os.path.exists(wav_raw):
                    try: os.remove(wav_raw)
                    except: pass
                    
                winmm.mciSendStringW(f'save recsound "{wav_raw}"', None, 0, None)
                winmm.mciSendStringW("close recsound", None, 0, None)
                
                if not self.is_running:
                    break
                    
                self.signals.status.emit("Analyzing...")
                
                # 3. Use FFmpeg to perfectly format the audio (16kHz, Mono) so pydub doesn't crash
                if os.path.exists(wav_raw):
                    subprocess.run([
                        'ffmpeg', '-y', 
                        '-i', wav_raw, 
                        '-ac', '1',          # Convert to Mono
                        '-ar', '16000',      # Convert to 16000Hz
                        wav_ready
                    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                    
                    # 4. Send the cleaned file to Shazam
                    if os.path.exists(wav_ready):
                        with open(wav_ready, 'rb') as f:
                            audio_bytes = f.read()
                            
                        shazam = Shazam(audio_bytes)
                        recognize_generator = shazam.recognizeSong()
                        
                        try:
                            offset, out = next(recognize_generator)
                        except StopIteration:
                            out = {}
                            
                        if out and 'track' in out:
                            track = out['track']
                            title = track.get('title', 'Unknown Title')
                            
                            # 1. Filter out Shazam's known silence artifact
                            if title.lower() == "andy session 1":
                                self.signals.status.emit("Ignoring silence artifact...")
                                continue
                                
                            # 2. Generate STRICT 22-character Base62-compliant IDs for Spotify's API
                            import hashlib
                            raw_key = str(track.get('key', '000000'))
                            
                            # hex returns 0-9 and a-f, which perfectly satisfies Base62 requirements
                            track_id = hashlib.md5(raw_key.encode()).hexdigest()[:22]
                            album_id = hashlib.md5((raw_key + "album").encode()).hexdigest()[:22]
                            artist_id = hashlib.md5((raw_key + "artist").encode()).hexdigest()[:22]
                            
                            artist = track.get('subtitle', 'Unknown Artist')
                            
                            album_name = "Unknown Album"
                            images = []
                            
                            if 'sections' in track:
                                for sec in track['sections']:
                                    if sec.get('type') == 'SONG':
                                        for meta in sec.get('metadata', []):
                                            if meta.get('title') == 'Album':
                                                album_name = meta.get('text', album_name)
                            
                            if 'images' in track:
                                img = track['images'].get('coverart') or track['images'].get('background')
                                if img:
                                    images.append({'url': img})
                            
                            result = {
                                "id": track_id,
                                "item": {
                                    "name": title,
                                    "artists": [{"name": artist, "id": artist_id}], # <-- Added artist_id
                                    "album": {
                                        "name": album_name,
                                        "images": images,
                                        "id": album_id # <-- Removed the "album_" prefix
                                    },
                                    "id": track_id,
                                    "duration_ms": 180000
                                },
                                "is_playing": True,
                                "progress_ms": 0,
                                "source": "microphone"
                            }
                            
                            # --- STABILITY LOGIC ---
                            # 1. If this is the very first song detected after turning on Listen Mode
                            if self.current_track_id is None:
                                self.current_track_id = track_id
                                self.signals.track_changed.emit(result)
                                self.signals.status.emit(f"Locked onto initial track: {title}")
                                
                            # 2. If it matches what is currently playing, we are stable.
                            elif track_id == self.current_track_id:
                                self.pending_track_id = None
                                self.pending_match_count = 0
                                self.signals.status.emit(f"Still tracking: {title} (Stable)")
                                
                            # 3. It's a different track! But we need to verify it to prevent glitches.
                            else:
                                if track_id == self.pending_track_id:
                                    # We saw this new track twice in a row! It's legit.
                                    self.pending_match_count += 1
                                    if self.pending_match_count >= 1:
                                        self.current_track_id = track_id
                                        self.signals.track_changed.emit(result)
                                        self.signals.status.emit(f"Confirmed track change: {title}")
                                        
                                        # Reset pending memory
                                        self.pending_track_id = None
                                        self.pending_match_count = 0
                                else:
                                    # First time seeing this new track. Don't change UI yet.
                                    self.pending_track_id = track_id
                                    self.pending_match_count = 0
                                    self.signals.status.emit(f"Possible track change detected: {title}... waiting to verify.")
                            # ------------------------
                            
                        else:
                            self.signals.status.emit("No match found (Keeping current track on screen)")
                
                # Pause before listening again
                for _ in range(30):
                    if not self.is_running: break
                    time.sleep(0.1)
                    
            except Exception as e:
                self.signals.error.emit(str(e))
                winmm.mciSendStringW("close recsound", None, 0, None)
                time.sleep(2)

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
            track_custom_art_b64 = track_cache.get("custom_art_b64")
            album_custom_art_b64 = album_cache.get("custom_art_b64")
            custom_art_b64 = track_custom_art_b64 or album_custom_art_b64
            
            low_res_pil_img = self.preloaded_image
            if not low_res_pil_img and custom_art_b64:
                try:
                    low_res_pil_img = Image.open(io.BytesIO(base64.b64decode(custom_art_b64))).convert("RGB")
                except Exception:
                    low_res_pil_img = None
            if not low_res_pil_img and self.images_data:
                try: 
                    resp = requests.get(self.images_data[-1]["url"], timeout=10); resp.raise_for_status()
                    low_res_pil_img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                except: low_res_pil_img = Image.new("RGB", (640, 640), "black")
            
            if not low_res_pil_img: low_res_pil_img = Image.new("RGB", (640, 640), "black")

            # Keep visual colors album-scoped so same-album track changes do not recolor the UI.
            color_keys = {
                "ui_palette",
                "blob_palette",
                "lights_config",
                "text_color",
                "text_border_color",
                "title_gradient_enabled",
                "title_gradient_color",
                "title_gradient_direction",
            }
            album_color_data = {
                key: value for key, value in (album_cache.items() if isinstance(album_cache, dict) else []) if key in color_keys
            }

            # Non-color presentation settings may still be overridden per-track.
            settings_data = album_cache.copy() if isinstance(album_cache, dict) else {}
            if isinstance(track_cache, dict):
                for key, value in track_cache.items():
                    if key not in color_keys:
                        settings_data[key] = value

            ui_palette = None
            lights_palette = None
            blob_palette = None
            text_color = None
            shadow_enabled = True
            lights_config = album_color_data.get("lights_config") if isinstance(album_color_data, dict) else None

            if album_color_data:
                ui_palette = album_color_data.get("ui_palette")
                text_color = album_color_data.get("text_color")
                blob_palette = album_color_data.get("blob_palette")
                if lights_config and lights_config.get("mode") == "custom":
                    lights_palette = lights_config.get("palette")
            
            extracted_text_color = None; border_needed = False
            if not ui_palette:
                ui_palette, lights_palette, blob_palette, extracted_text_color, border_needed = extract_palette_from_image(low_res_pil_img, 3)
            elif not lights_palette:
                _, lights_palette, blob_palette, extracted_text_color, border_needed = extract_palette_from_image(low_res_pil_img, 3)

            text_border_enabled = settings_data.get("text_border_enabled") if settings_data else None
            if text_border_enabled is None:
                text_border_enabled = True if self.defaults.get("text_border_enabled") else border_needed

            if not text_color:
                text_color = extracted_text_color if extracted_text_color and not album_color_data.get("ui_palette") else list(get_best_text_color(ui_palette[0]))

            text_border_color = album_color_data.get("text_border_color")
            if not text_border_color:
                candidates = []
                if len(ui_palette) > 1: candidates.append(ui_palette[1])
                if blob_palette: candidates.extend(blob_palette)
                text_border_color = list(get_best_border_color(ui_palette[0], text_color, candidates))

            self.signals.result.emit({
                "pil_img": low_res_pil_img, "ui_palette": ui_palette, "original_lights_palette": lights_palette, "blob_palette": blob_palette,
                "text_color": text_color,
                "lights_config": lights_config if isinstance(lights_config, dict) else {},
                "shadow_enabled": settings_data.get("shadow_enabled", shadow_enabled),
                "font_family": settings_data.get("font_family", self.defaults.get("font_family")),
                "font_style": settings_data.get("font_style", self.defaults.get("font_style")),
                "font_size_scale": settings_data.get("font_size_scale", self.defaults.get("font_size_scale")),
                "title_case": settings_data.get("title_case", "default"), "artist_case": settings_data.get("artist_case", "default"),
                "album_art_border_enabled": settings_data.get("album_art_border_enabled", True),
                "title_gradient_enabled": settings_data.get("title_gradient_enabled", False),
                "title_gradient_color": album_color_data.get("title_gradient_color") or settings_data.get("title_gradient_color", [255, 255, 255]),
                "title_gradient_direction": settings_data.get("title_gradient_direction", "Left to Right"),
                "text_border_enabled": text_border_enabled, "text_border_color": text_border_color,
                "text_border_size": settings_data.get("text_border_size"), "token": self.token
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
    class Signals(QObject):
        result = pyqtSignal(object)
        error = pyqtSignal(str)

    def __init__(self, owner, repo, token=None, current_version="0.0.0"):
        super(GitHubUpdatesWorker, self).__init__()
        self.owner = owner
        self.repo = repo
        self.token = token
        self.current_version = current_version
        self.signals = self.Signals()

    def run(self):
        try:
            import requests
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            
            # 1. Attempt to fetch the latest release
            url = f"https://api.github.com/repos/{self.owner}/{self.repo}/releases/latest"
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                result = {
                    "latest_version": data.get("tag_name", "Unknown"),
                    "current_version": self.current_version,
                    "body": data.get("body") or "No release notes provided.",
                    "date": data.get("published_at", "")[:10],
                    "author": data.get("author", {}).get("login", "Unknown"),
                    "type": "release"
                }
                self.signals.result.emit(result)
            else:
                # 2. Fallback: Fetch commits
                commits_url = f"https://api.github.com/repos/{self.owner}/{self.repo}/commits?per_page=5"
                c_response = requests.get(commits_url, headers=headers, timeout=10)
                
                if c_response.status_code == 200:
                    commits = c_response.json()
                    formatted_commits = []
                    latest_sha = "Unknown"
                    
                    if commits and isinstance(commits, list) and len(commits) > 0:
                        # Use the short SHA of the newest commit as the "version"
                        latest_sha = commits[0].get("sha", "Unknown")[:7]
                        
                        for c in commits:
                            formatted_commits.append({
                                "title": c.get("commit", {}).get("message", "").split('\n')[0],
                                "desc": c.get("commit", {}).get("message", ""),
                                "date": c.get("commit", {}).get("author", {}).get("date", "")[:10],
                                "author": c.get("commit", {}).get("author", {}).get("name", "Unknown")
                            })

                    # Construct a result dict so the UI still gets version info
                    result = {
                        "latest_version": latest_sha, 
                        "current_version": self.current_version,
                        "commits": formatted_commits,
                        "type": "commits"
                    }
                    self.signals.result.emit(result)
                else:
                    self.signals.error.emit(f"No releases or commits found (Status: {response.status_code})")
                    
        except Exception as e:
            self.signals.error.emit(str(e))

class LyricsWorker(QRunnable):
    """Fetches time-synced lyrics from lrclib.net and parses them into (ms, text) pairs."""
    class Signals(QObject):
        lyrics_ready = pyqtSignal(str, list)  # track_id, [(ms, text), ...]
        no_lyrics = pyqtSignal(str)           # track_id

    def __init__(self, track_id, track_name, artist_name, album_name, duration_ms):
        super().__init__()
        self.signals = self.Signals()
        self.track_id = track_id
        self.track_name = track_name
        self.artist_name = artist_name
        self.album_name = album_name
        self.duration_ms = duration_ms

    @pyqtSlot()
    def run(self):
        try:
            params = urllib.parse.urlencode({
                "artist_name": self.artist_name,
                "track_name": self.track_name,
                "album_name": self.album_name,
                "duration": int(self.duration_ms / 1000),
            })
            url = f"https://lrclib.net/api/get?{params}"
            response = requests.get(url, timeout=5, headers={"User-Agent": "DynamicPlayer/1.0"})

            if response.status_code != 200:
                self.signals.no_lyrics.emit(self.track_id)
                return

            payload = response.json()
            raw_lrc = payload.get("syncedLyrics")
            if not raw_lrc:
                self.signals.no_lyrics.emit(self.track_id)
                return

            lines = self._parse_lrc(raw_lrc)
            if not lines:
                self.signals.no_lyrics.emit(self.track_id)
                return

            self.signals.lyrics_ready.emit(self.track_id, lines)
        except Exception:
            self.signals.no_lyrics.emit(self.track_id)

    def _parse_lrc(self, raw):
        """Parse LRC format into sorted list of [ms, text] pairs.
        Empty-text entries are kept as break markers (text == "").
        """
        pattern = re.compile(r'\[(\d+):(\d+(?:\.\d+)?)\](.*)')
        results = []
        for line in raw.splitlines():
            m = pattern.match(line.strip())
            if not m:
                continue
            minutes = int(m.group(1))
            seconds = float(m.group(2))
            text = m.group(3).strip()
            ms = int((minutes * 60 + seconds) * 1000)
            results.append([ms, text])
        results.sort(key=lambda x: x[0])
        return results


class SpotifyPollingWorker(QRunnable):
    class Signals(QObject): track_changed = pyqtSignal(dict); playback_state_changed = pyqtSignal(dict); no_playback = pyqtSignal()
    def __init__(self, sp_client): super().__init__(); self.signals = self.Signals(); self.sp = sp_client; self.is_running = True; self.current_track_id = None
    def _sleep(self, duration_ms):
        for _ in range(duration_ms // 100):
            if not self.is_running: return False
            QApplication.instance().thread().msleep(100)
        return True
    def stop(self): self.is_running = False
    def run(self):
        while self.is_running:
            try:
                if not self.sp:
                    # Spotify not configured, wait and continue
                    if not self._sleep(5000): return
                    continue
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
                
                # Filter out Spotify and Apple Music - they have dedicated workers
                if not session: 
                    return None
                
                app_id = session.source_app_user_model_id.lower()
                if "spotify" in app_id or "apple" in app_id or "itunes" in app_id: 
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
        blocked_families = {
            "Fixedsys",
            "MS Sans Serif",
            "MS Serif",
            "Small Fonts",
            "System",
        }
        db = QFontDatabase(); custom_fonts = set()
        for filename in QDir(":/fonts/").entryList(["*.ttf", "*.otf"], QDir.Files):
            fid = QFontDatabase.addApplicationFont(f":/fonts/{filename}")
            if fid != -1: custom_fonts.update(QFontDatabase.applicationFontFamilies(fid))
        all_families = sorted(list(set(db.families()) | custom_fonts))
        font_styles_cache = {}; base_families = []
        for family in all_families:
            if family in blocked_families or family.startswith("@"):
                continue
            if QFontDatabase.WritingSystem.Latin in db.writingSystems(family):
                styles = sorted(db.styles(family))
                if styles:
                    font_styles_cache[family] = styles
                    base_families.append(family)
        self.signals.result.emit({"font_styles_cache": font_styles_cache, "base_font_families": base_families})


# Apple Music Worker - Combines system media controls with Apple Music API enrichment
if IS_WINDOWS:
    class AppleMusicPollingWorker(QRunnable):
        """
        Polls for Apple Music playback using Windows Media Controls.
        Enriches metadata with Apple Music API if configured.
        """
        class Signals(QObject): 
            track_changed = pyqtSignal(dict)
            no_playback = pyqtSignal()
        
        def __init__(self, apple_music_client=None):
            super().__init__()
            self.signals = self.Signals()
            self.is_running = True
            self.current_media_id = None
            self.apple_music_client = apple_music_client
        
        def _generate_id(self, text):
            """Generate consistent MD5 hash ID from text."""
            if not text: return "unknown_id"
            return hashlib.md5(text.encode('utf-8')).hexdigest()
        
        async def _get_media_info(self):
            """Get currently playing media from Apple Music via system controls."""
            try:
                manager = await MediaManager.request_async()
                if not manager: return None
                session = manager.get_current_session()
                
                if not session: 
                    return None
                
                # Only handle Apple Music
                app_id = session.source_app_user_model_id.lower()
                if "apple" not in app_id and "itunes" not in app_id:
                    return None
                
                info = await session.try_get_media_properties_async()
                if info and info.title:
                    title = info.title
                    artist = info.artist or "Unknown Artist"
                    album_title = info.album_title or "Unknown Album"
                    
                    # Generate synthetic IDs
                    track_id = self._generate_id(f"{title}{artist}")
                    album_id = self._generate_id(f"{album_title}{artist}")
                    
                    # Fetch thumbnail
                    thumbnail_data = None
                    if info.thumbnail:
                        try:
                            stream = await info.thumbnail.open_read_async()
                            if stream and stream.size > 0:
                                thumbnail_data = bytearray(stream.size)
                                data_reader = DataReader(stream)
                                await data_reader.load_async(stream.size)
                                data_reader.read_bytes(thumbnail_data)
                        except Exception:
                            thumbnail_data = None
                    
                    # Try to enrich with Apple Music API if available
                    album_images = []
                    if self.apple_music_client and self.apple_music_client.developer_token:
                        try:
                            # Search for the track to get proper album art and metadata
                            search_results = self.apple_music_client.search(
                                f"{title} {artist}",
                                types="songs",
                                limit=1
                            )
                            
                            if search_results and "results" in search_results:
                                songs = search_results.get("results", {}).get("songs", {}).get("data", [])
                                if songs:
                                    song = songs[0]
                                    # Extract high-quality album artwork
                                    artwork = song.get("attributes", {}).get("artwork", {})
                                    if artwork and artwork.get("url"):
                                        # Apple Music uses template URLs
                                        base_url = artwork["url"]
                                        # Replace template variables with desired dimensions
                                        art_url = base_url.replace("{w}", "640").replace("{h}", "640")
                                        album_images = [
                                            {"url": art_url, "width": 640, "height": 640}
                                        ]
                                        
                                        # Update IDs to use Apple Music IDs if available
                                        track_id = song.get("id", track_id)
                                        album_data = song.get("attributes", {}).get("albumName")
                                        if album_data:
                                            album_id = song.get("relationships", {}).get("albums", {}).get("data", [{}])[0].get("id", album_id)
                        except Exception as e:
                            print(f"Apple Music API enrichment failed: {e}")
                    
                    # Construct track data
                    return {
                        "id": track_id,
                        "item": {
                            "name": title,
                            "artists": [{"name": artist}],
                            "album": {
                                "name": album_title,
                                "images": album_images,
                                "id": album_id
                            },
                            "id": track_id,
                            "duration_ms": 0
                        },
                        "is_playing": True,
                        "progress_ms": 0,
                        "thumbnail_data": thumbnail_data if not album_images else None,
                        "source": "apple_music"
                    }
            except Exception as e:
                print(f"Apple Music media info error: {e}")
            return None
        
        async def _main_loop(self):
            """Main polling loop."""
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
        def run(self):
            asyncio.run(self._main_loop())
        
        def stop(self):
            self.is_running = False
else:
    # Create placeholder class for non-Windows systems
    class AppleMusicPollingWorker:
        """Placeholder for non-Windows systems."""
        def __init__(self, *args, **kwargs):
            pass