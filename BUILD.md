# Building Dynamic Player Standalone Executable

## Prerequisites

- Python 3.8 or higher
- Windows OS (for Windows builds)
- Git (optional, for cloning the repository)

## Build Instructions

### 1. Install Dependencies

First, install all required Python packages:

```bash
pip install -r requirements.txt
```

This will install:
- **PyQt5**: GUI framework
- **Pillow**: Image processing
- **NumPy & scikit-learn**: Color palette extraction
- **spotipy**: Spotify API integration
- **requests**: HTTP requests
- **winsdk**: Windows media controls
- **PyInstaller**: Executable builder

### 2. Build the Executable

Run PyInstaller with the provided spec file:

```bash
pyinstaller dynamicplayer.spec
```

### 3. Locate Your Executable

The standalone executable will be created at:

```
dist/DynamicPlayer.exe
```

## What's Included in the Standalone Build

The `dynamicplayer.spec` file is configured to create a **fully standalone executable** that includes:

✅ **All Python Libraries**:
- PyQt5 (complete with QtMultimedia for sound)
- NumPy, scikit-learn (for color analysis)
- Pillow (image processing)
- spotipy (Spotify integration)
- requests, urllib3, certifi (HTTP with SSL)
- winsdk (Windows media controls)

✅ **Application Assets**:
- Sound effects (`sounds/*.wav`)
- Application icon (`icon.ico`)
- SSL certificates for HTTPS connections

✅ **Runtime Dependencies**:
- Python interpreter (embedded)
- All required DLLs and binaries

## No External Downloads Required!

The resulting `DynamicPlayer.exe` is completely self-contained. End-users can:
- Run it without installing Python
- Run it without installing any dependencies
- Run it without internet connection (after initial Spotify auth)
- Simply double-click and play!

## Troubleshooting

### Build Fails with Import Errors

If the build fails with module not found errors, try:

```bash
pip install --upgrade -r requirements.txt
pip install --upgrade pyinstaller
```

### Executable Won't Run

1. **Check antivirus**: Some antivirus software may flag PyInstaller executables
2. **Run from terminal**: Open cmd and run the exe to see error messages
3. **Check dependencies**: Make sure all packages in requirements.txt are installed

### Missing Sound Effects

If sounds don't play in the built executable:
- Ensure the `sounds/` folder exists in the project directory
- Check that all `.wav` files are present
- Rebuild with `pyinstaller --clean dynamicplayer.spec`

## Advanced Options

### Debug Build

To create a build with console output for debugging:

1. Edit `dynamicplayer.spec`
2. Change `console=False` to `console=True`
3. Rebuild with `pyinstaller dynamicplayer.spec`

### Reduce File Size

The spec file already excludes unnecessary packages like matplotlib, scipy, and pandas. To further reduce size:

1. Use UPX compression (already enabled)
2. Consider using `--onedir` mode instead of `--onefile` (faster startup)

### Clean Build

To start fresh:

```bash
pyinstaller --clean dynamicplayer.spec
```

## Distribution

The executable can be distributed via:
- Direct download (upload to GitHub releases)
- Installer (use NSIS, Inno Setup, etc.)
- Portable zip file

**File Size**: Approximately 80-150 MB (varies based on dependencies)

## Notes

- The spec file uses UPX compression to reduce size
- All dependencies are statically linked
- No Python installation required on target machine
- Windows Defender may scan the file on first run (this is normal)
