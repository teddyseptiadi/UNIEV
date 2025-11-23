UNIEV Platform

Ringkasan
- Platform manajemen EV Charging yang mencakup OCPP Server, REST API, Dashboard CPO, OCPI, dan Simulator EV.
- Mendukung OCPP 1.6J, integrasi Supabase, dan alur pembayaran terpisah melalui EMSV.

Instalasi
- Pastikan Python 3.12 sudah terpasang.
- Jalankan `pip install -r requirements.txt`.
- Set environment Supabase bila tersedia: `SUPABASE_URL`, `SUPABASE_KEY`.

Menjalankan Layanan
- OCPP Server: `python backend/ocpp_server.py`
- API: `uvicorn backend.main_api:app --reload --port 8000`
- Simulator: `streamlit run simev.py`
- Dashboard CPO: `streamlit run dashboard_cpo.py`

Struktur
- `backend/ocpp_server.py`: Server OCPP 1.6J.
- `backend/main_api.py`: API manajemen CPO, EVSE, finansial, tiket.
- `backend/ocpi_service.py`: OCPI dasar.
- `backend/database.py`: Koneksi Supabase dengan fallback mock.
- `simev.py`: Simulator EV.
- `dashboard_cpo.py`: Dashboard operasional CPO.

Koneksi OCPP
- Server mendengarkan `ws://HOST:9000/{charger_id}` dengan subprotocol `ocpp1.6`.
- Client simulator mengirim BootNotification, Heartbeat, Status, Start/StopTransaction, MeterValues.

API Inti
- `GET /api/chargers` daftar charger.
- `POST /api/chargers` daftar charger baru.
- `PUT /api/chargers/{id}/status` paksa ubah status.
- `POST /api/client/remote-start` antrian perintah mulai.
- `POST /api/client/remote-stop` antrian perintah berhenti.
- `GET /api/analytics/dashboard` KPI ringkas.

Manajemen CPO (EMSV)
- `POST /api/cpo/register` daftar CPO.
- `POST /api/cpo/{cpo_id}/verify` verifikasi CPO.
- `GET /api/cpo/{cpo_id}/wallet` saldo virtual dan breakdown.
- `POST /api/cpo/{cpo_id}/settlements/request` ajukan settlement.

Tarif
- `POST /api/tariffs/templates` buat template.
- `GET /api/tariffs/templates` lihat template.
- `POST /api/tariffs/assign` pasang template ke charger.

Tiket
- `POST /api/tickets` buat tiket.
- `PUT /api/tickets/{ticket_id}` ubah status/assignee.

Pembayaran
- `POST /api/payments/providers` simpan konfigurasi gateway (xendit/midtrans, environment, api_key)
- `GET /api/payments/providers` daftar provider (api_key ditampilkan dengan masking)
- `POST /api/payments/intent` membuat payment intent (amount, deskripsi, cpo_id, charger_id, user_id)
- `GET /api/payments/{payment_id}` status pembayaran

EVSE Management
- `POST /api/evse/command` kirim perintah ke EVSE (REBOOT/UNLOCK/LOCK/UPDATE_FIRMWARE/UPDATE_CONFIG)
- `GET /api/reports/transactions.csv` ekspor CSV transaksi

API Keys
- `POST /api/apikeys` simpan API key
- `GET /api/apikeys` daftar API key (masking)

Catatan
- Bila Supabase tidak tersedia, sistem memakai mock client sehingga API tetap berjalan.