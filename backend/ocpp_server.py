import asyncio
import websockets
import logging
import sys
import os
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- 1. FORCE PATH INJECTION (CRITICAL FIX) ---
# Ini wajib ada di paling atas agar Python bisa menemukan 'backend.database'
# meskipun dijalankan dari dalam folder backend.
current_file_path = os.path.abspath(__file__)
backend_dir = os.path.dirname(current_file_path) # Folder .../UNIEV/backend
root_dir = os.path.dirname(backend_dir)          # Folder .../UNIEV (Root)

if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# --- 2. CONFIG & LOGGING ---
ENABLE_DB = True
logging.basicConfig(level=logging.INFO, format='%(asctime)s [OCPP] %(message)s', stream=sys.stdout)
logger = logging.getLogger("OCPP")

# --- 3. DATABASE LOADING (ROBUST) ---
supabase_client = None
try:
    # Sekarang import ini pasti berhasil karena sys.path sudah diperbaiki
    from backend import config
    from backend.database import supabase
    supabase_client = supabase
    logger.info("✅ Database connected successfully.")
except ImportError as e:
    logger.error(f"❌ Critical Import Error: {e}")
    logger.error(f"   System Path: {sys.path}")
except Exception as e:
    logger.error(f"❌ Database Connection Error: {e}")

HOST = getattr(config, "OCPP_HOST", "0.0.0.0") if config else "0.0.0.0"
PORT = getattr(config, "OCPP_PORT", 9000) if config else 9000
db_executor = ThreadPoolExecutor(max_workers=3)

# --- 4. GLOBAL REGISTRY ---
connected_chargers = {}

# --- 5. LIBRARY SETUP ---
try:
    from ocpp.routing import on
    from ocpp.v16 import ChargePoint as cp16
    from ocpp.v16 import call, call_result
    from ocpp.v16.enums import Action, RegistrationStatus
    from dataclasses import dataclass

    # Auto-Patch Compatibility
    if not hasattr(call_result, 'BootNotificationPayload'):
        @dataclass
        class GenericPayload: pass
        call_result.BootNotificationPayload = getattr(call_result, 'BootNotification', GenericPayload)
        call_result.HeartbeatPayload = getattr(call_result, 'Heartbeat', GenericPayload)
        call_result.StatusNotificationPayload = getattr(call_result, 'StatusNotification', GenericPayload)
        call_result.StartTransactionPayload = getattr(call_result, 'StartTransaction', GenericPayload)
        call_result.StopTransactionPayload = getattr(call_result, 'StopTransaction', GenericPayload)
        call_result.MeterValuesPayload = getattr(call_result, 'MeterValues', GenericPayload)
        
        call.RemoteStartTransactionPayload = getattr(call, 'RemoteStartTransaction', GenericPayload)
        call.RemoteStopTransactionPayload = getattr(call, 'RemoteStopTransaction', GenericPayload)

except ImportError:
    sys.exit(1)

# --- 6. DB WORKERS ---
def _thread_process_transaction(charger_id, transaction_id, meter_stop, timestamp):
    if not supabase_client or not ENABLE_DB: return
    try:
        total_kwh = float(meter_stop) / 1000.0
        total_amount = (total_kwh * 2500) + 5000
        data = {
            "transaction_id": transaction_id, "charger_id": charger_id,
            "stop_time": timestamp, "meter_stop": meter_stop,
            "total_kwh": total_kwh, "total_amount": total_amount,
            "carbon_saved_kg": total_kwh * 0.85,
            "status": "COMPLETED", "payment_status": "PAID"
        }
        supabase_client.table("transactions").insert(data).execute()
        logger.info(f"💰 BILL: {charger_id} | {total_kwh} kWh | Rp {total_amount}")
    except: pass

def _thread_save_boot(charger_id, vendor, model):
    if not supabase_client: return
    try:
        # FORCE RESET STATUS SAAT BOOT
        data = {
            "charger_id": charger_id, 
            "vendor": vendor, 
            "model": model, 
            "status": "Available", # <--- Reset status
            "current_power_kw": 0,
            "current_session_kwh": 0,
            "last_heartbeat": datetime.utcnow().isoformat()
        }
        supabase_client.table("chargers").upsert(data).execute()
    except: pass

def _thread_save_status(charger_id, status):
    if not supabase_client: return
    try:
        supabase_client.table("chargers").update({"status": status}).eq("charger_id", charger_id).execute()
    except: pass

def _thread_save_live_meter(charger_id, kwh, kw, soc):
    if not supabase_client: return
    try:
        # Update data live untuk monitoring User App
        data = {}
        if kwh is not None: data['current_session_kwh'] = kwh
        if kw is not None: data['current_power_kw'] = kw
        if soc is not None: data['current_soc'] = soc
        
        if data:
            supabase_client.table("chargers").update(data).eq("charger_id", charger_id).execute()
    except: pass

# --- 7. HANDLER ---
class ChargePointHandler(cp16):
    @on(Action.BootNotification)
    async def on_boot_notification(self, **kwargs):
        vendor = kwargs.get('charge_point_vendor') or kwargs.get('chargePointVendor')
        model = kwargs.get('charge_point_model') or kwargs.get('chargePointModel')
        logger.info(f"📩 BOOT: {self.id}")
        
        asyncio.get_running_loop().run_in_executor(db_executor, _thread_save_boot, self.id, vendor, model)
        
        return call_result.BootNotificationPayload(
            current_time=datetime.utcnow().isoformat(), interval=30, status=RegistrationStatus.accepted
        )

    @on(Action.Heartbeat)
    async def on_heartbeat(self, **kwargs):
        return call_result.HeartbeatPayload(current_time=datetime.utcnow().isoformat())

    @on(Action.StatusNotification)
    async def on_status_notification(self, **kwargs):
        status = kwargs.get('status')
        logger.info(f"📊 STATUS {self.id}: {status}")
        asyncio.get_running_loop().run_in_executor(db_executor, _thread_save_status, self.id, status)
        return call_result.StatusNotificationPayload()

    @on(Action.StartTransaction)
    async def on_start_transaction(self, **kwargs):
        logger.info(f"⚡ START TX: {self.id}")
        return call_result.StartTransactionPayload(
            transaction_id=int(datetime.utcnow().timestamp()), id_tag_info={"status": "Accepted"}
        )

    @on(Action.StopTransaction)
    async def on_stop_transaction(self, **kwargs):
        tid = kwargs.get('transaction_id') or kwargs.get('transactionId')
        meter = kwargs.get('meter_stop') or kwargs.get('meterStop')
        ts = kwargs.get('timestamp')
        logger.info(f"🛑 STOP TX: {tid}")
        
        asyncio.get_running_loop().run_in_executor(db_executor, _thread_process_transaction, self.id, tid, meter, ts)
        
        # Reset Status di DB jadi Available setelah stop
        asyncio.get_running_loop().run_in_executor(db_executor, _thread_save_status, self.id, "Available")
        
        return call_result.StopTransactionPayload(id_tag_info={"status": "Accepted"})

    @on(Action.MeterValues)
    async def on_meter_values(self, **kwargs):
        # Logic Tangkap Meter untuk User App
        try:
            meter_val = kwargs.get('meter_value') or kwargs.get('meterValue')
            if meter_val:
                kwh = kw = soc = None
                # Parsing Sampled Value (Simplified)
                for mv in meter_val:
                    samples = mv.get('sampled_value') or mv.get('sampledValue') or []
                    for s in samples:
                        measurand = s.get('measurand') or s.get('Measurand')
                        val = float(s.get('value') or 0)
                        unit = s.get('unit') or s.get('Unit')
                        
                        if measurand == 'Energy.Active.Import.Register':
                            kwh = val / 1000 if unit == 'Wh' else val
                        elif measurand == 'Power.Active.Import':
                            kw = val / 1000 if unit == 'W' else val
                        elif measurand == 'SoC':
                            soc = int(val)
                
                if kwh is not None or kw is not None:
                    asyncio.get_running_loop().run_in_executor(db_executor, _thread_save_live_meter, self.id, kwh, kw, soc)
        except: pass
        return call_result.MeterValuesPayload()

    # --- REMOTE COMMANDS ---
    async def remote_start(self, user_id):
        logger.info(f"🚀 EXEC REMOTE START -> {self.id}")
        req = call.RemoteStartTransactionPayload(id_tag=user_id)
        await self.call(req)

    async def remote_stop(self, tx_id):
        logger.info(f"🚀 EXEC REMOTE STOP -> {self.id}")
        req = call.RemoteStopTransactionPayload(transaction_id=int(tx_id)) 
        await self.call(req)

# --- CONNECTION ---
async def on_connect(websocket, path=None):
    try:
        if path is None: path = websocket.request.path if hasattr(websocket, 'request') else websocket.path
        charger_id = (path or "/").strip('/') or "UNKNOWN"
        
        logger.info(f"🔗 CONNECTED: {charger_id}")
        cp = ChargePointHandler(charger_id, websocket)
        connected_chargers[charger_id] = cp
        await cp.start()
    except Exception as e:
        logger.error(f"🔥 ERROR: {e}")
    finally:
        if 'charger_id' in locals() and charger_id in connected_chargers:
            del connected_chargers[charger_id]

# --- COMMAND BRIDGE ---
async def command_checker():
    logger.info("👀 Command Bridge Started...")
    while True:
        if supabase_client:
            try:
                # Polling Database
                res = supabase_client.table("charging_commands").select("*").eq("status", "PENDING").execute()
                for cmd in res.data:
                    cid = cmd['charger_id']
                    action = cmd['action']
                    uid = cmd['user_id']
                    
                    if cid in connected_chargers:
                        cp = connected_chargers[cid]
                        logger.info(f"🔔 COMMAND: {action} -> {cid}")
                        
                        if action == "REMOTE_START":
                            asyncio.create_task(cp.remote_start(uid))
                        elif action == "REMOTE_STOP":
                            asyncio.create_task(cp.remote_stop(12345))
                            
                        supabase_client.table("charging_commands").update({"status": "EXECUTED"}).eq("id", cmd['id']).execute()
            except Exception as e:
                # logger.error(f"Bridge Error: {e}") # Silent error agar log tidak penuh
                pass
        await asyncio.sleep(1.5)

async def main():
    logger.info(f"--- UNIEV OCPP SERVER STARTING ON {HOST}:{PORT} ---")
    server = await websockets.serve(on_connect, HOST, int(PORT), subprotocols=['ocpp1.6'], ping_interval=None)
    await asyncio.gather(server.wait_closed(), command_checker())

if __name__ == "__main__":
    if sys.platform == 'win32': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt: pass