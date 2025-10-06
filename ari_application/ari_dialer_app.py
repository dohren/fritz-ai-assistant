#!/usr/bin/env python3
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn
from urllib.parse import quote
from config import cfg

# ---------- Konfig aus YAML ----------
C = cfg()
ARI_BASE = C["ari"]["base"]
ARI_USER = C["ari"]["user"]
ARI_PASS = C["ari"]["pass"]
APP      = C["ari"]["app"]

ENDPOINT_TEMPLATE = C["dialer"]["endpoint_template"]
DIALER_TIMEOUT_S  = int(C["dialer"]["timeout_s"])
API_PORT          = int(C.get("api_port", 8099))

# ---------- Dialer-Klasse ----------
class AriDialer:
    def __init__(self, base: str, user: str, pwd: str, app: str, endpoint_template: str):
        self.base = base.rstrip("/")
        self.auth = (user, pwd)
        self.app  = app
        self.endpoint_template = endpoint_template

    def call_and_say(self, number: str, message: str, timeout_s: int | None = None) -> dict:
        if not number or not message:
            raise ValueError("number und message dürfen nicht leer sein")

        endpoint = self.endpoint_template.format(number=number)
        params = {
            "endpoint": endpoint,
            "app": self.app,
            "appArgs": quote(message, safe=""),  # wird in der ARI-App per unquote(...) zurückgewonnen
            "callerId": number,
            "timeout": timeout_s or DIALER_TIMEOUT_S,
        }
        r = requests.post(
            f"{self.base}/channels",
            params=params,
            json={},          # leerer Body verhindert 500er bei manchen ARI-Versionen
            auth=self.auth,
            timeout=5,
        )
        if r.status_code not in (200, 202):
            raise RuntimeError(f"ARI create failed: {r.status_code} | {r.reason} | {r.text}")
        return r.json() if r.text else {"status": "ok"}

# ---------- HTTP für n8n / externe Trigger ----------
class CallRequest(BaseModel):
    callerId: str = Field(..., description="Zielrufnummer (E.164 oder passend zu deinem Dialplan)")
    message:  str = Field(..., description="Text, der gesprochen werden soll")

app = FastAPI(title="Freya Dialer API", version="1.0")
dialer = AriDialer(ARI_BASE, ARI_USER, ARI_PASS, APP, ENDPOINT_TEMPLATE)

@app.post("/call")
def call(req: CallRequest):
    try:
        res = dialer.call_and_say(req.callerId.strip(), req.message.strip())
        return {"ok": True, "ari": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)
