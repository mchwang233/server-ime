#!/usr/bin/env python3
"""CMake prefix launcher, relocatable together with share/server-ime/engine."""
from pathlib import Path
import os
import sys
target = Path(__file__).resolve().parents[1] / "share/server-ime/engine/bin/server-ime-engine"
os.execv(sys.executable, [sys.executable, str(target), *sys.argv[1:]])
