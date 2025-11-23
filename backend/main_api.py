# backend/main_api.py
from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel, Field
from typing import Literal
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

class CPOCreate(BaseModel):
    cpo_id: str = Field(..., example="CPO-001")
    name: str
    npwp: str | None = None
    siup: str | None = None
    address: str | None = None
    pic_name: str | None = None
    pic_phone: str | None = None
    profit_sharing_percent: float = 0.0

class SettlementRequest(BaseModel):
    amount: float
    method: str = "BankTransfer"
    notes: str | None = None

class TariffTemplateCreate(BaseModel):
    template_id: str
    name: str
    type: str = "per_kwh"
    price_per_kwh: float = 0.0
    idle_fee_per_min: float = 0.0
    peak_hours: list[str] | None = None
    offpeak_multiplier: float = 1.0
    cpo_id: str | None = None

class TicketCreate(BaseModel):
    ticket_id: str
    cpo_id: str
    charger_id: str
    category: str
    description: str
    priority: str = "Normal"
    status: str = "OPEN"

class PaymentProviderConfig(BaseModel):
    provider: Literal['xendit','midtrans']
    environment: Literal['development','production']
    api_key: str
    name: str | None = None
    cpo_id: str | None = None

class PaymentIntentRequest(BaseModel):
    provider: Literal['xendit','midtrans']
    amount: float
    currency: str = "IDR"
    description: str
    cpo_id: str | None = None
    charger_id: str | None = None
    user_id: str | None = None

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

@app.post("/api/cpo/register")
def cpo_register(cpo: CPOCreate):
    if not supabase: raise HTTPException(status_code=503, detail="Database Offline")
    data = cpo.dict()
    data.update({"status": "Pending", "created_at": datetime.utcnow().isoformat()})
    try:
        supabase.table("cpos").upsert(data).execute()
        return {"message": "CPO Registered", "data": data}
    except Exception:
        return {"message": "CPO Registered (soft)", "data": data}

@app.post("/api/cpo/{cpo_id}/verify")
def cpo_verify(cpo_id: str):
    if not supabase: raise HTTPException(status_code=503, detail="Database Offline")
    try:
        supabase.table("cpos").update({"status": "Verified", "verified_at": datetime.utcnow().isoformat()}).eq("cpo_id", cpo_id).execute()
        return {"message": "CPO Verified", "cpo_id": cpo_id}
    except Exception:
        return {"message": "CPO Verified (soft)", "cpo_id": cpo_id}

@app.get("/api/cpo/{cpo_id}/wallet")
def cpo_wallet(cpo_id: str):
    if not supabase: return {"balance": 0, "breakdown": {"gross": 0, "platform_fee": 0, "pg_fee": 0, "net": 0}}
    try:
        tx = supabase.table("transactions").select("total_amount, platform_fee, pg_fee").eq("cpo_id", cpo_id).execute().data
        gross = sum([t.get("total_amount", 0) or 0 for t in tx])
        platform_fee = sum([t.get("platform_fee", 0) or 0 for t in tx])
        pg_fee = sum([t.get("pg_fee", 0) or 0 for t in tx])
        net = gross - platform_fee - pg_fee
        return {"balance": net, "breakdown": {"gross": gross, "platform_fee": platform_fee, "pg_fee": pg_fee, "net": net}}
    except Exception:
        return {"balance": 0, "breakdown": {"gross": 0, "platform_fee": 0, "pg_fee": 0, "net": 0}}

@app.post("/api/cpo/{cpo_id}/settlements/request")
def cpo_settlement_request(cpo_id: str, req: SettlementRequest):
    if not supabase: raise HTTPException(status_code=503, detail="Database Offline")
    data = {"cpo_id": cpo_id, "amount": req.amount, "method": req.method, "notes": req.notes, "status": "PENDING", "requested_at": datetime.utcnow().isoformat()}
    try:
        supabase.table("settlements").insert(data).execute()
        return {"message": "Settlement Requested", "data": data}
    except Exception:
        return {"message": "Settlement Requested (soft)", "data": data}

@app.get("/api/noc/evse")
def noc_evse():
    if not supabase: return {"evse": []}
    try:
        chargers = supabase.table("chargers").select("*").execute().data
        return {"evse": chargers}
    except Exception:
        return {"evse": []}

@app.post("/api/tariffs/templates")
def create_tariff_template(t: TariffTemplateCreate):
    if not supabase: raise HTTPException(status_code=503, detail="Database Offline")
    try:
        supabase.table("tariff_templates").upsert(t.dict()).execute()
        return {"message": "Tariff Template Saved"}
    except Exception:
        return {"message": "Tariff Template Saved (soft)"}

@app.get("/api/tariffs/templates")
def list_tariff_templates(cpo_id: str | None = None):
    if not supabase: return []
    q = supabase.table("tariff_templates").select("*")
    if cpo_id: q = q.eq("cpo_id", cpo_id)
    return q.execute().data

@app.post("/api/tariffs/assign")
def assign_tariff(charger_id: str, template_id: str):
    if not supabase: raise HTTPException(status_code=503, detail="Database Offline")
    try:
        supabase.table("chargers").update({"tariff_template_id": template_id}).eq("charger_id", charger_id).execute()
        return {"message": "Tariff assigned", "charger_id": charger_id, "template_id": template_id}
    except Exception:
        return {"message": "Tariff assigned (soft)", "charger_id": charger_id, "template_id": template_id}

@app.post("/api/tickets")
def create_ticket(t: TicketCreate):
    if not supabase: raise HTTPException(status_code=503, detail="Database Offline")
    data = t.dict()
    data.update({"created_at": datetime.utcnow().isoformat()})
    try:
        supabase.table("tickets").insert(data).execute()
        return {"message": "Ticket Created"}
    except Exception:
        return {"message": "Ticket Created (soft)"}

@app.put("/api/tickets/{ticket_id}")
def update_ticket(ticket_id: str, status: str, assignee: str | None = None):
    if not supabase: raise HTTPException(status_code=503, detail="Database Offline")
    try:
        supabase.table("tickets").update({"status": status, "assignee": assignee}).eq("ticket_id", ticket_id).execute()
        return {"message": "Ticket Updated"}
    except Exception:
        return {"message": "Ticket Updated (soft)"}

def _mask_key(k: str) -> str:
    if not k: return ""
    return k[:4] + "****" + k[-4:]

@app.post("/api/payments/providers")
def upsert_payment_provider(cfg: PaymentProviderConfig):
    data = cfg.dict()
    if not supabase:
        return {"message": "Provider Saved (soft)", "provider": data | {"api_key": _mask_key(cfg.api_key)}}
    try:
        supabase.table("payment_providers").upsert(data).execute()
        return {"message": "Provider Saved", "provider": data | {"api_key": _mask_key(cfg.api_key)}}
    except Exception:
        return {"message": "Provider Saved (soft)", "provider": data | {"api_key": _mask_key(cfg.api_key)}}

@app.get("/api/payments/providers")
def list_payment_providers(cpo_id: str | None = None):
    if not supabase: return []
    try:
        q = supabase.table("payment_providers").select("provider, environment, name, cpo_id, api_key")
        if cpo_id: q = q.eq("cpo_id", cpo_id)
        res = q.execute().data
        for r in res:
            r["api_key"] = _mask_key(r.get("api_key",""))
        return res
    except Exception:
        return []

@app.post("/api/payments/intent")
def create_payment_intent(req: PaymentIntentRequest):
    pid = f"PAY-{int(datetime.utcnow().timestamp())}"
    link = f"https://pay.dev/uniev/{pid}" if req.provider == "xendit" else f"https://pay.dev/midtrans/{pid}"
    data = {
        "payment_id": pid,
        "provider": req.provider,
        "amount": req.amount,
        "currency": req.currency,
        "description": req.description,
        "payment_link": link,
        "status": "PENDING",
        "created_at": datetime.utcnow().isoformat(),
        "cpo_id": req.cpo_id,
        "charger_id": req.charger_id,
        "user_id": req.user_id,
    }
    if not supabase:
        return {"message": "Payment Intent Created (soft)", "data": data}
    try:
        supabase.table("payments").insert(data).execute()
        return {"message": "Payment Intent Created", "data": data}
    except Exception:
        return {"message": "Payment Intent Created (soft)", "data": data}

@app.get("/api/payments/{payment_id}")
def get_payment_status(payment_id: str):
    if not supabase:
        return {"payment_id": payment_id, "status": "PENDING"}
    try:
        res = supabase.table("payments").select("*").eq("payment_id", payment_id).limit(1).execute().data
        return res[0] if res else {"payment_id": payment_id, "status": "UNKNOWN"}
    except Exception:
        return {"payment_id": payment_id, "status": "PENDING"}

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

@app.post("/api/evse/command")
def evse_command(charger_id: str, action: Literal["REBOOT","UNLOCK","LOCK","UPDATE_FIRMWARE","UPDATE_CONFIG"], payload: dict | None = None):
    if not supabase: raise HTTPException(status_code=503, detail="Database Offline")
    data = {"charger_id": charger_id, "action": action, "status": "PENDING", "payload": payload, "ts": datetime.utcnow().isoformat()}
    try:
        supabase.table("charging_commands").insert(data).execute()
        return {"message": "Command queued", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reports/transactions.csv")
def export_transactions_csv():
    if not supabase:
        return ""
    try:
        res = supabase.table("transactions").select("*").order("stop_time", desc=True).execute().data
        import csv, io
        buf = io.StringIO()
        fields = list(res[0].keys()) if res else ["transaction_id","charger_id","stop_time","total_kwh","total_amount","status","payment_status"]
        w = csv.DictWriter(buf, fieldnames=fields)
        w.writeheader()
        for r in res:
            w.writerow(r)
        return buf.getvalue()
    except Exception:
        return ""

class APIKeyCreate(BaseModel):
    name: str
    key: str
    status: str = "active"
    cpo_id: str | None = None

@app.post("/api/apikeys")
def create_api_key(payload: APIKeyCreate):
    if not supabase:
        return {"message": "API key saved (soft)", "data": payload.dict()}
    try:
        supabase.table("api_keys").upsert(payload.dict()).execute()
        return {"message": "API key saved"}
    except Exception:
        return {"message": "API key saved (soft)"}

@app.get("/api/apikeys")
def list_api_keys(cpo_id: str | None = None):
    if not supabase: return []
    q = supabase.table("api_keys").select("name,key,status,cpo_id,created_at")
    if cpo_id: q = q.eq("cpo_id", cpo_id)
    try:
        items = q.execute().data
        for i in items:
            k = i.get("key", "")
            i["key"] = (k[:4] + "****" + k[-4:]) if k else ""
        return items
    except Exception:
        return []


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