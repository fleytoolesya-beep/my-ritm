from __future__ import annotations

from supabase import Client, create_client

from .config import get_settings


def get_supabase_client() -> Client | None:
    settings = get_settings()
    if not settings.supabase_configured:
        return None
    return create_client(settings.supabase_url, settings.supabase_publishable_key)
