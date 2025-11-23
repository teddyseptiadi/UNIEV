# backend/billing_engine.py
import logging
from datetime import datetime

# Konstanta Emisi (kg CO2 per kWh). Mobil Bensin ~0.2 kg/km. EV ~0.
# Asumsi penghematan per kWh.
CARBON_SAVING_FACTOR = 0.85 

logger = logging.getLogger("BILLING")

class BillingCalculator:
    def __init__(self, supabase_client):
        self.db = supabase_client

    def calculate_final_bill(self, charger_id, kwh_usage, duration_minutes):
        bill_details = {
            "cost_energy": 0, "cost_parking": 0, "cost_session": 0, "cost_idle": 0,
            "subtotal": 0, "tax_amount": 0, "total_amount": 0, "tariff_name": "Unknown",
            "is_peak_hour": False 
        }

        if not self.db: return bill_details

        try:
            # 1. Ambil Tarif
            charger_data = self.db.table("chargers").select("tariff_id, tariffs(*)").eq("charger_id", charger_id).execute()
            if not charger_data.data or not charger_data.data[0].get('tariffs'):
                return bill_details # Return kosong/default

            tariff = charger_data.data[0]['tariffs']
            bill_details["tariff_name"] = tariff['name']
            
            # --- [NEW] DYNAMIC PEAK HOUR LOGIC (Module 2.2) ---
            # Cek jam sekarang. Jika jam 17 - 22, naikkan harga kWh
            current_hour = datetime.now().hour
            base_price_kwh = float(tariff.get('price_kwh', 0))
            
            if 17 <= current_hour < 22:
                final_price_kwh = base_price_kwh * 1.5 # Peak Multiplier
                bill_details["is_peak_hour"] = True
                bill_details["tariff_name"] += " (PEAK RATE)"
            else:
                final_price_kwh = base_price_kwh

            # 2. Hitung
            bill_details["cost_energy"] = float(kwh_usage) * final_price_kwh
            bill_details["cost_parking"] = float(duration_minutes) * float(tariff.get('price_time_min', 0))
            bill_details["cost_session"] = float(tariff.get('price_session', 0))
            
            # Idle Fee Logic
            if duration_minutes > tariff.get('grace_period_min', 15): 
                # Logic sederhana: jika durasi total > grace period, anggap idle (perlu disempurnakan dengan status charger)
                # Di real world, idle dihitung setelah status 'Finishing' tapi kabel masih colok
                pass 

            # 3. Tax & Total
            subtotal = bill_details["cost_energy"] + bill_details["cost_parking"] + bill_details["cost_session"]
            tax = subtotal * (float(tariff.get('tax_percentage', 0)) / 100)
            
            bill_details["subtotal"] = round(subtotal, 2)
            bill_details["tax_amount"] = round(tax, 2)
            bill_details["total_amount"] = round(subtotal + tax, 2)
            
            return bill_details

        except Exception as e:
            logger.error(f"Billing Error: {e}")
            return bill_details

    def calculate_carbon_saved(self, kwh_usage):
        return round(kwh_usage * CARBON_SAVING_FACTOR, 2)