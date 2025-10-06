import asyncio
from wyoming.client import AsyncTcpClient
from wyoming.audio import AudioStart, AudioChunk, AudioStop
from wyoming.asr import Transcribe, Transcript  # ← wichtig
from config import cfg

async def _transcribe_async(pcm16_16k: bytes, lang: str) -> str:
    if not pcm16_16k:
        return ""

    C = cfg()  # cached – billig
    wyoming_host = C["wyoming"]["host"]
    wyoming_port = int(C["wyoming"]["asr_de"])

    async with AsyncTcpClient(wyoming_host, wyoming_port) as c:
        # saubere Events senden
        await c.write_event(Transcribe(language=lang).event())
        await c.write_event(AudioStart(rate=16000, width=2, channels=1).event())

        step = 640  # 20ms @16kHz, 2 Bytes pro Sample, 1 Kanal
        for off in range(0, len(pcm16_16k), step):
            chunk = pcm16_16k[off:off+step]
            await c.write_event(
                AudioChunk(rate=16000, width=2, channels=1, timestamp=None, audio=chunk).event()
            )

        await c.write_event(AudioStop().event())

        # Antwort sauber parsen
        while True:
            ev = await c.read_event()
            if not ev:
                return ""
            if ev.type == "transcript":
                return Transcript.from_event(ev).text or ""

def transcribe_segment(pcm16_16k: bytes, lang: str = "de") -> str:
    # Wrapper für Sync-Aufruf
    return asyncio.run(_transcribe_async(pcm16_16k, lang))
