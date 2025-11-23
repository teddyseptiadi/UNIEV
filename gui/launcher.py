import asyncio
import threading
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import time
import os
import sys
import subprocess
import psutil
import socket
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- Ngrok Imports ---
try:
    from pyngrok import ngrok
    from pyngrok.exception import PyngrokNgrokInstallError, PyngrokSecurityError
except ImportError:
    messagebox.showwarning("Ngrok Warning", "Library 'pyngrok' tidak ditemukan. Fitur Ngrok akan dinonaktifkan.")
    ngrok = None
    PyngrokNgrokInstallError = Exception
    PyngrokSecurityError = Exception

# --- TTK Bootstrap Setup (Assuming installed) ---
try:
    import ttkbootstrap as tb
    from ttkbootstrap.constants import *
except ImportError:
    import tkinter.ttk as tb
    from tkinter.constants import *

# --- Path & Config Setup ---
current_dir = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(current_dir)
sys.path.insert(0, ROOT_DIR)

try:
    from backend import config
    HOST = getattr(config, "HOST", "0.0.0.0")
    PORT = getattr(config, "OCPP_PORT", 9000)
except ImportError:
    HOST = "0.0.0.0"
    PORT = 9000

# --- GLOBAL STATE & EXECUTORS ---
active_processes = {}
db_executor = ThreadPoolExecutor(max_workers=3) 

# --- HELPER FUNCTIONS ---
def log_message(text, log_area):
    timestamp = datetime.now().strftime("%H:%M:%S")
    try:
        log_area.insert(tk.END, f"[{timestamp}] {text}\n")
        log_area.see(tk.END)
    except:
        pass

# Fungsi yang akan dijalankan oleh subprocess
def run_process_async(script_name, prefix, log_area):
    script_path = os.path.join(ROOT_DIR, 'backend', script_name)
    try:
        process = subprocess.Popen(
            [sys.executable, "-u", script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        active_processes[prefix] = process
        log_message(f"🚀 {prefix} Server Aktif (PID: {process.pid})", log_area)
        
        for line in iter(process.stdout.readline, ''):
            log_message(f"[{prefix}] {line.strip()}", log_area)
        
        process.wait()
        
    except Exception as e:
        log_message(f"❌ {prefix} CRASH: {e}", log_area)
    finally:
        if prefix in active_processes:
            del active_processes[prefix]
        log_message(f"🛑 {prefix} Server Stopped.", log_area)


# --- MAIN GUI CLASS ---
class UnievLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("UNIEV Launcher (OCPP/API/Ngrok)")
        self.geometry("950x700")

        self.server_port = PORT
        self.ngrok_tunnel = None
        self.auth_token = "YOUR_NGROK_AUTH_TOKEN"
        
        self.create_widgets()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # Start background monitoring loop
        self.after(1000, self.update_status_loop)

    def create_widgets(self):
        main_frame = tb.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- 1. NGrok / External Panel ---
        ngrok_frame = ttk.Labelframe(main_frame, text=" External Connectivity ", padding=10)
        ngrok_frame.pack(fill=tk.X, pady=(0, 15))

        tb.Label(ngrok_frame, text=f"OCPP Port: {self.server_port}").pack(side=tk.LEFT, padx=5)
        
        # Status
        tb.Label(ngrok_frame, text="| Ngrok Status:").pack(side=tk.LEFT, padx=15)
        self.lbl_ngrok_status = tb.Label(ngrok_frame, text="OFFLINE", bootstyle="danger")
        self.lbl_ngrok_status.pack(side=tk.LEFT)
        
        self.btn_ngrok_toggle = tb.Button(ngrok_frame, text="Start Ngrok Tunnel", command=self.toggle_ngrok_tunnel, bootstyle="warning")
        self.btn_ngrok_toggle.pack(side=tk.RIGHT)
        
        self.lbl_ngrok_url = tb.Label(ngrok_frame, text="WSS URL: Not Running", foreground="gray")
        self.lbl_ngrok_url.pack(fill=tk.X, padx=5, pady=(5,0))

        # --- 2. Service Control Panel ---
        ctrl_frame = ttk.Labelframe(main_frame, text=" Backend Services ", padding=10)
        ctrl_frame.pack(fill=tk.X)

        self.service_info = {
            "OCPP": {"script": "ocpp_server.py", "status_label": None, "pid_label": None, "pid": None, "button": None},
            "API": {"script": "main_api.py", "status_label": None, "pid_label": None, "pid": None, "button": None},
            "OCPI": {"script": "ocpi_service.py", "status_label": None, "pid_label": None, "pid": None, "button": None},
        }

        # Create service rows
        for prefix, data in self.service_info.items():
            row = tb.Frame(ctrl_frame)
            row.pack(fill=tk.X, pady=5)
            
            # [FIX A] Button Creation: Store direct reference
            btn = tb.Button(row, text=f"Start {prefix}", command=lambda p=prefix, s=data['script']: self.toggle_process(p, s))
            btn.pack(side=tk.LEFT, padx=(5, 10), ipadx=10)
            data['button'] = btn # STORE DIRECT REFERENCE HERE
            
            tb.Label(row, text=f"{prefix} Status:").pack(side=tk.LEFT, padx=10)
            
            # Status Lamp
            data['status_label'] = tb.Label(row, text="● STOPPED", bootstyle="danger")
            data['status_label'].pack(side=tk.LEFT, padx=5)

            # PID
            tb.Label(row, text="PID:").pack(side=tk.LEFT, padx=(30, 5))
            data['pid_label'] = tb.Label(row, text="---", font=("Consolas", 10))
            data['pid_label'].pack(side=tk.LEFT)
        
        # --- 3. Log Viewer ---
        tb.Label(main_frame, text="Real-time Process Logs:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(15, 5))
        self.log_area = tk.Text(main_frame, height=20, bg="#1a1a1a", fg="#00ff00", font=("Consolas", 9), state='normal')
        self.log_area.pack(fill=tk.BOTH, expand=True)

    # --- NGrok Logic ---
    def toggle_ngrok_tunnel(self):
        if ngrok is None:
            messagebox.showerror("Error", "Library 'pyngrok' tidak ditemukan.")
            return

        if self.ngrok_tunnel is None:
            # START TUNNEL
            try:
                if "OCPP" not in active_processes:
                    messagebox.showerror("Error", "OCPP Server (Port 9000) harus aktif sebelum Ngrok.")
                    return
                
                self.ngrok_tunnel = ngrok.connect(self.server_port, proto="tcp")
                
                public_url = self.ngrok_tunnel.public_url.replace("tcp://", "wss://")

                self.lbl_ngrok_url.config(text=f"WSS URL: {public_url}", foreground="green")
                self.lbl_ngrok_status.config(text="ONLINE", bootstyle="success")
                self.btn_ngrok_toggle.config(text="Stop Ngrok Tunnel", bootstyle="danger")
                messagebox.showinfo("Success", f"Ngrok Tunnel Aktif:\n{public_url}")
                log_message(f"🌐 Ngrok Tunnel Started: {public_url}", self.log_area)
                
            except PyngrokNgrokInstallError:
                messagebox.showerror("Error", "Ngrok client belum terinstal.")
            except PyngrokSecurityError:
                 messagebox.showerror("Error", "Ngrok AUTH TOKEN hilang.")
            except Exception as e:
                messagebox.showerror("Error", f"Gagal membuat tunnel: {e}")
                self.ngrok_tunnel = None
        else:
            # STOP TUNNEL
            ngrok.disconnect(self.ngrok_tunnel.public_url)
            self.ngrok_tunnel = None
            self.lbl_ngrok_url.config(text="WSS URL: Not Running", foreground="gray")
            self.lbl_ngrok_status.config(text="OFFLINE", bootstyle="danger")
            self.btn_ngrok_toggle.config(text="Start Ngrok Tunnel", bootstyle="warning")
            log_message("🌐 Ngrok Tunnel Stopped.", self.log_area)


    # --- Process Management Logic ---
    def toggle_process(self, prefix, script_name):
        if prefix in active_processes and active_processes[prefix].poll() is None:
            # STOP Process
            active_processes[prefix].terminate() 
        else:
            # START Process in a new thread
            threading.Thread(target=run_process_async, args=(script_name, prefix, self.log_area), daemon=True).start()

    # --- Monitoring Loop ---
    def update_status_loop(self):
        # [FINAL FIX] Menggunakan referensi langsung (data['button'])
        for prefix, data in self.service_info.items():
            process = active_processes.get(prefix)
            btn_widget = data['button'] # Retrieve the stored button reference
            
            if process and process.poll() is None:
                # Running
                data['status_label'].config(text="● RUNNING", bootstyle="success")
                data['pid_label'].config(text=str(process.pid))
                data['pid'] = process.pid
                btn_widget.config(text=f"Stop {prefix}", bootstyle="danger") 
            else:
                # Stopped
                data['status_label'].config(text="● STOPPED", bootstyle="danger")
                data['pid_label'].config(text="---")
                data['pid'] = None
                btn_widget.config(text=f"Start {prefix}", bootstyle="success") 
                
        self.after(1000, self.update_status_loop) # Loop every second

    # --- Cleanup ---
    def on_close(self):
        # Stop all running subprocesses and Ngrok tunnel
        if self.ngrok_tunnel:
            self.toggle_ngrok_tunnel() 
        for prefix in list(active_processes.keys()):
            if prefix in active_processes and active_processes[prefix].poll() is None:
                 active_processes[prefix].terminate()

        self.quit()
        self.destroy()

if __name__ == "__main__":
    root = UnievLauncher()
    root.mainloop()