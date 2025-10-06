#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json, base64, time, requests, socket, threading, audioop, queue
from websocket import create_connection, WebSocketTimeoutException
from urllib.parse import unquote

from ari_stt_openai import transcribe_segment
from ari_webhook import process_text
from ari_tts import send_tts_to_rtp
from ari_segmenter import Segmenter, SegmenterConfig
from ari_rtpreceiver import RtpReceiver
from config import cfg
import uuid
import os

# ---- Konfig zentral aus YAML ----
C = cfg()

ARI_BASE = C["ari"]["base"]
API_PORT = int(C.get("api_port", 8099))
ARI_USER = C["ari"]["user"]
ARI_PASS = C["ari"]["pass"]
APP      = C["ari"]["app"]

EXT_HOST_IP   = C["media"]["ext_host_ip"]
EXT_HOST_PORT = int(C["media"]["ext_host_port"])

ENDPOINT_TEMPLATE = C["dialer"]["endpoint_template"]
DIALER_TIMEOUT_S = int(C["dialer"]["timeout_s"])

WYOMING_TTS_DE = int(C["wyoming"]["tts_de"])
LANG           = C["media"]["lang"]
WELCOME        = C["media"]["welcome"]

OPENAI_STT_MODEL = C["openai"]["stt_model"]
WYOMING_HOST     = C["wyoming"]["host"]
WYOMING_ASR_DE   = int(C["wyoming"]["asr_de"])

# ---------- globaler Zustand ----------
segment_queue: "queue.Queue[bytes]" = queue.Queue()
ext_id = None
bridge_id = None
caller_id = None
rtp_receiver = None
call_alive = False       
segmenter_instance = None
TTS_DST_IP = None
TTS_DST_PORT = None
caller_number = None



# ---------- ARI-Helper ----------
def ari(path, method="GET", **kw):
    f = getattr(requests, method.lower())
    r = f(ARI_BASE + path, auth=(ARI_USER, ARI_PASS), timeout=5, **kw)
    r.raise_for_status()
    return r.json() if r.text else {}

def get_var(ch_id, var):
    r = requests.get(f"{ARI_BASE}/channels/{ch_id}/variable",
                     params={"variable": var}, auth=(ARI_USER, ARI_PASS), timeout=5)
    r.raise_for_status(); return r.json().get("value")

def is_caller(ev):
    ch = ev.get("channel", {})
    tech = (ch.get("channeltype") or "").upper()
    name = (ch.get("name") or ""); caller = ch.get("caller", {}).get("number","")
    return tech in ("PJSIP", "SIP", "DAHDI") or caller or name.startswith(("PJSIP/","SIP/","DAHDI/"))

def wait_channel(id, tries=100, delay=0.05):
    url = f"{ARI_BASE}/channels/{id}"
    for _ in range(tries):
        r = requests.get(url, auth=(ARI_USER, ARI_PASS), timeout=2)
        if r.status_code == 200: return True
        time.sleep(delay)
    return False

def safe_add(bridge, ch):
    for _ in range(10):
        try:
            ari(f"/bridges/{bridge}/addChannel", "POST", params={"channel": ch})
            return True
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (400, 404):
                time.sleep(0.05); continue
            raise
    return False

# ---------- Cleanup ----------
def cleanup_call():
    global ext_id, bridge_id, caller_id, caller_number, call_alive 
    # Bridge aufräumen
    try:
        if bridge_id:
            requests.delete(f"{ARI_BASE}/bridges/{bridge_id}", auth=(ARI_USER, ARI_PASS), timeout=2)
    except Exception:
        pass

    # Segmenter flush, falls noch Audio drin
    try:
        if segmenter_instance and segmenter_instance.buf:
            seg = bytes(segmenter_instance.buf)
            segmenter_instance.buf.clear()
            if len(seg) > 32000:
                print(f"[SEG] --> FLUSH OUT: {len(seg)} bytes")
                segment_queue.put(seg)
    except Exception:
        pass

    # Queue leeren
    try:
        while not segment_queue.empty():
            segment_queue.get_nowait()
    except Exception:
        pass

    ext_id = bridge_id = caller_id = None
    caller_number = None  
    call_alive = False
    print("[ARI] cleaned up.")

# ---------- TTS Helper: über denselben Socket senden wie Empfang ----------
def say(text: str):
    if not (TTS_DST_IP and TTS_DST_PORT and rtp_receiver and rtp_receiver._sock):
        print("[TTS] no dst/socket available")
        return
    # Nicht blockierend: TTS in Thread schicken
    threading.Thread(
        target=send_tts_to_rtp,
        args=(text, TTS_DST_IP, TTS_DST_PORT),
        kwargs={"sock": rtp_receiver._sock},  # <— gleicher UDP-Socket wie Receiver!
        daemon=True,
    ).start()

# ---------- Call-Start ----------
def on_start(ev):
    global ext_id, bridge_id, caller_id, call_alive, TTS_DST_IP, TTS_DST_PORT
    if not is_caller(ev):
        return
    caller_id = ev["channel"]["id"]
    print(f"[ARI] caller in: {caller_id}")

    caller_number = (ev.get("channel", {}).get("caller", {}) or {}).get("number") or ""
    if not caller_number:
        caller_number = str(uuid.uuid4())
    print(f"[ARI] caller in: chan={caller_id}, number={caller_number}")

    bridge_id = ari("/bridges", "POST", params={"type": "mixing"})["id"]
    safe_add(bridge_id, caller_id)

    ext = ari("/channels/externalMedia", "POST", params={
        "app": APP,
        "external_host": f"{EXT_HOST_IP}:{EXT_HOST_PORT}",
        "format": "ulaw",
        "direction": "both",
    })
    ext_id = ext["id"]
    time.sleep(0.1)
    if not wait_channel(ext_id) or not safe_add(bridge_id, ext_id):
        print(f"[ARI] externalMedia {ext_id} nicht bereit")
        return

    call_alive = True
    print("[ARI] call active, RTP already running")

    ip  = get_var(ext_id, "UNICASTRTP_LOCAL_ADDRESS")
    port= int(get_var(ext_id, "UNICASTRTP_LOCAL_PORT") or 0)
    TTS_DST_IP, TTS_DST_PORT = ip, port
    print(f"[TTS] target set {TTS_DST_IP}:{TTS_DST_PORT}")

    args = ev.get("args") or []
    init_tts_enc = (args[0] if args else "").strip()
    init_tts = unquote(init_tts_enc)

    
    if init_tts:
        time.sleep(3)
        say(init_tts) 
    else:
        say(WELCOME)     


def bridge_has_channel(bridge_id: str, ch_id: str) -> bool:
    try:
        br = ari(f"/bridges/{bridge_id}")
        return any(c.get("id") == ch_id for c in br.get("channels", []))
    except Exception:
        return False

def ensure_ext_in_bridge():
    if bridge_id and ext_id and not bridge_has_channel(bridge_id, ext_id):
        print("[BRIDGE] externalMedia missing -> re-adding")
        try:
            ari(f"/bridges/{bridge_id}/addChannel", "POST", params={"channel": ext_id})
        except Exception as e:
            print("[BRIDGE] re-add failed:", e)

# ---------- Event-Loop ----------
def main():
    # Receiver dauerhaft starten
    seg = Segmenter(
        on_segment=lambda seg_bytes: segment_queue.put(seg_bytes),
        cfg=SegmenterConfig(silence_ms=500, rms_thresh=400, min_bytes=24000)
    )
    global rtp_receiver, segmenter_instance
    segmenter_instance = seg
    rtp_receiver = RtpReceiver(ip=EXT_HOST_IP, port=EXT_HOST_PORT, segmenter=seg)
    rtp_receiver.start()
    print("[RTP-IN] permanent receiver started")

    auth = base64.b64encode(f"{ARI_USER}:{ARI_PASS}".encode()).decode()
    ws = create_connection(
        f"ws://127.0.0.1:8088/ari/events?api_key={ARI_USER}:{ARI_PASS}&app={APP}&subscribeAll=true",
        header=[f"Authorization: Basic {auth}"]
    )
    ws.settimeout(0.1)
    print("[ARI] connected; waiting for calls...")

    try:
        while True:
            try:
                ev = json.loads(ws.recv())
                if ev.get("type") == "StasisStart" and ev.get("application") == APP:
                    on_start(ev)
                elif ev.get("type") in ("ChannelHangupRequest", "ChannelDestroyed", "StasisEnd"):
                    ch_id = ev.get("channel", {}).get("id")
                    if caller_id and ch_id == caller_id:
                        print("[ARI] caller hung up/destroyed.")
                        cleanup_call()
            except WebSocketTimeoutException:
                pass
            except Exception as e:
                print("[ARI] WS error:", e)

            # Segmente verarbeiten nur wenn Call aktiv
            if call_alive and not segment_queue.empty():
                seg = segment_queue.get()
                if len(seg) < 32000:
                    continue
                t0 = time.time()
                text_in = transcribe_segment(seg, lang=LANG)
                print(f"[JOB] stt_done in {(time.time()-t0)*1000:.0f}ms text_in={text_in!r}")
                if not text_in:
                    continue

                print(f"[ASR][{caller_number}] {text_in!r}")
                text_out = process_text(text_in, caller=caller_number)

                print(f"[AGENT] {text_out!r}")
                if TTS_DST_IP and TTS_DST_PORT:
                    ensure_ext_in_bridge()
                    print(f"[TTS] send to {TTS_DST_IP}:{TTS_DST_PORT} -> '{text_out[:60]}'")
                    say(text_out)

            time.sleep(0.003)
    finally:
        ws.close()

if __name__ == "__main__":
    main()
