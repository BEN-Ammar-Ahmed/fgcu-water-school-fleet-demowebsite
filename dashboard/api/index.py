"""Vercel entry point. Both websites deploy from this folder as two Vercel projects;
the SITE setting in each project picks which one runs: SITE=fleet (the default) or SITE=reserve."""
import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Vercel looks for a top-level "app" in this file.
app = importlib.import_module('reserve_app' if os.environ.get('SITE', 'fleet') == 'reserve' else 'app').app
