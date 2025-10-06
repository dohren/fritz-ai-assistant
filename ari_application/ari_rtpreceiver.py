import socket, threading, audioop

class RtpReceiver:
    """
    Hört auf RTP (Payload-Type=0, μ-law/8kHz), wandelt nach PCM16@16k
    und gibt Frames an einen Segmenter weiter (feed20ms).
    """
    def __init__(self, ip="127.0.0.1", port=12000, segmenter=None):
        self.ip = ip
        self.port = port
        self.segmenter = segmenter
        self._stop = False
        self._sock = None
        self._thread = None

    def start(self):
        self._stop = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        self._stop = True
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None
        self._thread = None

    def _loop(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.ip, self.port))
        self._sock = s
        buf8k = bytearray()
        print(f"[RTP-IN] listening {self.ip}:{self.port} (PT=0 μ-law)")

        while not self._stop:
            try:
                pkt, _ = s.recvfrom(2048)
            except OSError:
                break
            if len(pkt) < 12:
                continue
            ulaw = pkt[12:]  # RTP Header 12 Bytes
            pcm16_8k = audioop.ulaw2lin(ulaw, 2)
            buf8k.extend(pcm16_8k)
            while len(buf8k) >= 320:  # 20ms @ 8kHz, 16bit = 320 Bytes
                frame8k = bytes(buf8k[:320])
                del buf8k[:320]
                frame16k, _ = audioop.ratecv(frame8k, 2, 1, 8000, 16000, None)
                if self.segmenter:
                    self.segmenter.feed20ms(frame16k)