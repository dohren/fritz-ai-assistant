# /opt/freya/phone/ari_stt_openai.py
import io, wave, os
from openai import OpenAI
from config import cfg

C = cfg()
OPENAI_STT_MODEL = C["openai"]["stt_model"]                              # z.B. gpt-4o-mini-transcribe

_client = OpenAI() 

def _pcm16_16k_bytes_to_wav_bytes(pcm: bytes) -> bytes:
    """Wrappt PCM16/16k/mono in ein gültiges WAV-Container-Byteobjekt."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)      # 16-bit
        wf.setframerate(16000)
        wf.writeframes(pcm)
    return buf.getvalue()

def transcribe_segment(pcm16_16k: bytes, lang: str = "de") -> str:
    if not pcm16_16k:
        return ""

    wav_bytes = _pcm16_16k_bytes_to_wav_bytes(pcm16_16k)

    resp = _client.audio.transcriptions.create(
        model=OPENAI_STT_MODEL,                                  # ⬅️ jetzt vorhanden
        file=("audio.wav", io.BytesIO(wav_bytes), "audio/wav"),
        language=lang or None
    )
    return (getattr(resp, "text", "") or "").strip()

