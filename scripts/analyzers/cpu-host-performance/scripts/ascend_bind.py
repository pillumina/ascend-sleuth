#!/usr/bin/env python3
"""Run from any directory; copy the skill folder for Linux host execution."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hostbind.cli import main

if __name__=='__main__':sys.exit(main())
