import streamlit as st
import pandas as pd
import time
from datetime import datetime

# --- 1. CONFIG & STYLING ---
st.set_page_config(page_title="UNIEV Driver App", page_icon="⚡", layout="centered")

# Custom CSS (Native App Look)
st.markdown("""
<style>
    .stApp { background-color: #F5F7FA; font-family: 'Helvetica Neue', sans-serif; }
    
    /* Card Styles */
    .car-card { background: white; padding: 20px; border-radius: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.05); margin-bottom: 20px; text-align: center; }
    .info-card { background: white; padding: 15px; border-radius: 12px; border: 1px solid #eee; margin-bottom: 10px; }
    
    /* Typography */
    .card-title { font-size: 16px; font-weight: 700; color: #1F2937; }
    .price-big { font-size: 24px; font-weight: 800; color: #2563EB; }
    
    /* Button Override */
    div.stButton > button { border-radius: 12px; height: 50px; font-weight: 600; width: 100%; }

    /* Centering and sizing car image */
    .car-image-container { display: flex; justify-content: center; align-items: center; height: 150px; overflow: hidden; }
    .car-image-container img { max-width: 90%; max-height: 100%; object-fit: contain; }
</style>
""", unsafe_allow_html=True)

# --- 2. DATABASE CONNECTION ---
try:
    from backend.database import supabase
except ImportError:
    st.error("⚠️ Backend connection failed.")
    st.stop()

# --- 3. STATE & AUTH MANAGEMENT ---
if "user" not in st.session_state:
    st.session_state.user = {"id": "GUEST", "name": "Guest", "balance": 0}
if "selected_car_index" not in st.session_state:
    st.session_state.selected_car_index = 0
if "nav" not in st.session_state:
    st.session_state.nav = "Home"
if "is_authenticated" not in st.session_state:
    st.session_state.is_authenticated = False

# --- 4. CORE FUNCTIONS ---

def authenticate(username, password):
    """Simulasi Login: Cek username dan password ke DB"""
    if not supabase: return False, "DB not connected"
    
    try:
        res = supabase.table("ev_users").select("*").eq("username", username).execute()
        user_data = res.data[0] if res.data else None
        
        if user_data:
            # DEMO CHECK (Should use bcrypt in production)
            if password == user_data['hashed_password']: 
                
                profile_res = supabase.table("user_profiles").select("*").eq("user_id", user_data['user_id']).execute()
                profile_data = profile_res.data[0] if profile_res.data else {}

                st.session_state.is_authenticated = True
                st.session_state.user = {
                    "id": user_data['user_id'],
                    "name": user_data['full_name'],
                    "balance": profile_data.get('wallet_balance', 500000),
                }
                st.session_state.selected_car_index = profile_data.get('active_car_index', 0)
                
                return True, "Login Successful"
        
        return False, "Invalid username or password."
    except Exception as e:
        return False, f"Login Error: {e}"

def logout_user():
    st.session_state.is_authenticated = False
    st.session_state.user = {"id": "GUEST", "name": "Guest", "balance": 0}
    st.session_state.nav = "Home"
    st.rerun()

def save_user_car_preference(car_index):
    """Menyimpan pilihan mobil user ke DB."""
    if not st.session_state.is_authenticated: return
    try:
        supabase.table("user_profiles").upsert({
            "user_id": st.session_state.user["id"],
            "active_car_index": car_index,
        }).execute()
        st.session_state.selected_car_index = car_index
    except Exception as e:
        print(f"ERROR saving preference: {e}")

def get_chargers():
    try: return supabase.table("chargers").select("*").order("charger_id").execute().data
    except Exception as e: 
        print(f"\n[DEBUG ERROR] Gagal fetch chargers: {e}")
        return []

def get_cars():
    try: return supabase.table("electric_vehicles").select("*").order("brand, model").execute().data
    except Exception as e:
        print(f"\n[CRITICAL ERROR] Gagal memuat data mobil dari DB. Penyebab: {e}")
        return []

def check_active_session(chargers_data):
    for c in chargers_data:
        if c['status'] == 'Charging': return c
    return None

def send_cmd(charger_id, action):
    try:
        supabase.table("charging_commands").insert({"charger_id": charger_id, "user_id": st.session_state.user["id"], "action": action, "status": "PENDING"}).execute()
        return True
    except: return False

def force_reset_charger(charger_id):
    try:
        supabase.table("chargers").update({"status": "Available", "current_session_kwh": 0, "current_power_kw": 0, "current_soc": 0}).eq("charger_id", charger_id).execute()
        return True
    except: return False

def wait_for_charging_start(charger_id):
    start_time = time.time()
    while time.time() - start_time < 10:
        chargers_data = get_chargers()
        for c in chargers_data:
            if c['charger_id'] == charger_id and c['status'] == 'Charging':
                return True
        time.sleep(1)
    return False


# --- LOAD MASTER DATA ---
cars = get_cars()
chargers = get_chargers()
car_names = [f"{x['brand']} {x['model']} ({x['battery_capacity_kwh']} kWh)" for x in cars] if cars else []

# Definisikan Mobil Default
default_car = {
    "brand": "Generic", "model": "Car", "battery_capacity_kwh": 50.0, 
    "image_url": "https://i.ibb.co/3s685Gk/polestar-generic-car.png"
}

# Logic Pengamanan Index List
if not cars:
    my_car = default_car
else:
    if st.session_state.selected_car_index >= len(cars):
        st.session_state.selected_car_index = 0
    my_car = cars[st.session_state.selected_car_index]

active_session_charger = check_active_session(chargers)


# --- 5. PAGE DEFINITIONS ---

def page_login():
    st.title("Welcome to UNIEV")
    st.caption("Aplikasi Manajemen Pengisian Daya EV")

    st.markdown("---")
    
    with st.form("login_form"):
        st.subheader("Login User Demo")
        username = st.text_input("Username", value="userdemo")
        password = st.text_input("Password", type="password", value="test1234")
        submitted = st.form_submit_button("LOGIN", type="primary")

        if submitted:
            success, message = authenticate(username, password)
            if success:
                st.success(f"Welcome, {st.session_state.user['name']}!")
                time.sleep(1)
                st.rerun()
            else:
                st.error(message)


def page_home(my_car):
    st.markdown("### 🚘 My Vehicle")
    
    # Render Dynamic Car Image
    st.markdown("<div class='car-card' style='text-align:center;'>", unsafe_allow_html=True)
    st.markdown("<div class='car-image-container'>", unsafe_allow_html=True)
    if my_car.get('image_url'):
        st.image(my_car['image_url'], caption="", output_format="auto", use_column_width=False, width=250)
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown(f"<h3>{my_car['brand']} {my_car['model']}</h3>", unsafe_allow_html=True)
    st.markdown(f"<p class='sub-text' style='margin-bottom:20px;'>Battery: {my_car['battery_capacity_kwh']} kWh</p>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # [FIX LOGIC] Baterai Bawaan: Ambil 27% (default) jika tidak ada sesi aktif
    current_soc_display = 27 
    is_charging_bar = False
    
    if active_session_charger:
        # Jika sedang charging, ambil data live dari DB
        current_soc_display = int(active_session_charger.get('current_soc', 0) or 0)
        is_charging_bar = True

    # Status Card
    # Progress bar hanya muncul jika sedang charging
    soc_width = current_soc_display if is_charging_bar else 0

    st.markdown("""
    <div class="info-card" style="text-align:center;">
        <div style="font-size:24px; font-weight:bold; color:#2563EB;">{}%</div>
        <div class="sub-text">Current Battery Level {}</div>
        <div style="height:5px; background:#eee; margin-top:5px; border-radius:5px;">
            <div style="width:{}%; height:100%; background:#2563EB; border-radius:5px;"></div>
        </div>
    </div>
    """.format(current_soc_display, "(Live)" if is_charging_bar else "(Est.)", soc_width), unsafe_allow_html=True)
    
    st.write("---")
    if st.button("⚡ FIND CHARGER & START", type="primary"):
        st.session_state.nav = "Charge"
        st.rerun()

def page_charge(my_car):
    st.title("Isi Daya")
    st.caption(f"Selected Vehicle: **{my_car['model']}**")
    
    tab_scan, tab_list = st.tabs(["🔌 Konfigurasi", "📋 Troubleshoot"])

    with tab_scan:
        # 1. PILIH CHARGER
        available_c = [x for x in chargers if x['status'] == 'Available']
        if not available_c:
            st.error("❌ Tidak ada charger yang tersedia saat ini.")
            return

        c_opts = {x['charger_id']: x for x in available_c}
        sel_id = st.selectbox("Pilih Mesin", list(c_opts.keys()))
        sel_c = c_opts[sel_id]
        
        # TAMPILAN DETAIL CHARGER
        ctype = sel_c.get('current_type', 'AC')
        badge_type = "DC FAST ⚡" if ctype == 'DC' else "AC Type 2 🌱"
        badge_cls = "badge-dc" if ctype == 'DC' else "badge-ac"
        
        st.markdown(f"""
        <div class="info-card">
            <div class="card-title">{sel_c['vendor']} {sel_id}</div>
            <div class="sub-text">Max Power: {sel_c['max_power_kw']} kW</div>
            <div style="font-weight:bold; margin-top:10px;">
                <span class="badge {badge_cls}">{badge_type}</span>
                <span style="color:#2563EB; margin-left:10px;">Rp 2,466 / kWh</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
            
        # 2. KALKULATOR PENGISIAN
        price_per_kwh = 2466
        bat_cap = float(my_car['battery_capacity_kwh'])
        
        st.write("Target Pengisian")
        mode = st.radio("Mode", ["Penuh (Full Tank)", "Target %", "Nominal (Rp)", "Energi (kWh)"], horizontal=True, label_visibility="collapsed")
        
        target_kwh = 0.0
        target_rp = 0.0
        
        if mode == "Penuh (Full Tank)":
            st.caption("Input sisa baterai (AC Charger tidak bisa baca otomatis):")
            current_soc = st.slider("Current SoC (%)", 0, 99, 20, key="soc_full")
            
            percent_needed = 100 - current_soc
            target_kwh = (percent_needed / 100) * bat_cap
            target_rp = target_kwh * price_per_kwh
            st.info(f"Butuh isi **{percent_needed}%** ({target_kwh:.2f} kWh) lagi.")
            
        elif mode == "Target %":
            st.caption("Input persentase yang ingin dicapai:")
            target_soc = st.slider("Target SoC (%)", 1, 100, 80, key="soc_target")
            current_soc = st.slider("Sisa Baterai Saat Ini (%)", 0, 99, 20, key="soc_current_target")
            
            if target_soc > current_soc:
                percent_needed = target_soc - current_soc
                target_kwh = (percent_needed / 100) * bat_cap
                target_rp = target_kwh * price_per_kwh
                st.info(f"Mengisi dari {current_soc}% ke {target_soc}% butuh **{target_kwh:.2f} kWh**.")
            else:
                 st.info("Target persentase harus lebih besar dari sisa baterai saat ini.")
            
        elif mode == "Nominal (Rp)":
            input_rp = st.number_input("Nominal Rupiah", min_value=10000, value=50000, step=5000, key="rp_input")
            target_rp = input_rp
            target_kwh = input_rp / price_per_kwh

        elif mode == "Energi (kWh)":
            target_kwh = st.number_input("Target kWh", min_value=1.0, value=10.0, step=1.0, key="kwh_input")
            target_rp = target_kwh * price_per_kwh
        
        # --- PERHITUNGAN DURASI BARU ---
        charger_power = sel_c.get('max_power_kw', 1) 
        duration_hours = target_kwh / charger_power
        
        total_minutes = int(duration_hours * 60)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        
        duration_str = ""
        if hours > 0:
            duration_str += f"{hours} jam "
        if minutes > 0 or total_minutes == 0:
            duration_str += f"{minutes} menit"
        if total_minutes == 0 and target_kwh > 0:
            duration_str = "< 1 menit"
        # --- END PERHITUNGAN DURASI ---


        # Summary Box (Diperbarui menjadi 3 kolom)
        st.write("---")
        c_res1, c_res2, c_res3 = st.columns(3)
        c_res1.metric("Estimasi Biaya", f"Rp {target_rp:,.0f}")
        c_res2.metric("Target Energi", f"{target_kwh:.2f} kWh")
        c_res3.metric("Estimasi Durasi", duration_str)
        
        st.write("")
        
        # START BUTTON & EXECUTION
        if st.button("⚡ MULAI PENGISIAN", type="primary"):
            if send_cmd(sel_id, "REMOTE_START"):
                status_bar = st.progress(0, text="Menghubungkan...")
                for i in range(100):
                    time.sleep(0.03)
                    status_bar.progress(i + 1)
                    if i % 25 == 0:
                        if wait_for_charging_start(sel_id):
                            st.success("✅ Berhasil terhubung! Memulai pengisian...")
                            time.sleep(1)
                            st.session_state.nav = "Active"
                            st.rerun()
                            break
                else:
                    st.error("❌ Gagal terhubung ke mesin (Timeout).")
            else:
                st.error("Gagal mengirim perintah server.")

    with tab_list:
        st.title("Troubleshooting")
        st.caption("Gunakan ini jika status charger nyangkut.")
        
        # Manual Reset Tool (Fix Ghost State)
        all_ids = [c['charger_id'] for c in chargers]
        target_reset = st.selectbox("Pilih Charger Error", all_ids, key="reset_sel_charger_fix")
        if st.button("🔄 Force Reset Status", key="force_reset_btn_fix"):
            if force_reset_charger(target_reset):
                st.success(f"Charger {target_reset} reset to Available!")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Failed to reset.")


def page_active_charging(active_c):
    st.title("⚡ Charging Aktif")
    st.info(f"Mengisi di {active_c['charger_id']}")
    
    live_kwh = float(active_c.get('current_session_kwh', 0) or 0)
    live_kw = float(active_c.get('current_power_kw', 0) or 0)
    live_soc = int(active_c.get('current_soc', 0) or 0)
    
    c1, c2 = st.columns(2)
    c1.metric("Total Energi", f"{live_kwh:.3f} kWh")
    c2.metric("Daya Masuk", f"{live_kw:.2f} kW")
    
    st.caption(f"Status Baterai: {live_soc}%")
    st.progress(live_soc, text="Charging Progress")
    
    st.write("---")
    
    if st.button("⏹️ AKHIRI PENGISIAN (STOP)", type="primary"):
        if send_cmd(active_c['charger_id'], "REMOTE_STOP"):
            st.toast("Memutuskan daya...", icon="🛑")
            time.sleep(3)
            st.session_state.nav = "Charge"
            st.rerun()

def page_car_library():
    st.title("📋 Car Library")
    
    if not cars:
        st.error("Database mobil kosong. Silakan isi data.")
        return
        
    if not car_names:
        st.warning("Data mobil tidak terstruktur dengan benar.")
        return
        
    current_selected_car_name = car_names[st.session_state.selected_car_index]
    new_selected_car_name = st.selectbox("Currently Active Vehicle", car_names, index=st.session_state.selected_car_index, key="car_switch_library")
    
    if new_selected_car_name != current_selected_car_name:
        save_user_car_preference(car_names.index(new_selected_car_name))
        st.toast(f"Active vehicle changed to {new_selected_car_name}", icon="🚗")
        time.sleep(0.5)
        st.rerun()
        
    st.write("---")
    st.subheader(f"Daftar Lengkap Model ({len(cars)})")

    for car in cars:
        st.markdown(f"""
        <div class="info-card" style="display:flex; align-items:center;">
            <img src="{car['image_url']}" style="width:100px; height:50px; object-fit:contain; margin-right:15px;" alt="{car['model']}">
            <div>
                <div class="card-title">{car['brand']} {car['model']}</div>
                <span class="sub-text">Max Kapasitas: {car['battery_capacity_kwh']} kWh</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
def page_account():
    st.title("👤 My Account")
    
    st.markdown(f"""
    <div class="info-card">
        <div style="font-weight:bold;">Hello, {st.session_state.user['name']}</div>
        <div class="sub-text">Member ID: {st.session_state.user['id']}</div>
    </div>
    """, unsafe_allow_html=True)
    
    st.metric("Wallet Balance", f"Rp {st.session_state.user['balance']:,.0f}")
    
    st.write("---")
    if st.button("Log Out", type="secondary"):
        logout_user()


# --- 7. NAVIGATION CONTROLLER ---

if st.session_state.is_authenticated == False:
    page_login()
    st.stop()
    
if active_session_charger and st.session_state.nav != "Active":
    st.session_state.nav = "Active" 

# Render Page
if st.session_state.nav == "Home":
    page_home(my_car)
elif st.session_state.nav == "Charge":
    page_charge(my_car)
elif st.session_state.nav == "Active":
    page_active_charging(active_session_charger)
elif st.session_state.nav == "Car Library":
    page_car_library()
elif st.session_state.nav == "Account":
    page_account()


# Bottom Navigation Bar
st.write("---")
col_nav1, col_nav2, col_nav3, col_nav4 = st.columns(4)

with col_nav1:
    if st.button("🏠 Home", key="nav_home", type="primary" if st.session_state.nav == "Home" else "secondary"):
        st.session_state.nav = "Home"; st.rerun()
with col_nav2:
    if st.button("⚡ Charge", key="nav_charge", type="primary" if st.session_state.nav == "Charge" or st.session_state.nav == "Active" else "secondary"):
        st.session_state.nav = "Charge"; st.rerun()
with col_nav3:
    if st.button("🚗 Library", key="nav_library", type="primary" if st.session_state.nav == "Car Library" else "secondary"):
        st.session_state.nav = "Car Library"; st.rerun()
with col_nav4:
    if st.button("👤 Akun", key="nav_acc", type="primary" if st.session_state.nav == "Account" else "secondary"):
        st.session_state.nav = "Account"; st.rerun()

# Auto Refresh
sleep_time = 2 if active_session_charger else 5
time.sleep(sleep_time)
st.rerun()