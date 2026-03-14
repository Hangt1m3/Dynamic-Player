# services.py
import os
import json
import threading
import time
import requests
from PyQt5.QtCore import QStandardPaths, QDir, QTimer
from utils import rgb_to_hsl, hsl_to_rgb, normalize_color
from PyQt5.QtMultimedia import QSoundEffect
from PyQt5.QtCore import QUrl, QObject, QEvent, pyqtSignal, QCoreApplication
from PyQt5.QtGui import QColor
import random

class ColorCache:
    """Handles loading, saving, and accessing cached album colors."""
    def __init__(self, filename='color_cache.json'):
        app_data_path = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        if not app_data_path: app_data_path = QDir.homePath()
        self.dir = QDir(app_data_path)
        if not self.dir.exists(): self.dir.mkpath('.')
        self.filepath = self.dir.filePath(filename)
        self.cache = self._load()

    def _load(self):
        if not os.path.exists(self.filepath): 
            return {}
        try:
            with open(self.filepath, 'r') as f:
                data = json.load(f)
                # Validation: Ensure the loaded data is actually a dictionary
                if isinstance(data, dict):
                    changed = False
                    normalized = {}
                    for key, value in data.items():
                        entry, entry_changed = self._normalize_cache_entry(value)
                        normalized[key] = entry
                        changed = changed or entry_changed
                    if changed:
                        self.cache = normalized
                        self.save()
                    return normalized
                return {}
        except (json.JSONDecodeError, IOError, ValueError):
            return {}

    def _normalize_color_triplet(self, value):
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            return None
        try:
            return [int(value[0]), int(value[1]), int(value[2])]
        except (TypeError, ValueError):
            return None

    def _normalize_palette(self, palette):
        if not isinstance(palette, list):
            return []
        normalized = []
        for color in palette:
            triplet = self._normalize_color_triplet(color)
            if triplet is not None:
                normalized.append(triplet)
        return normalized

    def _dedupe_palette(self, palette):
        deduped = []
        seen = set()
        for color in palette:
            key = tuple(color)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(color)
        return deduped

    def _fallback_accent_color(self, background, blob_palette):
        if len(blob_palette) > 1:
            return blob_palette[1]
        if blob_palette:
            source = blob_palette[0]
        else:
            source = background or [30, 30, 30]

        accent = QColor(*source)
        if accent.lightnessF() < 0.5:
            accent = accent.lighter(150)
        else:
            accent = accent.darker(150)
        return [accent.red(), accent.green(), accent.blue()]

    def _fallback_blob_palette(self, background, accent):
        source = QColor(*(accent or background or [30, 30, 30]))
        lighter = source.lighter(115)
        darker = source.darker(125)
        return self._dedupe_palette([
            [source.red(), source.green(), source.blue()],
            [lighter.red(), lighter.green(), lighter.blue()],
            [darker.red(), darker.green(), darker.blue()],
        ])

    def _normalize_cache_entry(self, entry):
        if not isinstance(entry, dict):
            return entry, False

        normalized = dict(entry)
        changed = False

        player_bg_color = self._normalize_color_triplet(normalized.get("player_bg_color"))
        if "player_bg_color" in normalized:
            if player_bg_color is None:
                normalized.pop("player_bg_color", None)
                changed = True
            elif player_bg_color != normalized.get("player_bg_color"):
                normalized["player_bg_color"] = player_bg_color
                changed = True

        blob_palette = self._normalize_palette(normalized.get("blob_palette"))
        deduped_blob_palette = self._dedupe_palette(blob_palette)
        if deduped_blob_palette != normalized.get("blob_palette"):
            normalized["blob_palette"] = deduped_blob_palette
            changed = True
        blob_palette = deduped_blob_palette

        ui_palette = self._normalize_palette(normalized.get("ui_palette"))
        if ui_palette and ui_palette != normalized.get("ui_palette"):
            normalized["ui_palette"] = ui_palette
            changed = True

        if not player_bg_color and ui_palette:
            player_bg_color = ui_palette[0]
            normalized["player_bg_color"] = player_bg_color
            changed = True

        if player_bg_color and blob_palette:
            filtered_blob_palette = [color for color in blob_palette if color != player_bg_color]
            if filtered_blob_palette and filtered_blob_palette != blob_palette:
                blob_palette = filtered_blob_palette
                normalized["blob_palette"] = filtered_blob_palette
                changed = True

        if not ui_palette and (player_bg_color or blob_palette):
            bg_color = player_bg_color or blob_palette[0]
            accent_color = self._fallback_accent_color(bg_color, blob_palette)
            ui_palette = [bg_color, accent_color]
            normalized["ui_palette"] = ui_palette
            changed = True

        if not player_bg_color and ui_palette:
            player_bg_color = ui_palette[0]
            normalized["player_bg_color"] = player_bg_color
            changed = True

        if not blob_palette and ui_palette:
            background = player_bg_color or ui_palette[0]
            accent = ui_palette[1] if len(ui_palette) > 1 else None
            blob_palette = self._fallback_blob_palette(background, accent)
            normalized["blob_palette"] = blob_palette
            changed = True

        return normalized, changed

    def save(self):
        try:
            with open(self.filepath, 'w') as f: json.dump(self.cache, f, indent=4)
        except IOError as e: print(f"Error saving color cache: {e}")

    def get_album_data(self, album_id):
        data = self.cache.get(album_id)
        if not isinstance(data, dict):
            return data
        normalized, changed = self._normalize_cache_entry(data)
        if changed:
            self.cache[album_id] = normalized
            self.save()
        return normalized

    def set_album_data(self, album_id, data):
        if data is None: 
            if album_id in self.cache: del self.cache[album_id]
        else:
            if isinstance(data, dict):
                normalized, _ = self._normalize_cache_entry(data)
                self.cache[album_id] = normalized
            else:
                self.cache[album_id] = data
        self.save()
    def clear(self): self.cache = {}; self.save()


class LyricsCache:
    """Persistent cache for time-synced lyrics keyed by Spotify track_id.
    Values are either a list of (ms, text) tuples or False (no synced lyrics available).
    """
    def __init__(self, filename='lyrics_cache.json'):
        app_data_path = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        if not app_data_path:
            app_data_path = QDir.homePath()
        self.dir = QDir(app_data_path)
        if not self.dir.exists():
            self.dir.mkpath('.')
        self.filepath = self.dir.filePath(filename)
        self.cache = self._load()

    def _load(self):
        if not os.path.exists(self.filepath):
            return {}
        try:
            with open(self.filepath, 'r') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, IOError, ValueError):
            return {}

    def _save(self):
        try:
            with open(self.filepath, 'w') as f:
                json.dump(self.cache, f, separators=(',', ':'))
        except IOError as e:
            print(f"Error saving lyrics cache: {e}")

    def has(self, track_id):
        return track_id in self.cache

    def get(self, track_id):
        return self.cache.get(track_id, None)

    def set(self, track_id, data):
        """Store a list of [ms, text] pairs or False for tracks with no synced lyrics."""
        self.cache[track_id] = data
        self._save()


class GoveeController:
    def __init__(self, api_key, devices):
        self.api_key = api_key
        self.devices = devices
        self.base_url = "https://developer-api.govee.com/v1/devices/control"
        self._last_sent = {}
        self._lock = threading.Lock()

    def send_colors(self, palette, enabled=True, brightness=1.0):
        errors = []
        if not self.api_key or not enabled or not palette: return errors

        num_devices = len(self.devices)
        num_colors = len(palette)
        lights_palette = []

        if num_colors > 0:
            if num_devices <= num_colors:
                lights_palette = [palette[i] for i in range(num_devices)]
            else:
                if num_colors == 1: lights_palette = [palette[0]] * num_devices
                else:
                    for i in range(num_devices):
                        pos = i * (num_colors - 1) / (num_devices - 1)
                        idx1 = int(pos); idx2 = min(idx1 + 1, num_colors - 1); t = pos - idx1
                        c1 = palette[idx1]; c2 = palette[idx2]
                        r = int(c1[0] + (c2[0] - c1[0]) * t)
                        g = int(c1[1] + (c2[1] - c1[1]) * t)
                        b = int(c1[2] + (c2[2] - c1[2]) * t)
                        lights_palette.append((r, g, b))

        with self._lock:
            headers = {"Govee-API-Key": self.api_key, "Content-Type": "application/json"}
            for idx, color in enumerate(lights_palette):
                if idx >= num_devices: break
                device_info = self.devices[idx]
                device_id = device_info["device"]
                r, g, b = color
                correction = device_info.get("color_correction", {})
                s_mult = correction.get("s_mult"); l_mult = correction.get("l_mult")

                if s_mult or l_mult:
                    h, s, l = rgb_to_hsl(r, g, b)
                    if s_mult: s = min(1.0, s * s_mult)
                    if l_mult: l = min(1.0, l * l_mult)
                    r, g, b = hsl_to_rgb(h, s, l)
                else:
                    r *= correction.get("r", 1.0); g *= correction.get("g", 1.0); b *= correction.get("b", 1.0)
                
                r, g, b = normalize_color((r, g, b))
                if device_id not in self._last_sent: self._last_sent[device_id] = {'color': None, 'brightness': None}

                if self._last_sent[device_id]['color'] != (r, g, b):
                    payload_color = {"device": device_info["device"], "model": device_info["model"], "cmd": {"name": "color", "value": {"r": r, "g": g, "b": b}}}
                    try:
                        resp = requests.put(self.base_url, json=payload_color, headers=headers, timeout=5)
                        if resp.status_code == 200: self._last_sent[device_id]['color'] = (r, g, b)
                        elif resp.status_code == 429: errors.append(f"Rate Limit (429) - {device_info.get('name', 'Light')}"); time.sleep(2.0)
                        elif resp.status_code != 200: errors.append(f"Error {resp.status_code} - {device_info.get('name', 'Light')}")
                    except Exception: errors.append(f"Error - {device_info.get('name', 'Light')}")
                    time.sleep(0.4)

                # --- FIX: Check if brightness is None (Override Mode) ---
                if brightness is not None:
                    b_val = max(1, min(100, int(brightness * 100)))
                    if self._last_sent[device_id]['brightness'] != b_val:
                        payload_brightness = {"device": device_info["device"], "model": device_info["model"], "cmd": {"name": "brightness", "value": b_val}}
                        try:
                            resp = requests.put(self.base_url, json=payload_brightness, headers=headers, timeout=5)
                            if resp.status_code == 200: self._last_sent[device_id]['brightness'] = b_val
                            elif resp.status_code == 429: errors.append(f"Rate Limit (429) - {device_info.get('name', 'Light')}"); time.sleep(2.0)
                            elif resp.status_code != 200: errors.append(f"Error {resp.status_code} - {device_info.get('name', 'Light')}")
                        except Exception: errors.append(f"Error (Brightness) - {device_info.get('name', 'Light')}")
                        time.sleep(0.4)
        return errors
    
# [UPDATE THIS CLASS]
class SoundManager(QObject):
    """
    Manages global sound effects with pitch and volume randomization.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sounds = {} 
        self.sound_pools = {} 
        self.enabled = True
        self.base_volume = 0.5 # Default master volume
        
        # Specific volume multipliers for each sound type to balance levels
        self.volume_modifiers = {
            "click": 1.0,
            "hover": 0.4,      # Hovers should be subtle
            "slide": 0.25,     # Sliders generate many events, keep quiet
            "toggle_on": 0.3,  # Requested to be quieter
            "toggle_off": 0.3
        }
        
        from utils import resource_path 
        self._load_sound("click", "click")
        self._load_sound("hover", "hover")
        self._load_sound("slide", "slide")
        self._load_sound("toggle_on", "toggle_on")
        self._load_sound("toggle_off", "toggle_off")
        
    def _load_sound(self, name, base_filename):
        from utils import resource_path 
        found_path = None
        for ext in [".wav", ".mp3"]:
            full_path = resource_path(os.path.join("sounds", base_filename + ext))
            if os.path.exists(full_path):
                found_path = full_path
                break
        
        if found_path:
            effect = QSoundEffect()
            effect.setSource(QUrl.fromLocalFile(found_path))
            effect.setVolume(self.base_volume)
            self.sounds[name] = effect
            self.sound_pools[name] = [] 

    def set_master_volume(self, volume):
        """Sets the master volume (0.0 to 1.0)."""
        self.base_volume = max(0.0, min(1.0, volume))

    def play(self, name, pitch_shift=True, overlap=True):
        """
        Plays a sound.
        :param overlap: Default True to allow concurrent sounds.
        """
        if not self.enabled or name not in self.sounds:
            return

        effect = None
        if overlap:
            pool = self.sound_pools[name]
            for s in pool:
                if not s.isPlaying():
                    effect = s
                    break
            
            if effect is None:
                if len(pool) < 20: 
                    effect = QSoundEffect()
                    effect.setSource(self.sounds[name].source())
                    pool.append(effect)
                else:
                    effect = pool[0]
                    effect.stop()
        else:
            effect = self.sounds[name]
            if effect.isPlaying():
                effect.stop()

        # Calculate volume: Master * Specific Modifier * Random Variation
        vol_variation = random.uniform(0.95, 1.05)
        modifier = self.volume_modifiers.get(name, 1.0)
        final_volume = max(0.0, min(1.0, self.base_volume * modifier * vol_variation))
        
        effect.setVolume(final_volume)

        if pitch_shift and hasattr(effect, 'setPlaybackRate'):
             rate_variation = random.uniform(0.98, 1.02)
             effect.setPlaybackRate(rate_variation)

        effect.play()

# [UPDATE THIS CLASS]
class GlobalSoundFilter(QObject):
    """
    Event filter to detect clicks and hovers globally.
    """
    def __init__(self, sound_manager):
        super().__init__()
        self.sm = sound_manager

    def _check_val(self, slider, old_val):
        try:
            if slider.value() != old_val:
                self.sm.play("slide", overlap=True)
        except RuntimeError:
            pass

    def eventFilter(self, obj, event):
        if not self.sm.enabled: return False

        # --- Button & Tab Clicks ---
        if event.type() == QEvent.MouseButtonPress:
            # Check for standard buttons or Tab Bars
            if obj.inherits("QAbstractButton") or obj.inherits("QTabBar"): 
                if obj.isEnabled():
                    if obj.inherits("QAbstractButton") and obj.isCheckable():
                        if obj.isChecked():
                            if obj.inherits("QRadioButton") and obj.autoExclusive():
                                self.sm.play("toggle_on") 
                            else:
                                self.sm.play("toggle_off")
                        else:
                            self.sm.play("toggle_on")
                    else:
                        self.sm.play("click")
            
            elif obj.inherits("QSlider") and obj.isEnabled():
                old_val = obj.value()
                QTimer.singleShot(0, lambda: self._check_val(obj, old_val))

        # --- Dragging ---
        elif event.type() == QEvent.MouseMove:
             if obj.inherits("QSlider") and obj.isEnabled() and event.buttons():
                 old_val = obj.value()
                 QTimer.singleShot(0, lambda: self._check_val(obj, old_val))

        # --- Scrolling ---
        elif event.type() == QEvent.Wheel:
             if obj.inherits("QSlider") and obj.isEnabled():
                 old_val = obj.value()
                 QTimer.singleShot(0, lambda: self._check_val(obj, old_val))
        
        # --- NEW: Hover Sounds ---
        elif event.type() == QEvent.Enter:
            # Play hover for buttons, tabs, and sliders
            if (obj.inherits("QAbstractButton") or obj.inherits("QTabBar") or obj.inherits("QSlider")) and obj.isEnabled():
                self.sm.play("hover", overlap=True)
        
        return super().eventFilter(obj, event)


class AppleMusicClient:
    """
    Handles Apple Music API authentication and requests.
    Generates JWT tokens from developer credentials and manages API calls.
    """
    def __init__(self, team_id=None, key_id=None, private_key=None):
        self.team_id = team_id
        self.key_id = key_id
        self.private_key = private_key
        self.base_url = "https://api.music.apple.com/v1"
        self.developer_token = None
        self.user_token = None
        self.storefront = "us"  # Default, will be updated dynamically
        
        if self.team_id and self.key_id and self.private_key:
            self._generate_developer_token()
    
    def _generate_developer_token(self):
        """Generate JWT developer token from credentials."""
        try:
            import jwt  # type: ignore[import]
            import datetime
            
            # Token valid for 6 months
            expiration_time = datetime.datetime.utcnow() + datetime.timedelta(days=180)
            
            headers = {
                "alg": "ES256",
                "kid": self.key_id
            }
            
            payload = {
                "iss": self.team_id,
                "iat": int(datetime.datetime.utcnow().timestamp()),
                "exp": int(expiration_time.timestamp())
            }
            
            self.developer_token = jwt.encode(
                payload,
                self.private_key,
                algorithm="ES256",
                headers=headers
            )
            
            # Handle both string and bytes return from jwt.encode
            if isinstance(self.developer_token, bytes):
                self.developer_token = self.developer_token.decode('utf-8')
                
            return True
        except ImportError:
            print("PyJWT library not installed. Install with: pip install pyjwt cryptography")
            return False
        except Exception as e:
            print(f"Error generating Apple Music developer token: {e}")
            return False
    
    def set_user_token(self, user_token):
        """Set the user's music token for personalized requests."""
        self.user_token = user_token
    
    def _get_headers(self, include_user_token=False):
        """Get request headers with authentication."""
        headers = {
            "Authorization": f"Bearer {self.developer_token}",
            "Content-Type": "application/json"
        }
        
        if include_user_token and self.user_token:
            headers["Music-User-Token"] = self.user_token
        
        return headers
    
    def get_current_playback(self):
        """
        Get currently playing track information.
        Note: Apple Music API doesn't have a direct 'current playback' endpoint like Spotify.
        This requires MusicKit JS integration or recent play history.
        Returns None if not available through API.
        """
        # Apple Music API limitation: No direct playback state endpoint
        # Would need MusicKit JS or system integration for real-time playback
        return None
    
    def search(self, query, types=None, limit=25):
        """Search Apple Music catalog."""
        if not self.developer_token:
            return None
        
        types_str = types or "songs,albums,playlists"
        params = {
            "term": query,
            "types": types_str,
            "limit": limit
        }
        
        try:
            response = requests.get(
                f"{self.base_url}/catalog/{self.storefront}/search",
                headers=self._get_headers(),
                params=params,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Apple Music search error: {e}")
            return None
    
    def get_song(self, song_id):
        """Get song details by ID."""
        if not self.developer_token:
            return None
        
        try:
            response = requests.get(
                f"{self.base_url}/catalog/{self.storefront}/songs/{song_id}",
                headers=self._get_headers(),
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Apple Music get song error: {e}")
            return None
    
    def get_album(self, album_id):
        """Get album details by ID."""
        if not self.developer_token:
            return None
        
        try:
            response = requests.get(
                f"{self.base_url}/catalog/{self.storefront}/albums/{album_id}",
                headers=self._get_headers(),
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Apple Music get album error: {e}")
            return None
    
    def get_user_playlists(self, limit=25):
        """Get user's library playlists (requires user token)."""
        if not self.developer_token or not self.user_token:
            return []
        
        try:
            response = requests.get(
                f"{self.base_url}/me/library/playlists",
                headers=self._get_headers(include_user_token=True),
                params={"limit": limit},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except Exception as e:
            print(f"Apple Music get playlists error: {e}")
            return []
    
    def get_user_albums(self, limit=25):
        """Get user's library albums (requires user token)."""
        if not self.developer_token or not self.user_token:
            return []
        
        try:
            response = requests.get(
                f"{self.base_url}/me/library/albums",
                headers=self._get_headers(include_user_token=True),
                params={"limit": limit},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except Exception as e:
            print(f"Apple Music get albums error: {e}")
            return []
    
    def get_playlist_tracks(self, playlist_id, limit=100):
        """Get tracks from a playlist."""
        if not self.developer_token:
            return []
        
        try:
            # Check if it's a library playlist or catalog playlist
            if playlist_id.startswith("p."):
                # Library playlist (requires user token)
                url = f"{self.base_url}/me/library/playlists/{playlist_id}/tracks"
                headers = self._get_headers(include_user_token=True)
            else:
                # Catalog playlist
                url = f"{self.base_url}/catalog/{self.storefront}/playlists/{playlist_id}/tracks"
                headers = self._get_headers()
            
            response = requests.get(url, headers=headers, params={"limit": limit}, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except Exception as e:
            print(f"Apple Music get playlist tracks error: {e}")
            return []
    
    def get_album_tracks(self, album_id):
        """Get tracks from an album."""
        if not self.developer_token:
            return []
        
        try:
            response = requests.get(
                f"{self.base_url}/catalog/{self.storefront}/albums/{album_id}/tracks",
                headers=self._get_headers(),
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except Exception as e:
            print(f"Apple Music get album tracks error: {e}")
            return []
    
    def get_recently_played(self, limit=10):
        """Get recently played tracks (requires user token)."""
        if not self.developer_token or not self.user_token:
            return []
        
        try:
            response = requests.get(
                f"{self.base_url}/me/recent/played/tracks",
                headers=self._get_headers(include_user_token=True),
                params={"limit": limit},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except Exception as e:
            print(f"Apple Music get recently played error: {e}")
            return []
