import streamlit as st
import pandas as pd
import plotly.express as px
from backend.database import supabase
import time

# Konfigurasi Halaman
st.set_page_config(page_title="UNIEV CPO Dashboard", layout="wide", page_icon="⚡")

# Header
st.title("⚡ UNIEV Command Center")
st.markdown("---")

# --- 1. DATA LOADING ---
if not supabase:
    st.error("Database Connection Failed!")
    st.stop()

def load_data():
    # Load Chargers
    chargers = pd.DataFrame(supabase.table("chargers").select("*").execute().data)
    # Load Transactions
    trans = pd.DataFrame(supabase.table("transactions").select("*").execute().data)
    return chargers, trans

try:
    df_chargers, df_trans = load_data()
except Exception as e:
    st.warning("Belum ada data transaksi. Silakan gunakan simulator.")
    df_chargers = pd.DataFrame()
    df_trans = pd.DataFrame()

# --- 2. KEY METRICS (KPI) ---
col1, col2, col3, col4 = st.columns(4)

with col1:
    active_chargers = len(df_chargers[df_chargers['status'] == 'Charging']) if not df_chargers.empty else 0
    st.metric("🔌 Active Charging", f"{active_chargers} Unit", delta_color="normal")

with col2:
    total_rev = df_trans['total_amount'].sum() if not df_trans.empty else 0
    st.metric("💰 Total Revenue", f"Rp {total_rev:,.0f}")

with col3:
    total_energy = df_trans['total_kwh'].sum() if not df_trans.empty else 0
    st.metric("⚡ Energy Delivered", f"{total_energy:,.2f} kWh")

with col4:
    co2 = df_trans['carbon_saved_kg'].sum() if not df_trans.empty else 0
    st.metric("🌱 CO2 Saved", f"{co2:,.2f} kg", delta="High Impact")

# --- 3. CHARTS & GRAPHS ---
c1, c2 = st.columns([2, 1])

with c1:
    st.subheader("📈 Revenue Trend")
    if not df_trans.empty:
        df_trans['stop_time'] = pd.to_datetime(df_trans['stop_time'])
        chart_data = df_trans.groupby(df_trans['stop_time'].dt.hour)['total_amount'].sum().reset_index()
        fig = px.bar(chart_data, x='stop_time', y='total_amount', labels={'stop_time': 'Jam', 'total_amount': 'Rupiah'})
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Waiting for transactions...")

with c2:
    st.subheader("⚙️ Charger Status")
    if not df_chargers.empty:
        status_counts = df_chargers['status'].value_counts()
        fig2 = px.pie(values=status_counts.values, names=status_counts.index, hole=0.4)
        st.plotly_chart(fig2, use_container_width=True)

# --- 4. REALTIME TABLE ---
st.subheader("📝 Live Transaction Logs")
if not df_trans.empty:
    st.dataframe(
        df_trans[['transaction_id', 'charger_id', 'total_kwh', 'total_amount', 'status', 'stop_time']]
        .sort_values('stop_time', ascending=False),
        use_container_width=True
    )
else:
    st.text("No logs yet.")

# Tombol Refresh Manual
if st.button("Refresh Data"):
    st.rerun()