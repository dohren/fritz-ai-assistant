#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio, socket, struct, time, audioop, random
from wyoming.client import AsyncTcpClient
from wyoming.tts import Synthesize
from wyoming.audio import AudioChunk
from config import cfg

C = cfg()
WYOMING_HOST = C["wyoming"]["host"]
WYOMING_TTS_PORT = int(C["wyoming"]["tts_de"])

# --- einfacher RTP-Zustand (pro Call) ---
_RTP_STATE = {"ssrc": None, "seq": 0, "ts": 0}

def reset_tts_rtp_state():
    """Pro neuem Call aufrufen: neue SSRC, zufälliger Startwert für seq/ts."""
    _RTP_STATE["ssrc"] = random.getrandbits(32)
    _RTP_STATE["seq"]  = random.randint(0, 65535)
    _RTP_STATE["ts"]   = random.randint(0, 2**31 - 1)

async def _tts_pcm16_16k(text: str) -> bytes:
    pcm = bytearray()
    async with AsyncTcpClient(WYOMING_HOST, WYOMING_TTS_PORT) as c:
        await c.write_event(Synthesize(text=text).event())
        while True:
            ev = await c.read_event()
            if not ev:
                break
            if ev.type == "audio-chunk":
                pcm.extend(AudioChunk.from_event(ev).audio)
            elif ev.type == "audio-stop":
                break
    return bytes(pcm)

def send_tts_to_rtp(
    text: str,
    dst_ip: str,
    dst_port: int,
    sock: socket.socket | None = None,
    stop_event=None,        # <— NEU: optionales Cancel-Flag
) -> int:
    """
    Erzeugt PCM16@16k mit Wyoming/Piper, wandelt zu 8k μ-law und sendet
    in RTP-PCMU (PT=0) 20ms-Paketen. Hält seq/ts/ssrc über Aufrufe hinweg.
    Wenn 'sock' übergeben wird, wird genau dieser UDP-Socket zum Senden benutzt
    (z.B. der gleiche wie der Empfangs-Socket), andernfalls wird ein eigener
    UDP-Socket kurzfristig erstellt.
    Return: gesendete Paketanzahl.
    """
    if not dst_ip or not dst_port:
        print("[TTS] no dst specified")
        return 0

    # Vorab-Abbruch (falls zwischen say() und Synthese schon gecancelt wurde)
    if stop_event and stop_event.is_set():
        print("[TTS] cancelled before synth")
        return 0

    print(f"[TTS] dst={dst_ip}:{dst_port} text='{text[:60]}'")
    pcm16_16k = asyncio.run(_tts_pcm16_16k(text))
    if not pcm16_16k:
        print("[TTS] no audio from wyoming")
        return 0

    # Abbruch-Check vor der Konvertierung (spart CPU)
    if stop_event and stop_event.is_set():
        print("[TTS] cancelled before convert")
        return 0

    # 16k -> 8k, dann μ-law (16bit -> ulaw bytes)
    pcm16_8k, _ = audioop.ratecv(pcm16_16k, 2, 1, 16000, 8000, None)
    ulaw = audioop.lin2ulaw(pcm16_8k, 2)
    print(f"[TTS] bytes_ulaw={len(ulaw)}")

    # initialisiere RTP-State falls nötig
    if _RTP_STATE["ssrc"] is None:
        reset_tts_rtp_state()

    RTP_PT = 0
    TS_INC = 160   # 20 ms @8k -> 160 timestamp increment
    ssrc   = _RTP_STATE["ssrc"]
    seq    = _RTP_STATE["seq"]
    ts     = _RTP_STATE["ts"]

    s = sock or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    close_after = (sock is None)
    step = 160   # 20ms chunks @8k -> 160 bytes
    pkt_count = 0
    first_pkt = True

    # sende nur volle step-chunks (einfacher und kompatibler)
    for off in range(0, len(ulaw) - step + 1, step):
        # Abbruch mitten im Senden
        if stop_event and stop_event.is_set():
            print("[TTS] stopped early")
            break

        chunk = ulaw[off:off+step]
        # RTP header: V=2, P=0, X=0, M=marker for first packet, PT, seq, ts, ssrc
        marker = 0x80 if first_pkt else 0x00
        first_pkt = False
        b1 = 0x80
        b2 = marker | RTP_PT
        hdr = struct.pack("!BBHII", b1, b2, seq & 0xFFFF, ts & 0xFFFFFFFF, ssrc & 0xFFFFFFFF)
        try:
            s.sendto(hdr + chunk, (dst_ip, int(dst_port)))
        except Exception as e:
            print("[TTS] send error:", e)
            break

        pkt_count += 1
        seq = (seq + 1) & 0xFFFF
        ts  = (ts + TS_INC) & 0xFFFFFFFF
        time.sleep(0.02)  # 20 ms pacing

    # speichere State zurück
    _RTP_STATE["seq"] = seq
    _RTP_STATE["ts"]  = ts
    if close_after:
        s.close()
    print(f"[TTS] sent {pkt_count} RTP packets to {dst_ip}:{dst_port}")
    return pkt_count
