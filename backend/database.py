# backend/database.py
import time
from supabase import create_client, Client

# --- UNIVERSAL IMPORT BLOCK ---
try:
    from backend import config
except ImportError:
    import config
# -----------------------------

class Database:
    _instance = None

    @staticmethod
    def get_client():
        if Database._instance is None:
            try:
                Database._instance = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
            except Exception as e:
                # print(f"[DB] Init Error: {e}") # Silent agar tidak spam log
                return None
        return Database._instance

    @staticmethod
    def get_latency():
        """Mengukur kecepatan respons DB dalam milidetik (ms)"""
        client = Database.get_client()
        if not client: return -1
        
        start_time = time.time()
        try:
            # Query super ringan (HEAD request)
            client.table("chargers").select("charger_id", count="exact").limit(1).execute()
            latency = (time.time() - start_time) * 1000 # convert to ms
            return round(latency, 1)
        except:
            Database._instance = None # Reset jika error
            return -1

# Global Object
supabase = Database.get_client()