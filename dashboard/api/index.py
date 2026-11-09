"""Vercel entry point. Both websites deploy from this folder as two Vercel projects;
the SITE setting in each project picks which one runs: SITE=fleet (the default) or SITE=reserve."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if os.environ.get('SITE', 'fleet') == 'reserve':
    from reserve_app import app
else:
    from app import app

__all__ = ['app']
