# backend/main_api.py
from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
import uvicorn
from datetime import datetime
from datetime import timedelta


# --- [MODULE 2.3] MANUAL INVOICING ---
class ManualInvoice(BaseModel):
    charger_id: str
    description: str
    amount: float

@app.post("/api/billing/manual-invoice")
def create_manual_invoice(inv: ManualInvoice):
    """Membuat tagihan manual (misal: denda kerusakan alat oleh user)"""
    if not supabase: return {"error": "DB Offline"}
    
    data = {
        "charger_id": inv.charger_id,
        "total_amount": inv.amount,
        "payment_status": "PENDING",
        "status": "MANUAL_CHARGE",
        "stop_time": datetime.utcnow().isoformat() # timestamp invoice dibuat
        # note: kolom lain bisa null atau diisi deskripsi jika tabel mendukung
    }
    try:
        supabase.table("invoices").insert(data).execute()
        return {"status": "Success", "msg": f"Manual Invoice Rp {inv.amount} Created"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- [MODULE 2.1] FAULT LOGS & NOTIFICATIONS ---
@app.get("/api/operations/fault-logs")
def get_fault_logs():
    """Melihat daftar kerusakan alat (Fault Logs)"""
    if not supabase: return []
    # Ambil tiket yang statusnya OPEN
    res = supabase.table("maintenance_tickets").select("*").eq("status", "OPEN").execute()
    return res.data

@app.post("/api/operations/notify-technician/{ticket_id}")
def notify_technician(ticket_id: str):
    """(Simulasi) Mengirim Notifikasi WA/Email ke Teknisi"""
    # Di real world, integrasi ke Twilio/WhatsApp API disini
    print(f"[NOTIF] Sending WhatsApp to Field Engineer for Ticket {ticket_id}...")
    return {"status": "Sent", "channel": "WhatsApp"}

# --- [MODULE 2.4] REAL ANALYTICS (UPTIME) ---
@app.get("/api/analytics/dashboard")
def get_dashboard_stats():
    if not supabase: return {"error": "DB Offline"}
        
    # ... (Kode energy & revenue yang lama tetap sama) ...
    
    # [UPDATE] LOGIC UPTIME SCORE REAL
    # Rumus: (Jumlah Charger Available+Charging) / (Total Charger) * 100
    all_chargers = supabase.table("chargers").select("status", count="exact").execute()
    total_units = all_chargers.count
    
    # Charger yang 'Sehat' adalah yang tidak Faulted dan tidak Offline
    healthy_chargers = supabase.table("chargers").select("status", count="exact")\
        .neq("status", "Faulted").neq("status", "Offline").execute()
    healthy_count = healthy_chargers.count
    
    if total_units > 0:
        uptime = (healthy_count / total_units) * 100
    else:
        uptime = 0
        
    return {
        # ... (return lain sama) ...
        "uptime_score": f"{uptime:.1f}%", 
        "total_units": total_units,
        "healthy_units": healthy_count
    }

# --- UNIVERSAL IMPORT ---
try:
    from backend import config
    from backend.database import supabase
except ImportError:
    import config
    from database import supabase

app = FastAPI(
    title="UNIEV Management API",
    description="Backend Control Panel untuk CPO. Gunakan ini untuk memanipulasi data tanpa Simulator.",
    version="1.0.0"
)

# --- DATA MODELS (Untuk Validasi Input) ---
class ChargerCreate(BaseModel):
    charger_id: str
    vendor: str = "Generic"
    model: str = "AC-7kW"
    location_name: str = "Unknown Location"

class StatusUpdate(BaseModel):
    status: str  # Available, Charging, Faulted, Offline

# --- ENDPOINTS ---

@app.get("/")
def root():
    return {"status": "Online", "system": "UNIEV Core Backend", "docs_url": f"http://localhost:{config.PORT_API}/docs"}

@app.get("/api/chargers")
def get_all_chargers():
    """Melihat semua charger yang terdaftar di sistem"""
    if not supabase:
        return {"error": "Database not connected"}
    res = supabase.table("chargers").select("*").order("charger_id").execute()
    return res.data

@app.post("/api/chargers")
def register_charger(charger: ChargerCreate):
    """(Admin) Mendaftarkan Charger Baru secara Manual"""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database Offline")
    
    data = {
        "charger_id": charger.charger_id,
        "vendor": charger.vendor,
        "model": charger.model,
        "location_name": charger.location_name,
        "status": "Available",
        "last_heartbeat": datetime.utcnow().isoformat()
    }
    try:
        supabase.table("chargers").upsert(data).execute()
        return {"message": "Charger Registered", "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/api/chargers/{charger_id}/status")
def force_status_change(charger_id: str, state: StatusUpdate):
    """(Simulation) Memaksa ubah status charger (misal: pura-pura rusak/charging)"""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database Offline")
    
    # Validasi status
    valid_status = ["Available", "Charging", "Faulted", "Offline", "Finishing"]
    if state.status not in valid_status:
        raise HTTPException(status_code=400, detail=f"Status harus salah satu dari: {valid_status}")

    try:
        supabase.table("chargers").update({"status": state.status}).eq("charger_id", charger_id).execute()
        return {"message": f"Charger {charger_id} status changed to {state.status}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/chargers/{charger_id}/reset")
def remote_reset(charger_id: str):
    """(Command) Mengirim perintah Reset ke mesin (Mockup)"""
    # Di masa depan, ini akan mengirim perintah WebSocket ke ocpp_server.py
    print(f"[API] Sending RESET Command to {charger_id}...")
    return {"message": "Reset Command Queued", "target": charger_id}

if __name__ == "__main__":
    print(f"--- UNIEV API SERVER STARTED ON PORT {config.PORT_API} ---")
    # Gunakan port dari config (8000)
    uvicorn.run(app, host=config.HOST, port=config.PORT_API, log_level="info")

# Tambahkan di backend/main_api.py

@app.get("/api/analytics/dashboard")
def get_dashboard_stats():
    """(Module 2.4) Analytics Summary untuk Dashboard CPO"""
    if not supabase:
        return {"error": "DB Offline"}
        
    # 1. Total Energy Delivered
    # Query SQL sum(total_kwh)
    res_energy = supabase.table("transactions").select("total_kwh").execute()
    total_energy = sum([x['total_kwh'] for x in res_energy.data if x['total_kwh']])
    
    # 2. Total Revenue
    res_rev = supabase.table("transactions").select("total_amount").execute()
    total_revenue = sum([x['total_amount'] for x in res_rev.data if x['total_amount']])
    
    # 3. Carbon Offset
    res_carbon = supabase.table("transactions").select("carbon_saved_kg").execute()
    total_carbon = sum([x['carbon_saved_kg'] for x in res_carbon.data if x['carbon_saved_kg']])
    
    # 4. Active Chargers
    res_active = supabase.table("chargers").select("*", count="exact").eq("status", "Charging").execute()
    active_count = res_active.count
    
    return {
        "energy_delivered_kwh": round(total_energy, 2),
        "total_revenue_idr": round(total_revenue, 2),
        "carbon_offset_kg": round(total_carbon, 2),
        "active_sessions": active_count,
        "uptime_score": "99.8%" # Mockup logic, realnya hitung log heartbeat
    }

@app.get("/api/analytics/utilization")
def get_utilization_chart():
    """Data untuk grafik penggunaan per jam (Mockup Structure)"""
    # Nanti diisi logic aggregation by hour
    return {
        "labels": ["08:00", "10:00", "12:00", "14:00", "16:00"],
        "data": [5, 12, 20, 18, 25]
    }