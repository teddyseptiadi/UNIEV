import streamlit as st
import asyncio
import threading
import time
import pandas as pd
import logging
import random
from datetime import datetime
import sys

from streamlit.runtime.scriptrunner import add_script_run_ctx

# --- CONFIG ---
st.set_page_config(page_title="UNIEV Turbo Simulator", page_icon="🚀", layout="wide")

if "logs" not in st.session_state: st.session_state["logs"] = []
def ui_log(message, type="INFO"):
    entry = {"Time": datetime.now().strftime("%H:%M:%S"), "Type": type, "Message": message}
    st.session_state["logs"].insert(0, entry)
    if len(st.session_state["logs"]) > 100: st.session_state["logs"].pop()

# --- IMPORTS ---
try:
    import websockets
    from ocpp.routing import on
    from ocpp.v16 import ChargePoint as cp16
    from ocpp.v16 import call, call_result
    from ocpp.v16.enums import RegistrationStatus, Action
    from dataclasses import dataclass
    
    # Patching
    if not hasattr(call_result, 'BootNotificationPayload'):
        @dataclass
        class GenericPayload: pass
        call_result.BootNotificationPayload = getattr(call_result, 'BootNotification', GenericPayload)
        call_result.RemoteStartTransactionPayload = getattr(call_result, 'RemoteStartTransaction', GenericPayload)
        call_result.RemoteStopTransactionPayload = getattr(call_result, 'RemoteStopTransaction', GenericPayload)

    if not hasattr(call, 'BootNotificationPayload'):
        call.BootNotificationPayload = getattr(call, 'BootNotification', None)
        call.StatusNotificationPayload = getattr(call, 'StatusNotification', None)
        call.StartTransactionPayload = getattr(call, 'StartTransaction', None)
        call.StopTransactionPayload = getattr(call, 'StopTransaction', None)
        call.MeterValuesPayload = getattr(call, 'MeterValues', None)

except ImportError as e:
    st.error(f"CRITICAL ERROR: {e}")
    st.stop()

# --- STATE ---
if "sim" not in st.session_state:
    st.session_state.sim = {
        "connected": False, "status": "Offline", "transaction_id": None, "is_charging": False,
        "voltage": 220, "current": 0.0, "power": 0.0, "kwh_total": 0.0, "soc": 20,
        "stop_event": threading.Event(), "cmd_queue": [] 
    }

# --- LOGIC ---
class WebChargePoint(cp16):
    
    async def validate_message(self, *args, **kwargs): pass 

    async def send_boot(self, model, vendor):
        req = call.BootNotificationPayload(charge_point_model=model, charge_point_vendor=vendor)
        return await self.call(req)

    async def send_status(self, status, err="NoError"):
        await self.call(call.StatusNotificationPayload(connector_id=1, error_code=err, status=status))

    async def start_txn(self, id_tag):
        start_wh = int(st.session_state.sim["kwh_total"] * 1000)
        res = await self.call(call.StartTransactionPayload(connector_id=1, id_tag=id_tag, meter_start=start_wh, timestamp=datetime.utcnow().isoformat()))
        return res.transaction_id

    async def stop_txn(self, tx_id):
        stop_wh = int(st.session_state.sim["kwh_total"] * 1000)
        await self.call(call.StopTransactionPayload(transaction_id=tx_id, meter_stop=stop_wh, timestamp=datetime.utcnow().isoformat()))

    async def send_meter(self, tx_id, v, i, p, soc):
        current_wh = str(st.session_state.sim["kwh_total"] * 1000)
        vals = [
            {"value": str(v), "measurand": "Voltage", "unit": "V"},
            {"value": str(i), "measurand": "Current.Import", "unit": "A"},
            {"value": str(p * 1000), "measurand": "Power.Active.Import", "unit": "W"},
            {"value": current_wh, "measurand": "Energy.Active.Import.Register", "unit": "Wh"},
            {"value": str(int(soc)), "measurand": "SoC", "unit": "Percent"}
        ]
        await self.call(call.MeterValuesPayload(connector_id=1, transaction_id=tx_id, meter_value=[{"timestamp": datetime.utcnow().isoformat(), "sampled_value": vals}]))

    # [CRITICAL FIX] HANDLER UNTUK REMOTE START/STOP DARI SERVER
    @on(Action.RemoteStartTransaction)
    async def on_remote_start(self, **kwargs):
        id_tag = kwargs.get('id_tag') or kwargs.get('idTag')
        ui_log(f"🔔 REMOTE START RECEIVED (User: {id_tag})", "WARN")
        
        # Trigger Start di Loop Utama
        st.session_state.sim["cmd_queue"].append({"action": "START", "rfid": id_tag})
        
        return call_result.RemoteStartTransactionPayload(status=RegistrationStatus.accepted)

    @on(Action.RemoteStopTransaction)
    async def on_remote_stop(self, **kwargs):
        ui_log("🔔 REMOTE STOP RECEIVED", "WARN")
        st.session_state.sim["cmd_queue"].append({"action": "STOP"})
        return call_result.RemoteStopTransactionPayload(status=RegistrationStatus.accepted)

# --- THREAD ---
def thread_main(url, cp_id, model, vendor):
    async def async_loop():
        try:
            ui_log(f"Connecting to {url}/{cp_id}...", "SYS")
            async with websockets.connect(f"{url}/{cp_id}", subprotocols=['ocpp1.6']) as ws:
                cp = WebChargePoint(cp_id, ws)
                st.session_state.sim["connected"] = True
                st.session_state.sim["status"] = "Connected"
                ui_log("WebSocket Handshake OK", "SUCCESS")

                # Jalankan Listener di background agar bisa terima Remote Start
                listener = asyncio.create_task(cp.start())

                try:
                    res = await cp.send_boot(model, vendor)
                    if res.status == RegistrationStatus.accepted:
                        ui_log("Boot Accepted!", "SUCCESS")
                        await cp.send_status("Available")
                        st.session_state.sim["status"] = "Available"
                        
                        while not st.session_state.sim["stop_event"].is_set():
                            if listener.done(): break

                            if st.session_state.sim["cmd_queue"]:
                                cmd = st.session_state.sim["cmd_queue"].pop(0)
                                
                                if cmd['action'] == "START":
                                    tx = await cp.start_txn(cmd.get('rfid', 'Unknown'))
                                    st.session_state.sim["transaction_id"] = tx
                                    st.session_state.sim["is_charging"] = True
                                    st.session_state.sim["status"] = "Charging"
                                    # Auto Set Load biar kelihatan jalan
                                    st.session_state.sim["current"] = 16.0 
                                    await cp.send_status("Charging")
                                    ui_log(f"Charging Started (TX: {tx})", "INFO")
                                    
                                elif cmd['action'] == "STOP":
                                    if st.session_state.sim["transaction_id"]:
                                        await cp.stop_txn(st.session_state.sim["transaction_id"])
                                        st.session_state.sim["transaction_id"] = None
                                        st.session_state.sim["is_charging"] = False
                                        st.session_state.sim["status"] = "Available"
                                        st.session_state.sim["current"] = 0.0
                                        await cp.send_status("Available")
                                        ui_log("Charging Stopped", "SUCCESS")
                                        
                                elif cmd['action'] == "STATUS_CHANGE":
                                    st.session_state.sim["status"] = cmd['status']
                                    await cp.send_status(cmd['status'], "InternalError" if cmd['status']=="Faulted" else "NoError")

                            if st.session_state.sim["is_charging"]:
                                v = st.session_state.sim["voltage"]
                                i = st.session_state.sim["current"]
                                p = (v * i) / 1000
                                st.session_state.sim["power"] = p
                                st.session_state.sim["kwh_total"] += p * (1/3600) 
                                if st.session_state.sim["soc"] < 100: st.session_state.sim["soc"] += 0.05

                                try:
                                    await cp.send_meter(st.session_state.sim["transaction_id"], v, i, p, st.session_state.sim["soc"])
                                except: pass
                            
                            await asyncio.sleep(1)
                    else:
                        ui_log("Boot Rejected!", "ERROR")
                except Exception as e:
                    ui_log(f"Logic Error: {e}", "ERROR")
                
                listener.cancel()
        except Exception as e:
            ui_log(f"Connection Error: {e}", "ERROR")
        finally:
            if "sim" in st.session_state:
                st.session_state.sim["connected"] = False
                st.session_state.sim["status"] = "Offline"
            ui_log("Disconnected.", "SYS")

    asyncio.run(async_loop())

# --- GUI ---
st.markdown("""
<style>
div[data-testid="metric-container"] { background-color: #262730; border: 1px solid #464b5c; padding: 10px; border-radius: 5px; }
</style>
""", unsafe_allow_html=True)

st.title("🚀 UNIEV Turbo Simulator")

# SIDEBAR
with st.sidebar:
    st.header("⚙️ Config")
    url = st.text_input("Server URL", "ws://localhost:9000")
    cid = st.text_input("Charger ID", "HF-001")
    
    if not st.session_state.sim["connected"]:
        if st.button("🔌 CONNECT", type="primary"):
            st.session_state.sim["stop_event"].clear()
            t = threading.Thread(target=thread_main, args=(url, cid, "Turbo-Sim", "UNIEV"), daemon=True)
            add_script_run_ctx(t)
            t.start()
            st.rerun()
    else:
        if st.button("❌ DISCONNECT", type="secondary"):
            st.session_state.sim["stop_event"].set()
            st.rerun()
    st.markdown(f"**Status:** `{st.session_state.sim['status']}`")

# MAIN
col1, col2 = st.columns([1, 1.5])

with col1:
    st.subheader("🎮 Controls")
    c_a, c_b = st.columns(2)
    if c_a.button("▶️ Start Charge", type="primary", disabled=not st.session_state.sim["connected"] or st.session_state.sim["is_charging"]):
        st.session_state.sim["cmd_queue"].append({"action": "START", "rfid": "TEST-CARD"})
        st.session_state.sim["current"] = 16.0 
        st.rerun()
    if c_b.button("⏹️ Stop & Bill", type="secondary", disabled=not st.session_state.sim["is_charging"]):
        st.session_state.sim["cmd_queue"].append({"action": "STOP"})
        st.rerun()

    st.divider()
    st.subheader("🛠️ Force Status")
    col_f1, col_f2, col_f3 = st.columns(3)
    if col_f1.button("🟢 Available"): st.session_state.sim["cmd_queue"].append({"action": "STATUS_CHANGE", "status": "Available"})
    if col_f2.button("🔴 Faulted"): st.session_state.sim["cmd_queue"].append({"action": "STATUS_CHANGE", "status": "Faulted"})
    if col_f3.button("⚪ Offline"): st.session_state.sim["cmd_queue"].append({"action": "STATUS_CHANGE", "status": "Unavailable"})

    st.divider()
    st.subheader("🚀 Injector")
    c_inj1, c_inj2 = st.columns(2)
    if c_inj1.button("🎲 +10 kWh", disabled=not st.session_state.sim["is_charging"]):
        st.session_state.sim["kwh_total"] += random.uniform(5.0, 15.0)
        st.session_state.sim["soc"] = min(99, st.session_state.sim["soc"] + 15)
        st.rerun()
    if c_inj2.button("🔋 Full Charge", disabled=not st.session_state.sim["is_charging"]):
        st.session_state.sim["kwh_total"] += 50.0
        st.session_state.sim["soc"] = 100
        st.rerun()

with col2:
    st.subheader("⚡ Live Metrics")
    m1, m2 = st.columns(2)
    m1.metric("Voltage (V)", f"{st.session_state.sim['voltage']}")
    m2.metric("Current (A)", f"{st.session_state.sim['current']}")
    m3, m4 = st.columns(2)
    m3.metric("Power (kW)", f"{st.session_state.sim['power']:.2f}")
    m4.metric("TOTAL ENERGY (kWh)", f"{st.session_state.sim['kwh_total']:.3f}")
    st.progress(int(st.session_state.sim["soc"]), text=f"SoC: {int(st.session_state.sim['soc'])}%")

    st.divider()
    if st.button("Clear Logs"): st.session_state["logs"] = []
    if st.session_state["logs"]:
        st.dataframe(pd.DataFrame(st.session_state["logs"]), use_container_width=True, hide_index=True, height=200)

time.sleep(1)
st.rerun()