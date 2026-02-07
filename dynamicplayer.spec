# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

# 1. Collect all submodules for winsdk to prevent "Module not found" errors
winsdk_hidden_imports = collect_submodules('winsdk')

# 2. Add other dynamic libraries that might be missed
other_hidden_imports = [
    'pystray', 
    'PIL', 
    'PIL.Image', 
    'winsdk.windows.media.control' # Explicitly ensuring the media control is there
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('icon.ico', '.'),
        ('sounds', 'sounds'), # <--- ADDED THIS LINE: Bundles the sounds folder
        ('images', 'images'), # <--- ADDED THIS LINE: Bundles the images folder
        # ('fonts', 'fonts'), # Uncomment if you have a physical fonts folder
    ],
    # 3. Combine the hidden imports
    hiddenimports=winsdk_hidden_imports + other_hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DynamicPlayer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False, # Set to True if you want to see error messages during testing
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)