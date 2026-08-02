# Signals skill — thin wrapper

from __future__ import annotations

import runpy
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[2] / "indonesia-intel" / "scripts" / "smoke_section7.py"
sys.argv = [str(TARGET), "--skill", "signals", *sys.argv[1:]]
runpy.run_path(str(TARGET), run_name="__main__")
