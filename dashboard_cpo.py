import streamlit as st
import pandas as pd
import plotly.express as px
import time
from datetime import datetime
import numpy as np

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
    
    menu = st.radio("Menu Utama", ["Dashboard Overview", "Live Monitoring", "Financial Reports", "User Management"], index=0)
    
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