"""
Shared Supabase client for all seed scripts.
Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in environment (.env supported).
Service role key is required, not the anon key, because seed inserts must bypass
the "public read only" RLS policies set on Tier 1 tables.
"""
import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError(
        "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY. "
        "Set them in your environment or a .env file before running seed scripts."
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def batch_upsert(table: str, rows: list, on_conflict: str, batch_size: int = 500):
    """Upsert rows in batches to avoid payload size limits / timeouts."""
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        supabase.table(table).upsert(chunk, on_conflict=on_conflict).execute()
        print(f"  upserted {i + len(chunk)}/{len(rows)} rows into {table}")
