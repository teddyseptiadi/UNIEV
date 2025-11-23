import streamlit as st
import asyncio
import threading
import time
import pandas as pd
import logging
from datetime import datetime
import sys

# [FIX] Import Context Manager untuk Threading Streamlit
from streamlit.runtime.scriptrunner import add_script_run_ctx

# --- 1. PAGE CONFIG ---
st.set_page_config(page_title="UNIEV Pro Simulator", page_icon="⚡", layout="wide")

# --- 2. LOGGING CONFIG ---
if "logs" not in st.session_state:
    st.session_state["logs"] = []

def ui_log(message, type="INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = {"Time": timestamp, "Type": type, "Message": message}
    st.session_state["logs"].insert(0, entry)
    if len(st.session_state["logs"]) > 200:
        st.session_state["logs"].pop()

# --- 3. IMPORTS & PATCHING (SOLUSI ERROR ANDA) ---
try:
    import websockets
    from ocpp.v16 import ChargePoint as cp16
    from ocpp.v16 import call
    from ocpp.v16 import call_result # Penting untuk patch result juga
    from ocpp.v16.enums import RegistrationStatus, Action
    
    # [CRITICAL FIX] PATCHING MODUL 'call' (Request)
    # Ini memperbaiki error: module 'ocpp.v16.call' has no attribute 'BootNotificationPayload'
    if not hasattr(call, 'BootNotificationPayload'):
        # Mapping manual nama baru -> nama lama
        call.BootNotificationPayload = call.BootNotification
        call.HeartbeatPayload = call.Heartbeat
        call.StatusNotificationPayload = call.StatusNotification
        call.StartTransactionPayload = call.StartTransaction
        call.StopTransactionPayload = call.StopTransaction
        call.MeterValuesPayload = call.MeterValues
        print("⚠️ [SIM] Patched 'call' module for compatibility.")

    # [CRITICAL FIX] PATCHING MODUL 'call_result' (Response)
    if not hasattr(call_result, 'BootNotificationPayload'):
        call_result.BootNotificationPayload = call_result.BootNotification
        # (Tambahkan payload response lain jika perlu)
        print("⚠️ [SIM] Patched 'call_result' module for compatibility.")

except ImportError as e:
    st.error(f"CRITICAL ERROR: {e}. Run 'pip install ocpp websockets'")
    st.stop()

# --- 4. GLOBAL STATE ---
if "sim" not in st.session_state:
    st.session_state.sim = {
        "connected": False,
        "status": "Offline",
        "transaction_id": None,
        "is_charging": False,
        "voltage": 220,
        "current": 0.0,
        "power": 0.0,
        "kwh_total": 0.0,
        "soc": 20,
        "stop_event": threading.Event(),
        "cmd_queue": [] 
    }

# --- 5. OCPP LOGIC ---
class WebChargePoint(cp16):
    async def send_boot(self, model, vendor):
        # Sekarang aman karena sudah di-patch di atas
        req = call.BootNotificationPayload(
            charge_point_model=model,
            charge_point_vendor=vendor
        )
        return await self.call(req)

    async def send_status(self, status, err="NoError"):
        req = call.StatusNotificationPayload(
            connector_id=1, error_code=err, status=status
        )
        await self.call(req)

    async def start_txn(self, id_tag):
        req = call.StartTransactionPayload(
            connector_id=1, id_tag=id_tag, 
            meter_start=int(st.session_state.sim["kwh_total"] * 1000),
            timestamp=datetime.utcnow().isoformat()
        )
        res = await self.call(req)
        return res.transaction_id

    async def stop_txn(self, tx_id):
        req = call.StopTransactionPayload(
            transaction_id=tx_id, 
            meter_stop=int(st.session_state.sim["kwh_total"] * 1000),
            timestamp=datetime.utcnow().isoformat()
        )
        await self.call(req)

    async def send_meter(self, tx_id, v, i, p, soc):
        sampled_values = [
            {"value": str(v), "measurand": "Voltage", "unit": "V"},
            {"value": str(i), "measurand": "Current.Import", "unit": "A"},
            {"value": str(p * 1000), "measurand": "Power.Active.Import", "unit": "W"},
            {"value": str(int(soc)), "measurand": "SoC", "unit": "Percent"}
        ]
        req = call.MeterValuesPayload(
            connector_id=1, transaction_id=tx_id,
            meter_value=[{"timestamp": datetime.utcnow().isoformat(), "sampled_value": sampled_values}]
        )
        await self.call(req)

# --- 6. THREAD RUNNER ---
def thread_main(url, cp_id, model, vendor):
    async def async_loop():
        try:
            ui_log(f"Connecting to {url}/{cp_id}...", "SYS")
            async with websockets.connect(f"{url}/{cp_id}", subprotocols=['ocpp1.6']) as ws:
                cp = WebChargePoint(cp_id, ws)
                
                st.session_state.sim["connected"] = True
                st.session_state.sim["status"] = "Connected"
                ui_log("WebSocket Handshake OK", "SUCCESS")

                # BOOT
                try:
                    res = await cp.send_boot(model, vendor)
                    if res.status == RegistrationStatus.accepted:
                        ui_log("Boot Accepted!", "SUCCESS")
                        await cp.send_status("Available")
                        st.session_state.sim["status"] = "Available"
                        
                        # MAIN LOOP
                        while not st.session_state.sim["stop_event"].is_set():
                            
                            # Command Queue
                            if st.session_state.sim["cmd_queue"]:
                                cmd = st.session_state.sim["cmd_queue"].pop(0)
                                action = cmd['action']
                                
                                if action == "START":
                                    tx = await cp.start_txn(cmd['rfid'])
                                    st.session_state.sim["transaction_id"] = tx
                                    st.session_state.sim["is_charging"] = True
                                    st.session_state.sim["status"] = "Charging"
                                    await cp.send_status("Charging")
                                    ui_log(f"Charging Started (TX: {tx})", "INFO")
                                    
                                elif action == "STOP":
                                    if st.session_state.sim["transaction_id"]:
                                        await cp.stop_txn(st.session_state.sim["transaction_id"])
                                        st.session_state.sim["transaction_id"] = None
                                        st.session_state.sim["is_charging"] = False
                                        st.session_state.sim["status"] = "Available"
                                        st.session_state.sim["current"] = 0.0
                                        await cp.send_status("Available")
                                        ui_log("Charging Stopped", "INFO")
                                        
                                elif action == "STATUS_CHANGE":
                                    new_status = cmd['status']
                                    st.session_state.sim["status"] = new_status
                                    await cp.send_status(new_status, "InternalError" if new_status=="Faulted" else "NoError")
                                    ui_log(f"Status forced to {new_status}", "WARN")

                            # Metering Loop
                            if st.session_state.sim["is_charging"]:
                                v = st.session_state.sim["voltage"]
                                i = st.session_state.sim["current"]
                                p = (v * i) / 1000
                                st.session_state.sim["power"] = p
                                
                                st.session_state.sim["kwh_total"] += p * (1/3600) 
                                st.session_state.sim["soc"] = min(100, st.session_state.sim["soc"] + 0.05)
                                
                                try:
                                    await cp.send_meter(
                                        st.session_state.sim["transaction_id"], v, i, p, st.session_state.sim["soc"]
                                    )
                                except: pass
                            
                            await asyncio.sleep(1)
                    else:
                        ui_log("Boot Rejected!", "ERROR")
                except Exception as e_boot:
                    ui_log(f"Boot Logic Error: {e_boot}", "ERROR")

        except Exception as e:
            ui_log(f"Connection Error: {e}", "ERROR")
        finally:
            if "sim" in st.session_state:
                st.session_state.sim["connected"] = False
                st.session_state.sim["status"] = "Offline"
            ui_log("Disconnected.", "SYS")

    asyncio.run(async_loop())

# --- 7. UI LAYOUT ---
st.markdown("""
<style>
div[data-testid="metric-container"] {
    background-color: #262730;
    border: 1px solid #464b5c;
    padding: 10px;
    border-radius: 5px;
}
</style>
""", unsafe_allow_html=True)

st.title("🔌 UNIEV Pro Simulator")
st.caption("OCPP 1.6J Virtual Charge Point | Backend Connected")

# --- SIDEBAR CONFIG ---
with st.sidebar:
    st.header("⚙️ Configuration")
    url = st.text_input("Server URL", "ws://localhost:9000")
    cid = st.text_input("Charger ID", "WEB-SIM-001")
    vendor = st.text_input("Vendor", "UNIEV")
    model = st.text_input("Model", "Virtual-Pro")
    
    st.divider()
    
    if not st.session_state.sim["connected"]:
        if st.button("🔌 CONNECT", type="primary", use_container_width=True):
            st.session_state.sim["stop_event"].clear()
            t = threading.Thread(target=thread_main, args=(url, cid, model, vendor), daemon=True)
            add_script_run_ctx(t)
            t.start()
            st.rerun()
    else:
        if st.button("❌ DISCONNECT", type="secondary", use_container_width=True):
            st.session_state.sim["stop_event"].set()
            st.rerun()
            
    st.markdown(f"**Status:** `{st.session_state.sim['status']}`")

# --- MAIN DASHBOARD ---
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("🎮 Controls")
    
    with st.container(border=True):
        st.markdown("#### Transaction")
        rfid = st.text_input("RFID Tag", "CARD-12345")
        
        c_a, c_b = st.columns(2)
        with c_a:
            start_btn = st.button("▶️ Start", type="primary", use_container_width=True,
                                disabled=not st.session_state.sim["connected"] or st.session_state.sim["is_charging"])
        with c_b:
            stop_btn = st.button("⏹️ Stop", type="secondary", use_container_width=True,
                               disabled=not st.session_state.sim["is_charging"])
            
        if start_btn:
            st.session_state.sim["cmd_queue"].append({"action": "START", "rfid": rfid})
            st.session_state.sim["current"] = 16.0 
            st.rerun()
            
        if stop_btn:
            st.session_state.sim["cmd_queue"].append({"action": "STOP"})
            st.rerun()

    with st.container(border=True):
        st.markdown("#### Force Status")
        c_s1, c_s2 = st.columns(2)
        with c_s1:
            if st.button("Available", use_container_width=True):
                st.session_state.sim["cmd_queue"].append({"action": "STATUS_CHANGE", "status": "Available"})
        with c_s2:
            if st.button("Faulted ⚠️", use_container_width=True):
                st.session_state.sim["cmd_queue"].append({"action": "STATUS_CHANGE", "status": "Faulted"})
        
        if st.button("Unavailable / Offline", use_container_width=True):
             st.session_state.sim["cmd_queue"].append({"action": "STATUS_CHANGE", "status": "Unavailable"})

with col2:
    st.subheader("⚡ Electrical & Metrics")
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Voltage", f"{st.session_state.sim['voltage']} V")
    m2.metric("Current", f"{st.session_state.sim['current']} A")
    m3.metric("Power", f"{st.session_state.sim['power']:.2f} kW")
    m4.metric("Energy", f"{st.session_state.sim['kwh_total']:.3f} kWh")
    
    st.write("---")
    vol_val = st.slider("Voltage Input (V)", 200, 250, 220, key="slider_v")
    st.session_state.sim["voltage"] = vol_val
    
    cur_val = st.slider("Load Current (A)", 0.0, 63.0, st.session_state.sim["current"], key="slider_a")
    st.session_state.sim["current"] = cur_val
    
    soc_val = st.progress(int(st.session_state.sim["soc"]), text=f"Battery SoC: {int(st.session_state.sim['soc'])}%")

# --- LOGS SECTION ---
st.divider()
col_log_head, col_log_btn = st.columns([4, 1])
col_log_head.subheader("📜 Communication Logs")
if col_log_btn.button("Clear Logs"):
    st.session_state["logs"] = []
    st.rerun()

if st.session_state["logs"]:
    df = pd.DataFrame(st.session_state["logs"])
    st.dataframe(df, use_container_width=True, hide_index=True, height=250)
else:
    st.info("No logs yet. Connect to backend to start.")

# --- AUTO REFRESH ---
if st.session_state.sim["connected"]:
    time.sleep(1)
    st.rerun()