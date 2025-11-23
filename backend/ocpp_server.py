import asyncio
import websockets
import logging
import sys
import traceback
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- CONFIG ---
ENABLE_DB = True

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [OCPP] %(message)s', stream=sys.stdout)
logger = logging.getLogger("OCPP")

# --- PATH FIXER ---
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# --- BILLING ENGINE IMPORT ---
from backend.billing_engine import BillingCalculator, CARBON_SAVING_FACTOR

# --- CONFIG LOAD (Tolerant) ---
try:
    from backend import config
except ImportError:
    try:
        import config
    except:
        config = None

# Resolve Host/Port (Fallback ke default jika config gagal)
HOST = getattr(config, "OCPP_HOST", None) or getattr(config, "HOST", "0.0.0.0")
PORT = getattr(config, "OCPP_PORT", None) or getattr(config, "PORT_OCPP", 9000)

# --- DATABASE CLIENT RESOLVER (Tolerant) ---
supabase_client = None
try:
    # Coba cari fungsi get_client
    from backend.database import get_client
    supabase_client = get_client()
except ImportError:
    try:
        # Coba cari objek supabase langsung
        from backend.database import supabase
        supabase_client = supabase
    except:
        logger.warning("⚠️ Supabase client not found. DB operations will be skipped.")

# Executor untuk DB (Agar tidak memblokir WebSocket)
# [FIX] Gunakan ThreadPoolExecutor dari concurrent.futures
db_executor = ThreadPoolExecutor(max_workers=3)

# --- OCPP LIBRARY SETUP ---
try:
    from ocpp.routing import on
    from ocpp.v16 import ChargePoint as cp16
    from ocpp.v16 import call_result
    from ocpp.v16.enums import Action, RegistrationStatus
    
    # Auto-Patching Payload jika library versi lama/rusak
    from dataclasses import dataclass
    if not hasattr(call_result, 'BootNotificationPayload'):
        @dataclass
        class GenericPayload: pass
        
        call_result.BootNotificationPayload = getattr(call_result, 'BootNotification', GenericPayload)
        call_result.HeartbeatPayload = getattr(call_result, 'Heartbeat', GenericPayload)
        call_result.StatusNotificationPayload = getattr(call_result, 'StatusNotification', GenericPayload)
        call_result.StartTransactionPayload = getattr(call_result, 'StartTransaction', GenericPayload)
        call_result.StopTransactionPayload = getattr(call_result, 'StopTransaction', GenericPayload)
        call_result.MeterValuesPayload = getattr(call_result, 'MeterValues', GenericPayload)

except ImportError as e:
    logger.error("CRITICAL: Failed importing OCPP library: %s", e)
    sys.exit(1)

# --- DB WORKER HELPERS ---
def _thread_save_boot(charger_id, vendor, model):
    if not supabase_client or not ENABLE_DB: return
    try:
        data = {
            "charger_id": charger_id,
            "vendor": vendor,
            "model": model,
            "status": "Available",
            "last_heartbeat": datetime.utcnow().isoformat()
        }
        supabase_client.table("chargers").upsert(data).execute()
        logger.info(f"   └── [DB] Saved Boot: {charger_id}")
    except Exception as e:
        logger.warning(f"   └── [DB ERROR] Boot: {e}")

def _thread_save_transaction(charger_id, transaction_id, id_tag, meter_start, meter_stop, start_time, stop_time):
    if not supabase_client or not ENABLE_DB: return
    try:
        kwh_usage = (meter_stop - meter_start) / 1000.0
        duration_seconds = (stop_time - start_time).total_seconds()
        duration_minutes = duration_seconds / 60

        # Calculate billing
        billing_calculator = BillingCalculator(supabase_client)
        bill_details = billing_calculator.calculate_final_bill(charger_id, kwh_usage, duration_minutes)
        carbon_saved = billing_calculator.calculate_carbon_saved(kwh_usage)

        data = {
            "transaction_id": transaction_id,
            "charger_id": charger_id,
            "id_tag": id_tag,
            "meter_start": meter_start,
            "meter_stop": meter_stop,
            "start_time": start_time.isoformat(),
            "stop_time": stop_time.isoformat(),
            "total_kwh": round(kwh_usage, 2),
            "total_amount": bill_details["total_amount"],
            "carbon_saved_kg": carbon_saved,
            "status": "COMPLETED",
            "tariff_name": bill_details["tariff_name"],
            "is_peak_hour": bill_details["is_peak_hour"]
        }
        supabase_client.table("transactions").insert(data).execute()
        logger.info(f"   └── [DB] Saved Transaction: {transaction_id} for {charger_id}")
    except Exception as e:
        logger.warning(f"   └── [DB ERROR] Transaction: {e}")

def _thread_save_status(charger_id, status):
    if not supabase_client or not ENABLE_DB: return
    try:
        supabase_client.table("chargers").update({"status": status}).eq("charger_id", charger_id).execute()
    except: pass

# --- MAIN CHARGEPOINT HANDLER ---
class ChargePointHandler(cp16):
    def __init__(self, id, websocket):
        super().__init__(id, websocket)
        self.current_transaction = {} # Untuk menyimpan state transaksi


    # [PERBAIKAN UTAMA] Parameter menggunakan camelCase (sesuai JSON OCPP)
    # Tambahkan **kwargs untuk menangkap parameter tambahan agar tidak crash
    
    @on(Action.BootNotification)
    async def on_boot_notification(self, chargePointVendor, chargePointModel, **kwargs):
        logger.info(f"📩 BOOT: {self.id} (Vendor: {chargePointVendor}, Model: {chargePointModel})")

        # DB Save (Background)
        loop = asyncio.get_running_loop()
        loop.run_in_executor(db_executor, _thread_save_boot, self.id, chargePointVendor, chargePointModel)

        # Respond Immediately
        return call_result.BootNotificationPayload(
            currentTime=datetime.utcnow().isoformat(),
            interval=30,
            status=RegistrationStatus.accepted
        )

    @on(Action.Heartbeat)
    async def on_heartbeat(self, **kwargs):
        # logger.info(f"❤️ HEARTBEAT: {self.id}")
        return call_result.HeartbeatPayload(
            currentTime=datetime.utcnow().isoformat()
        )

    @on(Action.StatusNotification)
    async def on_status_notification(self, connectorId, errorCode, status, **kwargs):
        logger.info(f"📊 STATUS {self.id} (Conn: {connectorId}): {status} | Err: {errorCode}")
        
        loop = asyncio.get_running_loop()
        loop.run_in_executor(db_executor, _thread_save_status, self.id, status)
        
        return call_result.StatusNotificationPayload()

    @on(Action.StartTransaction)
    async def on_start_transaction(self, connectorId, idTag, meterStart, timestamp, **kwargs):
        logger.info(f"⚡ START TX: {self.id} (Tag: {idTag}, Meter: {meterStart})")
        
        # Generate a unique transaction ID (e.g., timestamp)
        transaction_id = int(datetime.utcnow().timestamp())
        
        # Store transaction details in memory
        self.current_transaction[connectorId] = {
            "transaction_id": transaction_id,
            "id_tag": idTag,
            "meter_start": meterStart,
            "start_time": datetime.utcnow()
        }

        return call_result.StartTransactionPayload(
            transactionId=transaction_id,
            idTagInfo={"status": "Accepted"}
        )

    @on(Action.StopTransaction)
    async def on_stop_transaction(self, transactionId, meterStop, timestamp, **kwargs):
        logger.info(f"🛑 STOP TX: {transactionId} (Meter: {meterStop})")
        
        # [FIX] Ambil connectorId dari kwargs jika ada, atau asumsikan 1
        connector_id = kwargs.get('connectorId', 1)

        # Retrieve transaction details from memory
        if connector_id in self.current_transaction and self.current_transaction[connector_id]["transaction_id"] == transactionId:
            tx_data = self.current_transaction.pop(connector_id)
            
            # Save transaction to DB in background
            loop = asyncio.get_running_loop()
            loop.run_in_executor(db_executor, _thread_save_transaction,
                                 self.id,
                                 tx_data["transaction_id"],
                                 tx_data["id_tag"],
                                 tx_data["meter_start"],
                                 meterStop,
                                 tx_data["start_time"],
                                 datetime.utcnow())
        else:
            logger.warning(f"   └── [OCPP] StopTransaction received for unknown or mismatched transaction ID: {transactionId}")

        return call_result.StopTransactionPayload(
            idTagInfo={"status": "Accepted"}
        )

    @on(Action.MeterValues)
    async def on_meter_values(self, connectorId, meterValue, **kwargs):
        # MeterValues sering mengirim data kompleks, gunakan kwargs agar aman.
        # Untuk saat ini, kita hanya log dan tidak menyimpan setiap meter value ke DB
        # karena bisa sangat banyak. Hanya total di StopTransaction yang disimpan.
        # logger.debug(f"📈 METER: {self.id} (Conn: {connectorId})")
        return call_result.MeterValuesPayload()

# --- CONNECTION HANDLER (UNIVERSAL) ---
async def on_connect(websocket, path=None):
    """
    Handler Universal:
    - Websockets v10: Mengirim (websocket, path)
    - Websockets v14+: Mengirim (websocket) saja, path ada di properti
    """
    try:
        # 1. Extract Path / Charger ID dengan Aman
        if path is None:
            # Cek atribut di versi baru
            if hasattr(websocket, 'request') and hasattr(websocket.request, 'path'):
                path = websocket.request.path
            elif hasattr(websocket, 'path'):
                path = websocket.path
        
        if not path: path = "/"
        charger_id = path.strip('/') or "UNKNOWN"

        logger.info(f"🔗 CLIENT CONNECTED: {charger_id}")

        # 2. Start Handler
        cp = ChargePointHandler(charger_id, websocket)
        await cp.start()

    except websockets.exceptions.ConnectionClosed:
        logger.info(f"❌ DISCONNECTED: {charger_id}")
    except Exception as e:
        logger.error(f"🔥 ERROR in CP {charger_id}: {e}")
        traceback.print_exc()

# --- START SERVER ---
async def main():
    logger.info(f"--- UNIEV OCPP SERVER STARTING ON {HOST}:{PORT} ---")
    
    # ping_interval=None mencegah timeout 20 detik default yang agresif
    server = await websockets.serve(
        on_connect,
        HOST,
        int(PORT),
        subprotocols=['ocpp1.6'],
        ping_interval=None
    )
    await server.wait_closed()

if __name__ == "__main__":
    # Windows loop policy fix
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down OCPP server.")
    except Exception:
        logger.error("Unhandled exception: %s", traceback.format_exc())