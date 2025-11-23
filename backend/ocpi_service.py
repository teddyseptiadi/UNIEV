# backend/ocpi_service.py
from fastapi import FastAPI
import uvicorn

# --- UNIVERSAL IMPORT BLOCK ---
try:
    from backend import config
except ImportError:
    import config
# -----------------------------

app = FastAPI(title="UNIEV OCPI Roaming Node")

@app.get("/ocpi/versions")
def versions():
    return {"versions": [{"version": "2.2.1", "url": "http://localhost/ocpi/2.2.1"}]}

if __name__ == "__main__":
    print(f"--- UNIEV OCPI ROAMING NODE STARTED ON PORT {config.PORT_OCPI} ---")
    uvicorn.run(app, host=config.HOST, port=config.PORT_OCPI, log_level="info")