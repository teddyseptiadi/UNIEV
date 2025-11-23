import sys
import os
import subprocess
import threading
import time
import socket
import psutil
import tkinter as tk
from datetime import datetime
import ttkbootstrap as tb
from ttkbootstrap.constants import *

# --- FIX PATH IMPORT ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(CURRENT_DIR)
sys.path.append(ROOT_DIR)

from backend import config
from backend.database import Database

class ServiceNode:
    """Class Helper untuk menyimpan state setiap Service"""
    def __init__(self, name, script, port):
        self.name = name
        self.script = script
        self.port = port
        self.process = None
        self.prev_io = None
        self.current_speed_in = 0.0 # KB/s
        self.current_speed_out = 0.0 # KB/s
        
        # UI Component References
        self.status_lamp = None
        self.lbl_pid = None     # NEW: Label PID
        self.lbl_speed_in = None
        self.lbl_speed_out = None
        self.btn_control = None

class UnievOrchestrator(tb.Window):
    def __init__(self):
        super().__init__(themename="cyborg")
        self.title("UNIEV COMMAND CENTER - System Monitor")
        self.geometry("1250x750") # Sedikit diperlebar agar muat info PID
        
        self.db_latency = 0
        self.running = True
        
        # Registrasi Services
        self.services = {
            "OCPP": ServiceNode("OCPP Server", "ocpp_server.py", config.PORT_OCPP),
            "API": ServiceNode("REST API", "main_api.py", config.PORT_API),
            "OCPI": ServiceNode("OCPI Roaming", "ocpi_service.py", config.PORT_OCPI)
        }
        
        self.create_ui()
        
        # Start Loops
        threading.Thread(target=self.loop_monitor_resources, daemon=True).start()
        threading.Thread(target=self.loop_monitor_database, daemon=True).start()

    def create_ui(self):
        # Header
        header = tb.Frame(self, bootstyle="dark", padding=15)
        header.pack(fill=X)
        tb.Label(header, text="UNIEV", font=("Impact", 30), bootstyle="inverse-light").pack(side=LEFT)
        tb.Label(header, text="INFRASTRUCTURE MANAGER", font=("Arial", 10, "bold"), foreground="#00ff00").pack(side=LEFT, padx=10, pady=(15,0))
        
        ip_info = tb.Label(header, text=f"HOST IP: {self.get_local_ip()}", font=("Consolas", 14, "bold"), bootstyle="inverse-warning")
        ip_info.pack(side=RIGHT)

        # Main Container
        container = tb.Frame(self, padding=20)
        container.pack(fill=BOTH, expand=YES)

        # --- KOLOM KIRI: SERVICE CONTROLS & TRAFFIC ---
        left_pane = tb.Labelframe(container, text=" Active Services & Nodes ", padding=15, bootstyle="info")
        left_pane.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 10))

        for key, svc in self.services.items():
            self.create_service_card(left_pane, key, svc)

        # --- KOLOM KANAN: DB & LOGS ---
        right_pane = tb.Frame(container)
        right_pane.pack(side=RIGHT, fill=BOTH, expand=YES)

        # DB Panel
        db_pane = tb.Labelframe(right_pane, text=" Database Connection (Supabase) ", padding=15, bootstyle="success")
        db_pane.pack(fill=X, pady=(0, 15))
        
        self.lbl_db_status = tb.Label(db_pane, text="● CHECKING...", font=("Arial", 14, "bold"), bootstyle="secondary")
        self.lbl_db_status.pack(anchor=W)
        
        stats_frame = tb.Frame(db_pane, padding=(0,10))
        stats_frame.pack(fill=X)
        
        tb.Label(stats_frame, text="Round-Trip Latency:", font=("Arial", 11)).pack(side=LEFT)
        self.lbl_latency_val = tb.Label(stats_frame, text="0 ms", font=("Consolas", 14, "bold"), bootstyle="warning")
        self.lbl_latency_val.pack(side=LEFT, padx=10)

        # Logs Panel
        log_pane = tb.Labelframe(right_pane, text=" System Output Log ", padding=15, bootstyle="secondary")
        log_pane.pack(fill=BOTH, expand=YES)
        
        self.log_area = tk.Text(log_pane, height=10, bg="#0f0f0f", fg="#00ff00", font=("Consolas", 9), state="normal")
        self.log_area.pack(fill=BOTH, expand=YES)

    def create_service_card(self, parent, key, svc):
        card = tb.Frame(parent, borderwidth=1, relief="solid", padding=15)
        card.pack(fill=X, pady=8)
        
        # --- ROW 1: Header & Button ---
        row1 = tb.Frame(card)
        row1.pack(fill=X)
        
        # Nama Service
        tb.Label(row1, text=f"{svc.name}", font=("Arial", 12, "bold")).pack(side=LEFT)
        
        # Tombol Control
        svc.btn_control = tb.Button(row1, text="START SERVICE", bootstyle="success", width=15, 
                                    command=lambda k=key: self.toggle_service(k))
        svc.btn_control.pack(side=RIGHT)

        # --- ROW 2: Technical Info (Status, Port, PID) ---
        row2 = tb.Frame(card, padding=(0, 10))
        row2.pack(fill=X)

        # Status Lamp
        svc.status_lamp = tb.Label(row2, text="● STOPPED", bootstyle="danger", font=("Arial", 10, "bold"), width=12)
        svc.status_lamp.pack(side=LEFT)
        
        # Divider
        tb.Separator(row2, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=10)

        # Port Number
        tb.Label(row2, text="PORT:", font=("Arial", 8), foreground="gray").pack(side=LEFT)
        tb.Label(row2, text=f"{svc.port}", font=("Consolas", 10, "bold"), bootstyle="info").pack(side=LEFT, padx=(2, 10))

        # PID (Process ID)
        tb.Label(row2, text="PID:", font=("Arial", 8), foreground="gray").pack(side=LEFT)
        svc.lbl_pid = tb.Label(row2, text="----", font=("Consolas", 10, "bold"), bootstyle="secondary")
        svc.lbl_pid.pack(side=LEFT, padx=(2, 0))

        # --- ROW 3: Traffic Meters ---
        row3 = tb.Frame(card)
        row3.pack(fill=X)
        
        # IN Meter
        f_in = tb.Frame(row3)
        f_in.pack(side=LEFT, fill=X, expand=YES, padx=(0,5))
        tb.Label(f_in, text="TRAFFIC IN (RX)", font=("Arial", 7), foreground="gray").pack(anchor=W)
        svc.lbl_speed_in = tb.Label(f_in, text="0.0 KB/s", font=("Consolas", 10, "bold"), foreground="#5bc0de")
        svc.lbl_speed_in.pack(anchor=W)

        # OUT Meter
        f_out = tb.Frame(row3)
        f_out.pack(side=LEFT, fill=X, expand=YES, padx=(5,0))
        tb.Label(f_out, text="TRAFFIC OUT (TX)", font=("Arial", 7), foreground="gray").pack(anchor=W)
        svc.lbl_speed_out = tb.Label(f_out, text="0.0 KB/s", font=("Consolas", 10, "bold"), foreground="#f0ad4e")
        svc.lbl_speed_out.pack(anchor=W)

    # --- LOGIC SERVICE CONTROL ---
    def toggle_service(self, key):
        svc = self.services[key]
        if svc.process is None:
            # START
            self.log(f"Starting {svc.name} on Port {svc.port}...")
            script_path = os.path.join(ROOT_DIR, 'backend', svc.script)
            try:
                # [PERBAIKAN] Tambahkan "-u" agar log muncul seketika tanpa delay
                svc.process = subprocess.Popen(
                    [sys.executable, "-u", script_path], 
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1 # Line buffered
                )
                threading.Thread(target=self.read_output, args=(svc.process, key), daemon=True).start()
                
                # UI Update - ACTIVE STATE
                svc.btn_control.configure(text="STOP SERVICE", bootstyle="danger")
                svc.status_lamp.configure(text="● RUNNING", bootstyle="success")
                
                # Update PID UI
                pid_num = svc.process.pid
                svc.lbl_pid.configure(text=f"{pid_num}", bootstyle="warning")
                
            except Exception as e:
                self.log(f"Error starting {key}: {e}")
        else:
            # ... (kode stop tetap sama) ...
            # STOP
            self.log(f"Stopping {svc.name} (PID: {svc.process.pid})...")
            svc.process.terminate()
            svc.process = None
            svc.prev_io = None
            
            # UI Update - STOPPED STATE
            svc.btn_control.configure(text="START SERVICE", bootstyle="success")
            svc.status_lamp.configure(text="● STOPPED", bootstyle="danger")
            
            # Reset Metrics & PID
            svc.lbl_pid.configure(text="----", bootstyle="secondary")
            svc.lbl_speed_in.configure(text="0.0 KB/s")
            svc.lbl_speed_out.configure(text="0.0 KB/s")

    def read_output(self, proc, key):
        while True:
            line = proc.stdout.readline()
            if not line: break
            self.log(f"[{key}] {line.strip()}")

    # --- LOGIC MONITORING (TRAFFIC) ---
    def loop_monitor_resources(self):
        while self.running:
            for key, svc in self.services.items():
                if svc.process and svc.process.poll() is None:
                    try:
                        proc = psutil.Process(svc.process.pid)
                        io = proc.io_counters() 
                        
                        if svc.prev_io:
                            read_diff = io.read_bytes - svc.prev_io.read_bytes
                            write_diff = io.write_bytes - svc.prev_io.write_bytes
                            
                            svc.current_speed_in = read_diff / 1024
                            svc.current_speed_out = write_diff / 1024
                        
                        svc.prev_io = io
                    except:
                        pass
                else:
                    svc.current_speed_in = 0
                    svc.current_speed_out = 0
            
            self.after(0, self.update_traffic_ui)
            time.sleep(1)

    def update_traffic_ui(self):
        for key, svc in self.services.items():
            txt_in = f"{svc.current_speed_in:.1f} KB/s"
            txt_out = f"{svc.current_speed_out:.1f} KB/s"
            
            if svc.lbl_speed_in: svc.lbl_speed_in.configure(text=txt_in)
            if svc.lbl_speed_out: svc.lbl_speed_out.configure(text=txt_out)

    # --- LOGIC MONITORING (DATABASE) ---
    def loop_monitor_database(self):
        while self.running:
            latency = Database.get_latency()
            self.after(0, lambda l=latency: self.update_db_ui(l))
            time.sleep(3)

    def update_db_ui(self, latency):
        if latency >= 0:
            self.lbl_db_status.configure(text="● CONNECTED", bootstyle="success")
            self.lbl_latency_val.configure(text=f"{latency} ms")
            if latency > 500: 
                self.lbl_latency_val.configure(bootstyle="danger")
            else:
                self.lbl_latency_val.configure(bootstyle="success")
        else:
            self.lbl_db_status.configure(text="● DISCONNECTED", bootstyle="danger")
            self.lbl_latency_val.configure(text="Timeout", bootstyle="danger")

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_area.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_area.see(tk.END)

    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"

if __name__ == "__main__":
    app = UnievOrchestrator()
    app.mainloop()