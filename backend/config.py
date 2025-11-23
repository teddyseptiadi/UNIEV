# backend/config.py
import os

# --- NETWORK CONFIG ---
HOST = "0.0.0.0"
PORT_OCPP = 9000
PORT_API = 8000  # <--- GANTI DARI 5000 KE 8000 (Agar tidak bentrok dengan AirPlay Mac)
PORT_OCPI = 5001

# --- SUPABASE CONFIG ---
SUPABASE_URL = "https://cshxkmpwpuywalcuugtv.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNzaHhrbXB3cHV5d2FsY3V1Z3R2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM4MTUxNDksImV4cCI6MjA3OTM5MTE0OX0.kea8dfEfanOfiUuBshbGuVsSZqSa4B2mCoIfUvjer7g"