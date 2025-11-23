Dokumentasi Platform UNIEV/EMSV

Overview
- EMSV: Platform pusat multi-tenant untuk administrasi CPO, pembayaran, settlement, monitoring nasional, compliance.
- CPO Dashboard: Operasional stasiun, EVSE management, sesi, user terbatas, ticketing, laporan.
- EV User App: Pencarian stasiun, mulai charging, pembayaran, sesi realtime, notifikasi, support.

1. EMSV (Electric Mobility Service Vendor)
- Manajemen CPO
  - Registrasi, verifikasi, status onboarding.
  - Konfigurasi bagi hasil.
- CPO Wallet & Settlement
  - Virtual balance per CPO, breakdown pendapatan.
  - Laporan harian/mingguan/bulanan, export.
  - Permintaan settlement, log.
- National Monitoring (NOC)
  - Status EVSE & connector, online/offline, available/charging/suspended/faulted.
  - Load monitoring, sesi aktif, health metrics.
  - Peta lokasi EVSE.
- Tarif & Template
  - Flat, per kWh, time-based (idle fee), peak/off-peak.
  - Default per CPO dan khusus stasiun.
- Compliance
  - OCPP versioning, OCPI endpoints, API key management, rate limiting, audit log.

2. Dashboard CPO Management
- Monitoring Stasiun
  - Profil stasiun, status charger, tegangan, arus, power, status konektor, temperatur, heartbeat, error code, rincian modul.
- EVSE Management
  - Tambah EVSE, update hardware/firmware, reboot, unlock connector, lock/unlock, diagnostics, konfigurasi via OCPP.
- Session Monitoring
  - Detail waktu, energi, biaya, status.
- User Access (Terbatas)
  - Nama, kontak opsional, jenis mobil, kapasitas baterai, riwayat pada stasiun CPO terkait.
- Ticketing & Support
  - Jenis tiket, assign teknisi, update status, prioritas, upload media, riwayat penanganan.
- Financial Report
  - Total sesi, energi, revenue kotor/bersih, tarif, settlement history.

3. EV User Mobile App
- Akun & KYC
  - Login, verifikasi opsional, profil kendaraan, riwayat.
- Finding Stations
  - Peta, filter AC/DC, daya, harga, konektor, status real-time, navigasi.
- Start Charging (OCPP)
  - Scan QR, start dari app, plug-and-charge bila didukung.
  - Sesi realtime: kWh, daya, durasi, biaya, status.
- Pembayaran
  - eWallet, QRIS, kartu kredit, debit, VA.
  - Auto-charge saldo, refund otomatis, invoice PDF.
- Notifikasi
  - Mulai/selesai charging, idle fee, sukses pembayaran, tiket.
- Support
  - Buat tiket, upload media, chat, status tiket.

4. Pembayaran
- Gateway: Xendit, Midtrans.
- Konfigurasi per CPO: provider, environment, api_key.
- API:
  - POST /api/payments/providers
  - GET  /api/payments/providers
  - POST /api/payments/intent
  - GET  /api/payments/{payment_id}
- Keamanan: api_key dimask saat ditampilkan.

API Referensi (Ringkas)
- CPO
  - POST /api/cpo/register
  - POST /api/cpo/{cpo_id}/verify
  - GET  /api/cpo/{cpo_id}/wallet
  - POST /api/cpo/{cpo_id}/settlements/request
- NOC
  - GET  /api/noc/evse
- Tarif
  - POST /api/tariffs/templates
  - GET  /api/tariffs/templates
  - POST /api/tariffs/assign
- Tiket
  - POST /api/tickets
  - PUT  /api/tickets/{ticket_id}
- Charger
  - GET  /api/chargers
  - POST /api/chargers
  - PUT  /api/chargers/{id}/status
- Perintah Pengguna
  - POST /api/client/remote-start
  - POST /api/client/remote-stop
- Analytics
  - GET  /api/analytics/dashboard
  - GET  /api/analytics/utilization

Operasional
- Jalankan OCPP server, API, Dashboard, dan Simulator sesuai README.
- Supabase opsional; tanpa Supabase, mock client aktif agar API tetap berjalan.

Catatan Implementasi
- Endpoint diimplementasi minimal untuk memvalidasi alur bisnis; perlu penambahan schema DB dan integrasi gateway pembayaran di tahap berikut.