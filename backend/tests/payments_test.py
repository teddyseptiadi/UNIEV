import requests

API="http://127.0.0.1:8000"

def run():
    r1 = requests.post(f"{API}/api/payments/providers", json={
        "provider":"xendit","environment":"development","api_key":"XENDIT-KEY-123456","name":"Xendit Dev","cpo_id":"CPO-001"
    })
    r2 = requests.post(f"{API}/api/payments/intent", json={
        "provider":"xendit","amount":75000.0,"description":"Test Payment","cpo_id":"CPO-001","charger_id":"SIM-001","user_id":"USR-001"
    })
    r3 = requests.get(f"{API}/api/payments/providers")
    print(r1.json())
    print(r2.json())
    try:
        print(r3.json())
    except Exception:
        print(r3.text)

if __name__ == '__main__':
    run()