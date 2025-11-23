import streamlit as st
import pandas as pd
import plotly.express as px
import time
from datetime import datetime
import numpy as np
import requests

# --- 1. PAGE CONFIG ---
st.set_page_config(
    page_title="UNIEV CPO Command Center",
    page_icon="🏢", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for professional dark-mode friendly table
st.markdown("""
<style>
    [data-testid="stMetricValue"] { font-size: 24px; font-weight: 700; }
    .st-emotion-cache-1r6slb0 { background-color: #1E1E1E; padding: 15px; border-radius: 8px; }
    .main-header { color: #2563EB; font-weight: 800; }
    /* Styling untuk tabel */
    .stDataFrame { border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
    /* Warna Status */
    .status-charging { color: #636EFA; font-weight: bold; }
    .status-idle { color: #00CC96; }
</style>
""", unsafe_allow_html=True)

# --- 2. DATABASE CONNECTION ---
try:
    from backend.database import supabase
except ImportError:
    st.error("Backend module not found. Pastikan menjalankan dari root folder.")
    st.stop()

if not supabase:
    st.warning("Database connection not initialized.")
    st.stop()

# --- 3. DATA FUNCTIONS (Centralized Fetching) ---

def get_summary_metrics():
    """Mengambil total KPI: Energy, Revenue, Uptime, Faults."""
    try:
        res_trans = supabase.table("transactions").select("total_kwh, total_amount, carbon_saved_kg").execute()
        df_trans = pd.DataFrame(res_trans.data)
        
        res_chargers = supabase.table("chargers").select("status", count="exact").execute()
        df_chargers_status = pd.DataFrame(supabase.table("chargers").select("status").execute().data)
        res_faults = supabase.table("maintenance_tickets").select("*", count="exact").eq("status", "OPEN").execute()

        total_units = res_chargers.count
        
        if df_trans.empty:
            energy, rev, carbon = 0, 0, 0
        else:
            energy = df_trans['total_kwh'].sum()
            rev = df_trans['total_amount'].sum()
            carbon = df_trans['carbon_saved_kg'].sum()
        
        healthy_count = len(df_chargers_status[~df_chargers_status['status'].isin(['Faulted', 'Offline'])])
        uptime_score = (healthy_count / total_units) * 100 if total_units > 0 else 0
        
        return (energy, rev, carbon, len(df_trans), f"{uptime_score:,.1f}%", res_faults.count, total_units)
    except Exception as e:
        return 0, 0, 0, 0, '0%', 0, 0

def get_transactions_history():
    """Riwayat transaksi."""
    try:
        res = supabase.table("transactions").select("*").order("stop_time", desc=True).limit(50).execute()
        df = pd.DataFrame(res.data)
        if not df.empty:
            df['stop_time'] = pd.to_datetime(df['stop_time'])
        return df
    except: return pd.DataFrame()

def get_live_chargers():
    """Mengambil status realtime charger beserta data live meter."""
    try:
        res = supabase.table("chargers").select("*").order("charger_id").execute()
        return pd.DataFrame(res.data)
    except: return pd.DataFrame()

def get_user_financial_summary():
    """
    Mengambil data user, profil, dan menggabungkannya dengan total pendapatan lifetime mereka.
    [FIXED COLUMN DUPLICATION HERE]
    """
    try:
        # 1. Fetch Users & Profiles
        df_users = pd.DataFrame(supabase.table("ev_users").select("user_id, full_name, username, email, created_at").order("created_at", desc=True).execute().data)
        df_profiles = pd.DataFrame(supabase.table("user_profiles").select("user_id, wallet_balance").execute().data)
        
        if df_users.empty: return df_users

        # 2. Fetch Aggregated Financials (Lifetime Revenue & Last Charged)
        trans_res = supabase.table("transactions").select("user_id, total_amount, stop_time").execute()
        df_trans = pd.DataFrame(trans_res.data)
        
        df_agg = df_trans.groupby('user_id').agg(
            lifetime_revenue=('total_amount', 'sum'),
            last_charged_time=('stop_time', 'max')
        ).reset_index()
        
        # 3. Merge Data: Users + Financials + Profiles
        df_merged = pd.merge(df_users, df_agg, on='user_id', how='left')
        df_merged = pd.merge(df_merged, df_profiles[['user_id', 'wallet_balance']], on='user_id', how='left')

        # 4. FINAL CLEANUP AND FORMATTING (Creating the clean display DataFrame)
        
        df_display = pd.DataFrame()
        
        # Identity Columns
        df_display['Nama Lengkap'] = df_merged['full_name']
        df_display['Email'] = df_merged['email']
        df_display['ID Pengguna'] = df_merged['user_id']
        
        # Financial Columns (Formatted)
        df_display['Saldo (IDR)'] = df_merged['wallet_balance'].fillna(0).apply(lambda x: f"Rp {x:,.0f}")
        df_display['Total Belanja (IDR)'] = df_merged['lifetime_revenue'].fillna(0).apply(lambda x: f"Rp {x:,.0f}")
        
        # Activity Columns
        df_display['Terakhir Mengisi'] = df_merged['last_charged_time'].fillna('Never').apply(lambda x: pd.to_datetime(x).strftime('%Y-%m-%d %H:%M') if x != 'Never' else 'Never')
        df_display['Status Aktif'] = np.where(df_merged['user_id'].isin(df_merged['user_id']), 'IDLE', 'IDLE') # Basic Status (Should check charger status)

        return df_display
    except Exception as e:
        # Menambahkan print exception untuk debugging
        print(f"\n[USER MANAGEMENT CRASH] Detail: {e}")
        traceback.print_exc(file=sys.stderr)
        st.error(f"❌ Gagal memuat manajemen pengguna: Terjadi Error saat menggabungkan data.")
        return pd.DataFrame()


# --- 4. SIDEBAR ---
with st.sidebar:
    st.title("⚡ UNIEV CPO")
    st.caption("Smart Charging Management System")
    st.divider()
    
    menu = st.radio("Menu Utama", ["Dashboard Overview", "Live Monitoring", "Financial Reports", "User Management", "CPO Admin", "Tariffs", "Tickets", "Payments", "EVSE Management"], index=0)
    
    st.divider()
    st.markdown(f"**System Status:** 🟢 Online")
    if st.button("🔄 Force Refresh"):
        st.rerun()

# --- 5. PAGE: DASHBOARD OVERVIEW (Module 2.4) ---
if menu == "Dashboard Overview":
    st.title("📊 Operational Overview")
    
    energy, rev, carbon, sessions, uptime_score, healthy_count, total_units = get_summary_metrics()
    df_chargers = get_live_chargers()
    
    # Top Metrics (KPIs)
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("🔌 Active Sessions", f"{healthy_count} Unit", help="Jumlah Charger yang Sehat/Online")
    col2.metric("🔋 Total Energy", f"{energy:,.2f} kWh", help="Energy yang sudah terjual")
    col3.metric("💰 Total Revenue", f"Rp {rev:,.0f}", help="Pendapatan Bruto")
    col4.metric("📈 Uptime Score", uptime_score, help="Skor Ketersediaan Charger")
    col5.metric("🛠️ Open Faults", f"{supabase.table('maintenance_tickets').select('*', count='exact').eq('status', 'OPEN').execute().count}", help="Tiket Gangguan yang sedang dibuka")
    
    st.divider()

    # Charts
    c1, c2 = st.columns([2, 1])
    df_trans = get_transactions_history()
    
    with c1:
        st.subheader("📈 Revenue Trend (Terbaru)")
        if not df_trans.empty:
            chart_data = df_trans.groupby(df_trans['stop_time'].dt.normalize())['total_amount'].sum().reset_index()
            fig = px.bar(
                chart_data, x='stop_time', y='total_amount',
                labels={"stop_time": "Tanggal/Waktu", "total_amount": "Pendapatan"},
                template="plotly_dark",
                title="Pendapatan Harian Agregat"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Belum ada data transaksi.")

    with c2:
        st.subheader("⚙️ Fleet Status")
        if not df_chargers.empty:
            status_counts = df_chargers['status'].value_counts().reset_index()
            status_counts.columns = ['status', 'count']
            color_map = {"Available": "#00CC96", "Charging": "#636EFA", "Faulted": "#EF553B", "Offline": "#AB63FA"}
            fig_pie = px.pie(status_counts, values='count', names='status', color='status', color_discrete_map=color_map, hole=0.4)
            st.plotly_chart(fig_pie, use_container_width=True)

# --- 6. PAGE: LIVE MONITORING (Module 2.1) ---
elif menu == "Live Monitoring":
    st.title("🔌 Station Real-time Monitor")
    st.caption("Data diperbarui setiap 2 detik")
    
    df = get_live_chargers()
    
    if not df.empty:
        st.dataframe(
            df[['charger_id', 'status', 'current_power_kw', 'current_session_kwh', 'current_soc', 'vendor', 'model', 'last_heartbeat']]
            .rename(columns={'current_power_kw': 'Daya (kW)', 'current_session_kwh': 'Energi Sesi (kWh)', 'current_soc': 'SoC (%)', 'last_heartbeat': 'Terakhir Dilihat'}),
            use_container_width=True,
            height=600
        )
    else:
        st.info("Tidak ada charger yang terhubung ke sistem.")

    time.sleep(2)
    st.rerun()

# --- 7. PAGE: FINANCIAL REPORTS (Module 2.3) ---
elif menu == "Financial Reports":
    st.title("💰 Transaction History & Billing")
    
    df = get_transactions_history()
    
    if not df.empty:
        df['Total Amount (IDR)'] = 'Rp ' + df['total_amount'].apply(lambda x: f'{x:,.0f}')
        
        col1, col2 = st.columns(2)
        col1.metric("Total Transaksi", len(df))
        col2.metric("Rata-rata Transaksi", f"Rp {df['total_amount'].mean():,.0f}")
        
        st.divider()

        st.dataframe(
            df[['transaction_id', 'charger_id', 'stop_time', 'total_kwh', 'Total Amount (IDR)', 'status', 'payment_status']]
            .rename(columns={'total_kwh': 'Energi (kWh)', 'stop_time': 'Waktu Selesai'}),
            use_container_width=True,
            hide_index=True
        )
        
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Report (CSV)", csv, "uniev_financial_report.csv", "text/csv")
    else:
        st.info("Belum ada data keuangan yang diselesaikan (Stop Transaction).")

# --- 8. PAGE: USER MANAGEMENT (BI View Lengkap) ---
elif menu == "User Management":
    st.title("👤 Manajemen Pengguna EV")
    st.caption("Data ini mencerminkan aktivitas dan finansial setiap pengguna di platform.")
    
    df_users = get_user_financial_summary()
    
    if not df_users.empty:
        
        # Final Display Table (Focus: Saldo, Belanja, Status)
        st.dataframe(
            df_users[['Nama Lengkap', 'Email', 'Saldo (IDR)', 'Total Belanja (IDR)', 'Terakhir Mengisi', 'Status Aktif', 'ID Pengguna']],
            use_container_width=True,
            height=600,
            hide_index=True
        )
    else:
        st.info("Tidak ada data pengguna EV.")


# Refresh rate standar untuk halaman selain monitoring
if menu != "Live Monitoring":
    time.sleep(10)
    st.rerun()

# --- 9. PAGE: CPO ADMIN ---
if menu == "CPO Admin":
    st.title("🏢 CPO Administration")
    api = st.text_input("API Base URL", "http://localhost:8000")
    with st.form("cpo_form"):
        cpo_id = st.text_input("CPO ID", "CPO-001")
        name = st.text_input("Nama CPO", "Contoh CPO")
        npwp = st.text_input("NPWP", "")
        siup = st.text_input("SIUP", "")
        address = st.text_input("Alamat", "")
        pic_name = st.text_input("PIC Nama", "")
        pic_phone = st.text_input("PIC Telp", "")
        profit = st.number_input("Bagi Hasil (%)", min_value=0.0, max_value=100.0, value=0.0)
        submitted = st.form_submit_button("Register CPO")
        if submitted:
            payload = {"cpo_id": cpo_id, "name": name, "npwp": npwp, "siup": siup, "address": address, "pic_name": pic_name, "pic_phone": pic_phone, "profit_sharing_percent": profit}
            try:
                r = requests.post(f"{api}/api/cpo/register", json=payload, timeout=10)
                st.success(r.json())
            except Exception as e:
                st.error(str(e))
    colv1, colv2 = st.columns(2)
    with colv1:
        vcpo = st.text_input("Verifikasi CPO ID", "CPO-001")
        if st.button("Verifikasi"):
            try:
                r = requests.post(f"{api}/api/cpo/{vcpo}/verify", timeout=10)
                st.success(r.json())
            except Exception as e:
                st.error(str(e))
    with colv2:
        wcpo = st.text_input("Wallet CPO ID", "CPO-001")
        if st.button("Lihat Wallet"):
            try:
                r = requests.get(f"{api}/api/cpo/{wcpo}/wallet", timeout=10)
                st.json(r.json())
            except Exception as e:
                st.error(str(e))

# --- 10. PAGE: TARIFFS ---
if menu == "Tariffs":
    st.title("💳 Tariff Templates")
    api = st.text_input("API Base URL", "http://localhost:8000")
    with st.form("tariff_form"):
        template_id = st.text_input("Template ID", "T-DEFAULT")
        name = st.text_input("Nama", "Default Per kWh")
        ttype = st.selectbox("Tipe", ["per_kwh", "flat", "time_based"])
        price = st.number_input("Harga/kWh", min_value=0.0, value=2500.0)
        idle_fee = st.number_input("Idle Fee/menit", min_value=0.0, value=0.0)
        cpo_id = st.text_input("CPO ID", "CPO-001")
        submitted = st.form_submit_button("Simpan Template")
        if submitted:
            payload = {"template_id": template_id, "name": name, "type": ttype, "price_per_kwh": price, "idle_fee_per_min": idle_fee, "cpo_id": cpo_id}
            try:
                r = requests.post(f"{api}/api/tariffs/templates", json=payload, timeout=10)
                st.success(r.json())
            except Exception as e:
                st.error(str(e))
    st.divider()
    cid = st.text_input("Assign ke Charger ID", "SIM-001")
    tid = st.text_input("Template ID untuk Assign", "T-DEFAULT")
    if st.button("Assign Tariff"):
        try:
            r = requests.post(f"{api}/api/tariffs/assign", params={"charger_id": cid, "template_id": tid}, timeout=10)
            st.success(r.json())
        except Exception as e:
            st.error(str(e))

# --- 11. PAGE: TICKETS ---
if menu == "Tickets":
    st.title("🎟️ Ticketing")
    api = st.text_input("API Base URL", "http://localhost:8000")
    with st.form("ticket_form"):
        ticket_id = st.text_input("Ticket ID", "TCK-0001")
        cpo_id = st.text_input("CPO ID", "CPO-001")
        charger_id = st.text_input("Charger ID", "SIM-001")
        category = st.selectbox("Kategori", ["StartFailed", "AuthFailed", "PaymentPending", "ConnectorBroken", "PriceMismatch", "AppError"]) 
        description = st.text_area("Deskripsi", "")
        priority = st.selectbox("Prioritas", ["Low", "Normal", "High", "Critical"], index=1)
        submitted = st.form_submit_button("Buat Ticket")
        if submitted:
            payload = {"ticket_id": ticket_id, "cpo_id": cpo_id, "charger_id": charger_id, "category": category, "description": description, "priority": priority}
            try:
                r = requests.post(f"{api}/api/tickets", json=payload, timeout=10)
                st.success(r.json())
            except Exception as e:
                st.error(str(e))
    st.divider()
    utid = st.text_input("Update Ticket ID", "TCK-0001")
    status = st.selectbox("Status", ["OPEN", "IN_PROGRESS", "ESCALATED", "RESOLVED"], index=0)
    assignee = st.text_input("Teknisi", "TECH-01")
    if st.button("Update Ticket"):
        try:
            r = requests.put(f"{api}/api/tickets/{utid}", params={"status": status, "assignee": assignee}, timeout=10)
            st.success(r.json())
        except Exception as e:
            st.error(str(e))

# --- 12. PAGE: PAYMENTS ---
if menu == "Payments":
    st.title("💳 Payments")
    api = st.text_input("API Base URL", "http://localhost:8000")
    st.subheader("Konfigurasi Gateway")
    with st.form("pg_form"):
        provider = st.selectbox("Provider", ["xendit","midtrans"])
        environment = st.selectbox("Environment", ["development","production"])
        api_key = st.text_input("API Key", type="password")
        name = st.text_input("Nama Alias", "Default Gateway")
        cpo_id = st.text_input("CPO ID", "CPO-001")
        submitted = st.form_submit_button("Simpan Provider")
        if submitted:
            payload = {"provider": provider, "environment": environment, "api_key": api_key, "name": name, "cpo_id": cpo_id}
            try:
                r = requests.post(f"{api}/api/payments/providers", json=payload, timeout=10)
                st.success(r.json())
            except Exception as e:
                st.error(str(e))
    st.divider()
    st.subheader("Buat Payment Intent")
    with st.form("intent_form"):
        provider2 = st.selectbox("Provider", ["xendit","midtrans"], key="prov2")
        amount = st.number_input("Amount (IDR)", min_value=1000.0, value=50000.0)
        description = st.text_input("Deskripsi", "Topup atau Pembayaran Sesi")
        cpo_id2 = st.text_input("CPO ID", "CPO-001")
        charger_id = st.text_input("Charger ID", "SIM-001")
        user_id = st.text_input("User ID", "USR-001")
        make_intent = st.form_submit_button("Create Intent")
        if make_intent:
            payload = {"provider": provider2, "amount": amount, "description": description, "cpo_id": cpo_id2, "charger_id": charger_id, "user_id": user_id}
            try:
                r = requests.post(f"{api}/api/payments/intent", json=payload, timeout=10)
                st.success(r.json())
            except Exception as e:
                st.error(str(e))
    st.divider()
    st.subheader("Daftar Provider")
    try:
        cpo_filter = st.text_input("Filter CPO ID", "")
        params = {"cpo_id": cpo_filter} if cpo_filter else {}
        providers = requests.get(f"{api}/api/payments/providers", params=params, timeout=10).json()
        st.dataframe(pd.DataFrame(providers), use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(str(e))

# --- 13. PAGE: EVSE MANAGEMENT ---
if menu == "EVSE Management":
    st.title("🔧 EVSE Management")
    api = st.text_input("API Base URL", "http://localhost:8000")
    with st.form("evse_cmd_form"):
        charger_id = st.text_input("Charger ID", "SIM-001")
        action = st.selectbox("Action", ["REBOOT","UNLOCK","LOCK","UPDATE_FIRMWARE","UPDATE_CONFIG"])
        payload = st.text_area("Payload JSON (opsional)", "{}")
        submit = st.form_submit_button("Kirim Perintah")
        if submit:
            try:
                jp = {}
                try:
                    import json
                    jp = json.loads(payload or "{}")
                except: jp = {}
                r = requests.post(f"{api}/api/evse/command", params={"charger_id": charger_id, "action": action}, json=jp, timeout=10)
                st.success(r.json())
            except Exception as e:
                st.error(str(e))