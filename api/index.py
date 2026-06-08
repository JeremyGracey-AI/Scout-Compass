"""Vercel serverless entrypoint — exposes the Flask app as a WSGI handler.

Vercel's @vercel/python runtime serves the module-level ``app`` (a WSGI callable).
We add web/ and cli/ to the path and import the existing Flask app — the Python
generator stays the single source of truth; nothing is duplicated for hosting.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "web"))
sys.path.insert(0, str(ROOT / "cli"))

# Frontend Supabase config for the demo deploy. These are PUBLIC by design (the
# publishable/anon key is shipped to the browser and gated by row-level security).
# In production, set real env vars in the Vercel project; setdefault won't override them.
os.environ.setdefault("SUPABASE_URL", "https://ivysnobxweftdmvfevqj.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "sb_publishable_sH9zkIdjxNXc-81I5RhRjw_CYO0xuYR")

from app import app  # noqa: E402  (Flask WSGI app that Vercel serves)
