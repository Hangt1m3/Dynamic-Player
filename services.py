# services.py
import os
import json
import threading
import time
import requests
from PyQt5.QtCore import QStandardPaths, QDir
from utils import rgb_to_hsl, hsl_to_rgb, normalize_color

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
        if not os.path.exists(self.filepath): return {}
        try:
            with open(self.filepath, 'r') as f: return json.load(f)
        except (json.JSONDecodeError, IOError): return {}

    def save(self):
        try:
            with open(self.filepath, 'w') as f: json.dump(self.cache, f, indent=4)
        except IOError as e: print(f"Error saving color cache: {e}")

    def get_album_data(self, album_id): return self.cache.get(album_id)
    def set_album_data(self, album_id, data):
        if data is None: 
            if album_id in self.cache: del self.cache[album_id]
        else: self.cache[album_id] = data
        self.save()
    def clear(self): self.cache = {}; self.save()

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