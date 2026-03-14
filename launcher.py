#!/usr/bin/env python
"""Wrapper script to launch main.py with comprehensive error capture"""

import sys
import os

# Add the current directory to path so imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    print("Starting Dynamic Player...", file=sys.stderr)
    print(f"Python version: {sys.version}", file=sys.stderr)
    print(f"Working directory: {os.getcwd()}", file=sys.stderr)
    
    print("Importing main module...", file=sys.stderr)
    import main
    
    print("Main module imported successfully", file=sys.stderr)
except ImportError as e:
    print(f"IMPORT ERROR: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"STARTUP ERROR: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
