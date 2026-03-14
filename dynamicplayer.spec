# -*- mode: python ; coding: utf-8 -*-
"""
Dynamic Player - PyInstaller spec

Build command:
    pyinstaller --clean --noconfirm dynamicplayer.spec

Output:
    dist/DynamicPlayer.exe

BUILDING STANDALONE EXECUTABLE:
================================
1. Install all dependencies: pip install -r requirements.txt
2. Build the executable: pyinstaller dynamicplayer.spec
3. Find the standalone exe in: dist/DynamicPlayer.exe

The resulting executable is fully standalone and includes:
- All Python dependencies (PyQt5, NumPy, scikit-learn, spotipy, etc.)
- Sound files (sounds/*.wav)
- Application icon
- Windows SDK for media control
- Apple Music API support (PyJWT, cryptography - optional)
- SSL certificates for HTTPS

No external downloads or installations required by end-users!
Note: Apple Music API features are optional and gracefully disabled if
      PyJWT/cryptography aren't installed.
"""

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs
import sys
import os

# Collect all submodules for comprehensive dependency coverage
winsdk_hidden_imports = collect_submodules('winsdk')
sklearn_hidden_imports = collect_submodules('sklearn')
spotipy_hidden_imports = collect_submodules('spotipy')
scipy_hidden_imports = collect_submodules('scipy')
pyqt5_hidden_imports = collect_submodules('PyQt5')  # Include ALL PyQt5 submodules

# Optional: collect jwt and cryptography if available
try:
    jwt_hidden_imports = collect_submodules('jwt')
except:
    jwt_hidden_imports = []

try:
    cryptography_hidden_imports = collect_submodules('cryptography')
except:
    cryptography_hidden_imports = []

# Explicit hidden imports for all dependencies
other_hidden_imports = [
    # PIL/Pillow
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'PIL.ImageFilter',
    
    # Numerical/Scientific
    'numpy',
    'scipy.signal',
    'scipy.fftpack',
    'scipy.stats',
    'sklearn.cluster',
    'sklearn.preprocessing',
    
    # UI/Graphics
    'pystray',
    
    # Audio
    'sounddevice',
    'soundfile',
    
    # HTTP/Web
    'requests',
    'urllib3',
    'certifi',
    
    # JSON/Serialization
    'json',
    'pickle',
    
    # Spotify & Music
    'spotipy',
    'spotipy.cache_handler',
    
    # System/OS
    'ctypes',
    'winsdk.windows.media.control',
    'winsdk.windows',
    
    # Custom UI modules
    'ui.dialogs',
    'ui.widgets',
    'ui.styles',
    'ui.overlays',
    'ui.renderers',
    'ui.gl_widget',
    'ui.playlist_panel',
    
    # Standard library (safety)
    'threading',
    'queue',
    'json',
    'base64',
    'colorsys',
    'math',
    'time',
    'os',
    'sys',
    'pathlib',
    'subprocess',
    'logging',
    'webbrowser',
    'asyncio',
    'datetime',
    'hashlib',
]

# Collect data files from packages that need them
try:
    sklearn_datas = collect_data_files('sklearn')
except:
    sklearn_datas = []

try:
    certifi_datas = collect_data_files('certifi')
except:
    certifi_datas = []

try:
    cryptography_datas = collect_data_files('cryptography')
except:
    cryptography_datas = []

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('icon.ico', '.'),
        ('sounds', 'sounds'),
    ] + sklearn_datas + certifi_datas + cryptography_datas,
    hiddenimports=pyqt5_hidden_imports + winsdk_hidden_imports + sklearn_hidden_imports + spotipy_hidden_imports + scipy_hidden_imports + jwt_hidden_imports + cryptography_hidden_imports + other_hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['hooks/qt_opengl_runtime.py'],
    excludes=['matplotlib', 'pandas', 'tkinter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DynamicPlayer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)