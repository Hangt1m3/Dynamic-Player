#!/usr/bin/env python
"""Test if DynamicPlayer.exe launches successfully"""

import subprocess
import time
import sys
import os

exe_path = r"dist\DynamicPlayer.exe"

print(f"Testing {exe_path}...")
print(f"EXE exists: {os.path.exists(exe_path)}")
print(f"EXE size: {os.path.getsize(exe_path) if os.path.exists(exe_path) else 'N/A'} bytes")

try:
    # Try to run the exe
    print("\nAttempting to launch...")
    proc = subprocess.Popen(
        [exe_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait a moment for it to either launch or fail
    time.sleep(2)
    
    if proc.poll() is None:
        print("✓ EXE launched successfully (process is running)")
        proc.terminate()
        proc.wait(timeout=5)
    else:
        returncode = proc.returncode
        stdout, stderr = proc.communicate()
        print(f"✗ EXE exited with code {returncode}")
        if stdout:
            print(f"STDOUT:\n{stdout}")
        if stderr:
            print(f"STDERR:\n{stderr}")
            
except Exception as e:
    print(f"✗ Error launching EXE: {e}")
    import traceback
    traceback.print_exc()
