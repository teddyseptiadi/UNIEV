# backend/main_api.py
from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel, Field
import uvicorn
import traceback
import sys
from datetime import datetime, timedelta

# --- UNIVERSAL IMPORT (Config & Database) ---
try:
    from backend import config
    from backend.database import supabase
except ImportError:
    try:
        import config
        from database import supabase
    except Exception as e:
        print(f"CRITICAL API IMPORT ERROR: {e}", file=sys.stderr)
        config = None
        supabase = None

# --- CONFIGURATION RESOLUTION (Pastikan port 8088 atau 8000) ---
API_HOST = getattr(config, "HOST", "0.0.0.0") if config else "0.0.0.0"
# Kita gunakan PORT_API dari config, yang seharusnya 8088 (sesuai fix terakhir)
API_PORT = getattr(config, "PORT_API", 8000) if config else 8000 

# --- 1. DATA MODELS (Input Validation) ---
class ChargerCreate(BaseModel):
    charger_id: str = Field(..., example="NEW-CH-005")
    vendor: str = Field("Generic", example="Tesla")
    model: str = Field("AC-7kW", example="Model 3")
    location_name: str = Field("Unknown Location", example="Mall A Parking Lot")

class StatusUpdate(BaseModel):
    status: str = Field(..., example="Charging", description="Status yang valid: Available, Charging, Faulted, Offline")

class ManualInvoice(BaseModel):
    charger_id: str = Field(..., example="SIM-001")
    description: str = Field(..., example="Denda kabel rusak")
    amount: float = Field(..., example=150000.0)

# --- 2. FASTAPI APP INITIALIZATION ---
app = FastAPI(
    title="UNIEV Management API",
    description="Backend Control Panel & Data Source untuk Frontend (Apps/Dashboard).",
    version="1.0.0"
)

# --- 3. CORE ENDPOINTS (Module 1.2 & 2.1) ---

@app.get("/")
def root():
    db_status = "Connected" if supabase else "Offline (CRASHED)"
    return {"status": "Online", "service": "UNIEV Core Backend", "db_status": db_status, "docs_url": f"http://localhost:{API_PORT}/docs"}

@app.get("/api/chargers")
def get_all_chargers():
    """Melihat semua charger yang terdaftar (Untuk Map/List)"""
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
    """(Simulation) Memaksa ubah status charger (digunakan untuk reset)"""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database Offline")
    
    valid_status = ["Available", "Charging", "Faulted", "Offline", "Finishing"]
    if state.status not in valid_status:
        raise HTTPException(status_code=400, detail=f"Status harus salah satu dari: {valid_status}")

    try:
        supabase.table("chargers").update({"status": state.status}).eq("charger_id", charger_id).execute()
        return {"message": f"Charger {charger_id} status changed to {state.status}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- 4. COMMAND & USER INTERACTION ENDPOINTS (Module 2.1) ---

@app.post("/api/client/remote-start")
def user_remote_start(charger_id: str, user_id: str = Body(..., embed=True, example="USR-8821")):
    """
    (Frontend User App) Menerima permintaan START CHARGING dari pengguna.
    Menyimpan ke tabel command queue untuk dibaca oleh OCPP Server.
    """
    if not supabase: raise HTTPException(status_code=503, detail="Database Offline")
    
    try:
        data = {
            "charger_id": charger_id, 
            "user_id": user_id, 
            "action": "REMOTE_START", 
            "status": "PENDING"
        }
        supabase.table("charging_commands").insert(data).execute()
        return {"status": "Accepted", "message": "Command queued. Waiting for charger response."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to queue command: {str(e)}")

@app.post("/api/client/remote-stop")
def user_remote_stop(charger_id: str, user_id: str = Body(..., embed=True, example="USR-8821")):
    """(Frontend User App) Menerima permintaan STOP CHARGING."""
    if not supabase: raise HTTPException(status_code=503, detail="Database Offline")
    
    try:
        data = {
            "charger_id": charger_id, 
            "user_id": user_id, 
            "action": "REMOTE_STOP", 
            "status": "PENDING"
        }
        supabase.table("charging_commands").insert(data).execute()
        return {"status": "Accepted", "message": "Stop command queued."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to queue command: {str(e)}")


# --- 5. FINANCIAL & MAINTENANCE ENDPOINTS (Module 2.3 & 2.1) ---

@app.post("/api/billing/manual-invoice")
def create_manual_invoice(inv: ManualInvoice):
    """(Admin) Membuat tagihan manual (misal: denda, biaya tambahan)"""
    if not supabase: return {"error": "DB Offline"}
    
    data = {
        "charger_id": inv.charger_id,
        "total_amount": inv.amount,
        "payment_status": "PENDING",
        "status": "MANUAL_CHARGE",
        "stop_time": datetime.utcnow().isoformat() 
    }
    try:
        supabase.table("invoices").insert(data).execute() # Gunakan tabel 'invoices' atau 'transactions' tergantung skema Anda
        return {"status": "Success", "msg": f"Manual Invoice Rp {inv.amount} Created"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/operations/fault-logs")
def get_fault_logs():
    """(Dashboard) Melihat daftar tiket kerusakan yang masih terbuka"""
    if not supabase: return []
    res = supabase.table("maintenance_tickets").select("*").eq("status", "OPEN").execute()
    return res.data

# --- 6. ANALYTICS & REPORTING ENDPOINTS (Module 2.4) ---

@app.get("/api/analytics/dashboard")
def get_dashboard_stats():
    """Analytics Summary untuk Dashboard CPO (KPIs)"""
    if not supabase: return {"error": "DB Offline"}
        
    # [NOTE] Ini adalah contoh agregasi yang lambat. Di production, gunakan View SQL.
    
    res_energy = supabase.table("transactions").select("total_kwh").execute()
    total_energy = sum([x['total_kwh'] for x in res_energy.data if x['total_kwh']])
    
    res_rev = supabase.table("transactions").select("total_amount").execute()
    total_revenue = sum([x['total_amount'] for x in res_rev.data if x['total_amount']])
    
    # Uptime Logic
    all_chargers = supabase.table("chargers").select("status", count="exact").execute()
    total_units = all_chargers.count
    healthy_chargers = supabase.table("chargers").select("status", count="exact").neq("status", "Faulted").neq("status", "Offline").execute()
    healthy_count = healthy_chargers.count
    uptime = (healthy_count / total_units) * 100 if total_units > 0 else 0
    
    return {
        "energy_delivered_kwh": round(total_energy, 2),
        "total_revenue_idr": round(total_revenue, 2),
        "active_sessions": healthy_chargers.count,
        "uptime_score": f"{uptime:.1f}%",
        "total_units": total_units
    }

@app.get("/api/analytics/utilization")
def get_utilization_chart():
    """Data untuk grafik penggunaan per jam (Mockup Structure)"""
    # Placeholder for complex time series analysis
    return {
        "labels": ["08:00", "10:00", "12:00", "14:00", "16:00"],
        "data": [5, 12, 20, 18, 25]
    }


# --- 7. UVICORN RUNNER ---
if __name__ == "__main__":
    try:
        uvicorn.run(
            app, 
            host=API_HOST, 
            port=API_PORT, 
            log_level="info"
        )
    except Exception as e:
        print(f"CRASH: Uvicorn API failed to start on port {API_PORT}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)