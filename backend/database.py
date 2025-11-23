# backend/database.py
import os
import logging
from supabase import create_client, Client

logger = logging.getLogger("UNIEV")

try:
    from backend import config
except Exception:
    try:
        import config
    except Exception:
        config = None

_supabase: Client | None = None

def get_client() -> Client | None:
    global _supabase
    if _supabase is not None:
        return _supabase
    try:
        url = os.getenv("SUPABASE_URL") or getattr(config, "SUPABASE_URL", None)
        key = os.getenv("SUPABASE_KEY") or getattr(config, "SUPABASE_KEY", None)
        if not url or not key:
            raise RuntimeError("Supabase credentials missing")
        _supabase = create_client(url, key)
        try:
            _supabase.table("chargers").select("count").execute()
            logger.info("✅ Database connection established")
        except Exception:
            logger.warning("⚠️ Supabase connected but test query failed; continuing")
        return _supabase
    except Exception as e:
        logger.warning(f"⚠️ Using mock database client: {e}")
        class MockClient:
            def table(self, name):
                return MockTable()
        class MockTable:
            def select(self, *args, **kwargs): return self
            def insert(self, data): return self
            def update(self, data): return self
            def upsert(self, data): return self
            def eq(self, *args, **kwargs): return self
            def execute(self):
                class MockResult:
                    data = []
                return MockResult()
        return MockClient()

supabase = get_client()

class Database:
    @staticmethod
    def get_client():
        return supabase

    @staticmethod
    def get_latency():
        import time
        client = supabase
        if client is None:
            return -1
        start = time.time()
        try:
            client.table("chargers").select("charger_id").limit(1).execute()
            return round((time.time() - start) * 1000, 1)
        except Exception:
            return -1