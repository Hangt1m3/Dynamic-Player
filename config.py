# config.py
SPOTIPY_REDIRECT_URI = "http://127.0.0.1:8888/"
SPOTIFY_SCOPE = "user-read-playback-state user-read-currently-playing user-modify-playback-state user-library-read"

# Apple Music API Configuration
APPLE_MUSIC_API_BASE = "https://api.music.apple.com/v1"
APPLE_MUSIC_STOREFRONT = "us"  # Default storefront, will be updated based on user region

# Default values
SPOTIFY_GREEN = [29, 185, 84]
APPLE_MUSIC_RED = [250, 55, 90]  # Apple Music brand color
GITHUB_OWNER = "Hangt1m3" 
GITHUB_REPO = "Dynamic-Player"
GITHUB_TOKEN = "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"

# --- NEW: App Version ---
APP_VERSION = "1.2.1"

# Background rendering configuration.
# OpenGL is preferred where safe for smooth, low-CPU lava-lamp animation.
ENABLE_OPENGL_BACKGROUND = True
FORCE_RASTER_BACKGROUND = False
BACKGROUND_TARGET_FPS = 30
LAVA_LAMP_INTENSITY = 1.0
LAVA_LAMP_PRESET = "color_pop"
MAX_SHADER_BLOB_COLORS = 8