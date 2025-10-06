import requests
from config import cfg

C = cfg()
N8N_WEBHOOK = (C.get("n8n", {}) or {}).get(
    "webhook_url",
    "http://localhost:5678/webhook/on_message" 
)

def process_text(text: str, caller: str):
    payload = {"caller": caller, "text": text}
    r = requests.post(N8N_WEBHOOK, json=payload, timeout=10)
    r.raise_for_status()
    try:
        data = r.json()
        return data.get("reply", str(data))
    except Exception:
        return r.text
