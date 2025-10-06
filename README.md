# Freya – Asterisk + FRITZ!Box + ARI (Docker) with n8n & local TTS/STT

**Freya** connects a **FRITZ!Box** IP phone to **Asterisk (PJSIP)**, handles calls with a **Python ARI app**, and speaks/recognizes speech locally using **Wyoming Piper** (TTS) and remote openai (STT).  
Designed to trigger/receive data from **n8n** via a simple webhook.

---

## What this project does

- Registers an IP phone on your **FRITZ!Box** and accepts inbound calls in **Asterisk**.
- Runs an **ARI** app (FastAPI) that answers, bridges audio, and can TTS/STT.
- Uses **Wyoming Piper** for fast, local **TTS** (and optional local STT).
- Provides a tiny **Dialer API** (`POST /call`) to place an outbound call and speak a message.
- Plays nicely with **n8n** via Webhook → Webhook Respond.

---

## Requirements

- A **FRITZ!Box** in your LAN (e.g., `192.168.178.1`), with an **IP phone (username/password)** created.
- Linux host with **Docker** & **Docker Compose**.
- `OPENAI_API_KEY` on the **host** 

---

## Minimal project layout (only what you need)

```
.
├── config/                    # Asterisk & app configs (mounts into the container)
│   ├── pjsip.conf.template    # <- rename to pjsip.conf and set FRITZ user/password/IP
│   ├── pjsip.conf             # (your file after renaming; do NOT commit secrets)
│   ├── extensions.conf        # dialplan: routes inbound to ARI
│   ├── http.conf              # enables Asterisk HTTP/WS (for ARI)
│   ├── ari.conf               # ARI credentials
│   ├── rtp.conf               # RTP port range
│   ├── asterisk.conf          # base Asterisk config
│   └── freya.yaml             # app settings (TTS/STT, webhook URL, etc.)
├── docker/                    
│   └── supervisord.conf       # starts Asterisk and ARI apps
├── Dockerfile                 # builds Asterisk + Python venv image
└── docker-compose.yml         # runs Asterisk/ARI and Wyoming Piper
```

> **Edit only:** `config/pjsip.conf` (renamed from the provided template) to set `<FRITZ_USER>`, `<FRITZ_PASS>`, `<FRITZ_IP>`.

---

## Quick install (Ubuntu)

```bash
https://docs.docker.com/engine/install/ubuntu/
```

---

## Prepare config

```bash
# in your project root
cp config/pjsip.conf.template config/pjsip.conf
# open config/pjsip.conf and replace placeholders:
#   <FRITZ_USER>, <FRITZ_PASS>, <FRITZ_IP> (e.g., 192.168.178.1)
```

Optional for examples:
```bash
export OPENAI_API_KEY=sk-...    # on your host shell (not required for core call handling)
```

---

## Docker Compose (copy/paste ready)

```yaml
services:
  fritz-voice-assistant:
    build:
      context: .
      dockerfile: Dockerfile
    image: fritz-voice-assistant:latest
    network_mode: "host"                     # SIP/RTP friendly (no NAT hassle)
    restart: unless-stopped
    environment:
      - OPENAI_API_KEY                       # passed through from host if set
    volumes:
      - ./config/asterisk.conf:/etc/asterisk/asterisk.conf:ro
      - ./config/pjsip.conf:/etc/asterisk/pjsip.conf:ro
      - ./config/extensions.conf:/etc/asterisk/extensions.conf:ro
      - ./config/rtp.conf:/etc/asterisk/rtp.conf:ro
      - ./config/http.conf:/etc/asterisk/http.conf:ro
      - ./config/ari.conf:/etc/asterisk/ari.conf:ro
      - ./config/freya.yaml:/opt/freya/phone/freya.yaml:ro  # app config

  wyoming-piper:
    image: rhasspy/wyoming-piper:latest
    container_name: wyoming-piper
    restart: unless-stopped
    ports:
      - "10200:10200"
    volumes:
      - /home/andi/docker-volumes/wyoming-piper:/data     # adjust path if needed
    command: --voice de_DE-ramona-low --update
```

Start it:
```bash
docker compose up -d --build
```

---

## Test the Dialer API (outbound)

```bash
curl -sS -X POST http://127.0.0.1:8099/call   -H 'Content-Type: application/json'   -d '{"callerId":"<TARGET_NUMBER>","message":"Hello from Freya! This is a test."}'
```

Inbound: call your FRITZ!Box number and watch Asterisk logs.

---

## n8n (optional, very short)

Quick run:
```bash
docker run -d --name n8n -p 5678:5678 n8nio/n8n
```

In n8n:
- Add a **Webhook** (Trigger) node (POST), copy its URL.
- Add **HTTP Request** node calling `http://localhost:8099/call` with JSON body:
  ```json
  { "callerId": "0176...", "message": "Your dynamic text here" }
  ```
- Add a **Webhook Respond** node if you want to return data immediately.

---

## Troubleshooting (Asterisk essentials)

**Enter the Asterisk CLI inside the container**
```bash
docker exec -it fritz-voice-assistant asterisk -rvvvv
```

**Reload and inspect PJSIP**
```asterisk
pjsip reload
pjsip show registrations
pjsip show endpoints
pjsip show endpoint fritz-endpoint
```

**SIP message trace / RTP trace**
```asterisk
pjsip set logger on
rtp set debug on
```

**Typical fixes**
- 401 Unauthorized on register → check `<FRITZ_USER>/<FRITZ_PASS>/<FRITZ_IP>` in `config/pjsip.conf`, confirm IP phone is enabled in FRITZ!Box.
- No audio → ensure `Answer()` before `Stasis()` in `extensions.conf`; endpoint has `allow=alaw,ulaw`; check `rtp set debug on` shows “Got/Sent RTP”.
- Dialer 500 “Allocation failed” → use a valid endpoint and/or AOR contact (e.g., `contact=sip:<FRITZ_IP>:5060` in AOR, or dial `PJSIP/fritz-endpoint/sip:{number}@<FRITZ_IP>`).

**Exit CLI**
```asterisk
exit
```

---

## License

Open Source (**MIT**). 

---

## About

Built to connect a **FRITZ!Box** with **n8n** via **Asterisk ARI** – with fast, local **TTS** using Piper.  
Created by **Andreas** (Hobby Developer).