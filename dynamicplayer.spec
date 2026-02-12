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
# - SSL certificates for HTTPS
#
# No external downloads or installations required by end-users!
#

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs
import sys
import os

# Collect all submodules for comprehensive dependency coverage
winsdk_hidden_imports = collect_submodules('winsdk')
sklearn_hidden_imports = collect_submodules('sklearn')
spotipy_hidden_imports = collect_submodules('spotipy')

# Explicit hidden imports for all dependencies
other_hidden_imports = [
    # PyQt5 modules
    'PyQt5.QtMultimedia',
    'PyQt5.QtCore',
    'PyQt5.QtWidgets',
    'PyQt5.QtGui',
    'PyQt5.sip',
    
    # PIL/Pillow
    'PIL',
    'PIL.Image',
    'PIL._imaging',
    
    # NumPy and scientific computing
    'numpy',
    'numpy.core',
    'numpy.core._multiarray_umath',
    
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
    
    # Standard library that sometimes needs explicit inclusion
    'json',
    'base64',
    'io',
    'threading',
    'multiprocessing',
    'asyncio',
]

# Collect data files from packages that need them
sklearn_datas = collect_data_files('sklearn', include_py_files=True)
certifi_datas = collect_data_files('certifi')

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('icon.ico', '.'),
        ('sounds', 'sounds'),
    ] + sklearn_datas + certifi_datas,
    hiddenimports=winsdk_hidden_imports + sklearn_hidden_imports + spotipy_hidden_imports + other_hidden_imports,


    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary packages to reduce size
        'matplotlib',
        'scipy',
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
)