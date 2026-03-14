#!/usr/bin/env python
"""Debug starter for DynamicPlayer with file logging"""

import sys
import os

# Ensure logging goes to a file we can check
log_file = os.path.join(os.path.expanduser('~'), 'dynamic_player_debug.log')

def log(msg):
    with open(log_file, 'a') as f:
        f.write(msg + '\n')
        f.flush()

try:
    log("=== Dynamic Player Startup ===")
    log(f"Python: {sys.version}")
    log(f"CWD: {os.getcwd()}")
    
    log("Importing modules...")
    multiprocessing = __import__('multiprocessing')
    os = __import__('os')
    sys = __import__('sys')
    
    log("Importing PyQt5...")
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtGui import  QIcon
    
    log("PyQt5 imports successful")
    log("Importing main module...")
    
    import main as main_module
    
    log("Main module imported")
    log("Creating QApplication...")
    
    multiprocessing.freeze_support()
    os.environ["XDG_SESSION_TYPE"] = "xcb"
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    
    log("QApplication created")
    app.setQuitOnLastWindowClosed(False)
    app.setOrganizationName("SpotifySync")
    app.setApplicationName("App")

    log("Creating SpotifyPlayer...")
    player = main_module.SpotifyPlayer()
    
    log("SpotifyPlayer created successfully")
    log(f"Is fullscreen: {player.is_fullscreen}")
    log(f"Multi monitor: {player.multi_monitor_mode}")
    
    if player.is_fullscreen and not player.multi_monitor_mode:
        log("Entering borderless fullscreen...")
        player._enter_borderless_fullscreen()
    else:
        log("Showing windowed...")
        player.show()

    log("Window shown, starting event loop...")
    if hasattr(player, '_start_in_wallpaper') and player._start_in_wallpaper:   
        QTimer.singleShot(100, player.toggle_wallpaper_mode)

    log("Executing app...")
    exit_code = app.exec_()
    log(f"App exited with code: {exit_code}")
    sys.exit(exit_code)
    
except Exception as e:
    import traceback
    log(f"FATAL ERROR: {type(e).__name__}: {e}")
    log(traceback.format_exc())
    sys.exit(1)
