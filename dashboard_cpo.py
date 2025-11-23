import streamlit as st
import pandas as pd
import plotly.express as px
import time
from datetime import datetime

# --- 1. PAGE CONFIG ---
st.set_page_config(
    page_title="UNIEV CPO Command Center",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS untuk tampilan profesional (Dark Mode friendly)
st.markdown("""
<style>
    [data-testid="stMetricValue"] {
        font-size: 24px;
    }
    div.stButton > button:first-child {
        width: 100%;
    }
    .status-card {
        padding: 10px;
        border-radius: 5px;
        margin-bottom: 10px;
        border: 1px solid #444;
    }
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

# --- 3. DATA FUNCTIONS ---
def get_summary_metrics():
    """Mengambil total transaksi dan revenue"""
    try:
        res = supabase.table("transactions").select("total_kwh, total_amount, carbon_saved_kg").execute()
        df = pd.DataFrame(res.data)
        
        if df.empty: return 0, 0, 0, 0
            
        return (
            df['total_kwh'].sum(),
            df['total_amount'].sum(),
            df['carbon_saved_kg'].sum(),
            len(df)
        )
    except: return 0, 0, 0, 0

def get_live_chargers():
    """Mengambil status realtime charger beserta data live meter"""
    try:
        res = supabase.table("chargers").select("*").order("charger_id").execute()
        return pd.DataFrame(res.data)
    except: return pd.DataFrame()

def get_transactions_history():
    """Riwayat transaksi"""
    try:
        res = supabase.table("transactions").select("*").order("stop_time", desc=True).limit(50).execute()
        df = pd.DataFrame(res.data)
        if not df.empty:
            df['stop_time'] = pd.to_datetime(df['stop_time'])
        return df
    except: return pd.DataFrame()

# --- 4. SIDEBAR ---
with st.sidebar:
    st.title("⚡ UNIEV CPO")
    st.caption("Smart Charging Management System")
    st.divider()
    
    menu = st.radio("Menu Utama", ["Dashboard Overview", "Live Monitoring", "Financial Reports"])
    
    st.divider()
    st.markdown("**System Status:** 🟢 Online")
    if st.button("🔄 Refresh Data"):
        st.rerun()

# --- 5. PAGE: DASHBOARD OVERVIEW ---
if menu == "Dashboard Overview":
    st.title("📊 Operational Overview")
    
    energy, rev, carbon, sessions = get_summary_metrics()
    df_chargers = get_live_chargers()
    
    # Hitung Active Chargers
    active_now = 0
    if not df_chargers.empty and 'status' in df_chargers.columns:
        active_now = len(df_chargers[df_chargers['status'] == 'Charging'])
    
    # Top Metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🔌 Active Sessions", f"{active_now} Unit", delta_color="normal")
    col2.metric("🔋 Total Energy", f"{energy:,.2f} kWh")
    col3.metric("💰 Total Revenue", f"Rp {rev:,.0f}")
    col4.metric("🌱 Carbon Saved", f"{carbon:,.1f} kg")

    st.divider()

    # Charts
    c1, c2 = st.columns([2, 1])
    
    with c1:
        st.subheader("📈 Revenue Trend")
        df_trans = get_transactions_history()
        if not df_trans.empty:
            fig = px.bar(
                df_trans, x="stop_time", y="total_amount",
                labels={"stop_time": "Waktu", "total_amount": "Pendapatan"},
                template="plotly_dark"
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

# --- 6. PAGE: LIVE MONITORING (REAL-TIME) ---
elif menu == "Live Monitoring":
    st.title("🔌 Station Real-time Monitor")
    st.caption("Data diperbarui setiap 2 detik")
    
    df = get_live_chargers()
    
    if not df.empty:
        # Loop setiap charger untuk membuat tampilan kartu
        for index, row in df.iterrows():
            # Tentukan warna indikator
            stat = row.get('status', 'Offline')
            
            # Container visual sederhana
            with st.container():
                st.markdown(f"### 📍 {row['charger_id']}")
                
                # Grid Layout untuk Metrics
                c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 2])
                
                with c1:
                    st.caption("Vendor / Model")
                    st.write(f"{row.get('vendor', '-')}")
                    st.write(f"{row.get('model', '-')}")
                
                with c2:
                    st.caption("Current Status")
                    if stat == 'Charging':
                        st.markdown(f"#### 🔵 {stat}")
                    elif stat == 'Available':
                        st.markdown(f"#### 🟢 {stat}")
                    elif stat == 'Faulted':
                        st.markdown(f"#### 🔴 {stat}")
                    else:
                        st.markdown(f"#### ⚫ {stat}")

                with c3:
                    st.caption("⚡ Load Power")
                    # Ambil data live (default 0 jika null)
                    kw = row.get('current_power_kw') or 0.0
                    st.metric("Power", f"{kw:.2f} kW", label_visibility="collapsed")

                with c4:
                    st.caption("🔋 Session Energy")
                    # Ambil data live
                    kwh = row.get('current_session_kwh') or 0.0
                    st.metric("Energy", f"{kwh:.3f} kWh", label_visibility="collapsed")

                with c5:
                    st.caption("🚗 Battery SoC")
                    soc = row.get('current_soc') or 0
                    st.metric("SoC", f"{soc}%", label_visibility="collapsed")

                # Progress Bar Visual
                if stat == 'Charging':
                    st.progress(int(soc), text=f"Charging... {soc}%")
                else:
                    st.progress(0, text="Standby")
                
                st.divider()
    else:
        st.info("Tidak ada charger yang terhubung ke sistem.")

    # Auto Refresh khusus halaman ini (Lebih cepat)
    time.sleep(2)
    st.rerun()

# --- 7. PAGE: FINANCIAL REPORTS ---
elif menu == "Financial Reports":
    st.title("💰 Transaction History")
    
    df = get_transactions_history()
    
    if not df.empty:
        col1, col2 = st.columns(2)
        col1.metric("Rata-rata Transaksi", f"Rp {df['total_amount'].mean():,.0f}")
        col2.metric("Total Transaksi (Halaman Ini)", len(df))
        
        st.dataframe(
            df[['transaction_id', 'charger_id', 'stop_time', 'total_kwh', 'total_amount', 'status']],
            use_container_width=True,
            hide_index=True
        )
        
        # CSV Download
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download CSV", csv, "uniev_report.csv", "text/csv")
    else:
        st.info("Belum ada data keuangan.")

# Refresh rate standar untuk halaman selain monitoring
if menu != "Live Monitoring":
    time.sleep(10)
    st.rerun()