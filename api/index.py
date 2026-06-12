"""Vercel entry point (serverless ASGI).

Vercel's filesystem is read-only except /tmp, so the database lives there:
the bundled Vilna seforim are rebuilt on each cold start (~1s). That means
on Vercel the question log and any Sefaria-ingested seforim do NOT persist
between cold starts — fine for trying it out; for the real thing use a host
with a disk (Railway / Fly.io / a small VPS — see README "Deployment").
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MIKVAOS_DB", "/tmp/mikvaos.db")

from app.main import _autoload_bundled_sources, app  # noqa: E402,F401

# Serverless runtimes don't reliably run ASGI lifespan — load explicitly.
_autoload_bundled_sources()
