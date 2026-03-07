# -*- mode: python ; coding: utf-8 -*-
#
# Dynamic Player - PyInstaller Spec File
# 
# BUILDING STANDALONE EXECUTABLE:
# ================================
# 1. Install all dependencies: pip install -r requirements.txt
# 2. Build the executable: pyinstaller dynamicplayer.spec
# 3. Find the standalone exe in: dist/DynamicPlayer.exe
#
# The resulting executable is fully standalone and includes:
# - All Python dependencies (PyQt5, NumPy, scikit-learn, spotipy, etc.)
# - Sound files (sounds/*.wav)
# - Application icon
# - Windows SDK for media control
# - Apple Music API support (PyJWT, cryptography - optional)
# - SSL certificates for HTTPS
#
# No external downloads or installations required by end-users!
# Note: Apple Music API features are optional and gracefully disabled if
#       PyJWT/cryptography aren't installed.
#

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs
import sys
import os
from pathlib import Path

# Collect all submodules for comprehensive dependency coverage
winsdk_hidden_imports = collect_submodules('winsdk')
sklearn_hidden_imports = collect_submodules('sklearn')
spotipy_hidden_imports = collect_submodules('spotipy')
scipy_hidden_imports = collect_submodules('scipy')

# Apple Music API dependencies (optional)
try:
    jwt_hidden_imports = collect_submodules('jwt')
    cryptography_hidden_imports = collect_submodules('cryptography')
except:
    jwt_hidden_imports = []
    cryptography_hidden_imports = []

# Optional binary collections for packages that may rely on native libs.
# This is additive/safe: if a package has no collectable binaries, we keep an empty list.
try:
    cryptography_binaries = collect_dynamic_libs('cryptography')
except:
    cryptography_binaries = []

try:
    winsdk_binaries = collect_dynamic_libs('winsdk')
except:
    winsdk_binaries = []

# Optional Qt OpenGL runtime binaries (ANGLE/software renderer) for broader GPU/driver compatibility.
qt_opengl_runtime_binaries = []
try:
    import PyQt5

    pyqt5_root = Path(PyQt5.__file__).resolve().parent
    qt_bin_candidates = [pyqt5_root / 'Qt5' / 'bin', pyqt5_root / 'Qt' / 'bin']
    for qt_bin_dir in qt_bin_candidates:
        if not qt_bin_dir.exists():
            continue
        for dll_name in ('opengl32sw.dll', 'libEGL.dll', 'libGLESv2.dll', 'd3dcompiler_47.dll'):
            dll_path = qt_bin_dir / dll_name
            if dll_path.exists():
                qt_opengl_runtime_binaries.append((str(dll_path), '.'))
except:
    qt_opengl_runtime_binaries = []

# Explicit hidden imports for all dependencies
other_hidden_imports = [
    # PyQt5 modules
    'PyQt5.QtMultimedia',
    'PyQt5.QtCore',
    'PyQt5.QtWidgets',
    'PyQt5.QtGui',
    'PyQt5.QtOpenGL',
    'PyQt5.sip',
    
    # PIL/Pillow
    'PIL',
    'PIL.Image',
    'PIL._imaging',
    
    # NumPy and scientific computing
    'numpy',
    'numpy.core',
    'numpy.core._multiarray_umath',
    'scipy',
    'scipy.sparse',
    
    # Scikit-learn
    'sklearn',
    'sklearn.cluster',
    'sklearn.cluster._kmeans',
    
    # Spotipy and dependencies
    'spotipy',
    'spotipy.oauth2',
    
    # Requests and dependencies
    'requests',
    'urllib3',
    'certifi',
    'charset_normalizer',
    'idna',
    
    # Windows SDK (explicitly)
    'winsdk.windows.media.control',
    'winsdk.windows.storage.streams',
    
    # Apple Music API (optional - jwt/PyJWT and cryptography)
    'jwt',
    'cryptography',
    'cryptography.hazmat',
    'cryptography.hazmat.primitives',
    'cryptography.hazmat.primitives.asymmetric',
    'cryptography.hazmat.primitives.serialization',
    'cryptography.hazmat.backends',
    
    # Standard library that sometimes needs explicit inclusion
    'json',
    'base64',
    'io',
    'threading',
    'multiprocessing',
    'asyncio',
    'datetime',
    'hashlib',
    'random',
    'ctypes',

    # New background renderer modules (additive explicit coverage).
    'ui.renderers',
    'ui.gl_widget',
]

# Collect data files from packages that need them
sklearn_datas = collect_data_files('sklearn', include_py_files=True)
certifi_datas = collect_data_files('certifi')

# Collect cryptography data files (optional)
try:
    cryptography_datas = collect_data_files('cryptography')
except:
    cryptography_datas = []

# Optional OpenGL plugin folders for Qt (safe if absent).
qt_opengl_plugin_datas = []
try:
    import PyQt5

    pyqt5_root = Path(PyQt5.__file__).resolve().parent
    qt_plugins_candidates = [pyqt5_root / 'Qt5' / 'plugins', pyqt5_root / 'Qt' / 'plugins']
    for plugins_root in qt_plugins_candidates:
        if not plugins_root.exists():
            continue

        for plugin_subdir in ('renderers', 'platforms'):
            source_dir = plugins_root / plugin_subdir
            if source_dir.exists():
                qt_opengl_plugin_datas.append((str(source_dir), os.path.join('PyQt5', 'Qt', 'plugins', plugin_subdir)))
except:
    qt_opengl_plugin_datas = []

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=winsdk_binaries + cryptography_binaries + qt_opengl_runtime_binaries,
    datas=[
        ('icon.ico', '.'),
        ('sounds', 'sounds'),
    ] + sklearn_datas + certifi_datas + cryptography_datas + qt_opengl_plugin_datas,
    hiddenimports=winsdk_hidden_imports + sklearn_hidden_imports + spotipy_hidden_imports + scipy_hidden_imports + jwt_hidden_imports + cryptography_hidden_imports + other_hidden_imports,


    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary packages to reduce size
        'matplotlib',
        'pandas',
        'tkinter',
    ],
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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    icon='icon.ico',
)