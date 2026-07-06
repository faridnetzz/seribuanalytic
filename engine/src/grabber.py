"""Capture DIPISAH dari inferensi — kunci video MULUS multi-kamera di 1 GPU.

Masalah patah-patah: kalau `cap.read()` satu loop dengan inferensi (YOLO/FR) yang
di-serialize `gpu.lock` antar banyak kamera, read ke-blok lama menunggu giliran GPU
-> buffer jaringan HLS tak terkuras -> timestamp drift / segmen menumpuk -> video
patah-patah + sering reconnect. Makin banyak kamera/modul makin parah.

Solusi: grabber thread HANYA `cap.read()` (ringan, dipacu laju stream) lalu simpan
ke dua tempat: (a) frame TERBARU utk thread INFERENSI (melewati yang basi -> GPU
selalu proses frame paling baru & jaringan terkuras realtime), (b) buffer playout
FIFO utk thread DISPLAY (serap jitter/burst HLS -> video mulus, tak patah-patah).

Buffer playout WAJIB utk kemulusan: HLS kirim frame dalam burst di batas segmen.
Tanpa buffer (tampil "frame terbaru" saja), saat jaringan jeda display mengulang
frame yang sama lalu melompat -> video ngendat. Buffer FIFO dikuras pada laju
stabil (LIVE_FPS, di bawah laju native stream) -> playout selalu mulus.
"""
import logging
import threading
import time
from collections import deque

import cv2
import numpy as np

log = logging.getLogger("engine.grabber")


class LatestFrame:
    """Baca stream di thread sendiri: simpan frame terbaru (inferensi) + buffer
    playout FIFO (display mulus)."""

    def __init__(self, src, name, on_reconnect=None, buffer=1, skip_frozen=False):
        self.src = src
        self.name = name
        self.on_reconnect = on_reconnect
        # skip_frozen: BUANG frame BEKU (identik dgn sebelumnya = stream stall) supaya
        # tak diproses inferensi. KRUSIAL utk parkir: saat stream freeze, frame yg sama
        # diproses berulang -> kendaraan LEWAT tampak "diam" -> dwell naik -> PARKIR LIAR
        # palsu. Dgn ini, frame beku dilewati -> dwell tak naik saat freeze.
        self.skip_frozen = skip_frozen
        self._prev_sig = None
        self._frame = None
        self._seq = 0
        self._buf = deque(maxlen=max(1, buffer))   # buffer playout utk display
        self._lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._loop, daemon=True,
                         name=f"grab-{self.name}").start()
        return self

    def _open(self):
        cap = cv2.VideoCapture(self.src, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # buffer minimal -> frame selalu fresh
        except Exception:
            pass
        return cap

    def _loop(self):
        cap = self._open()
        while True:
            ok, frame = cap.read()
            if not ok:
                log.warning("[%s] stream putus, reconnect...", self.name)
                if self.on_reconnect:
                    try:
                        self.on_reconnect()
                    except Exception:
                        pass
                cap.release()
                with self._lock:
                    self._buf.clear()              # buang frame basi pra-putus
                self._prev_sig = None
                time.sleep(1)
                cap = self._open()
                continue
            # deteksi frame BEKU (stream stall): frame (nyaris) identik dgn sebelumnya
            # -> JANGAN proses (cegah dwell parkir palsu). Scene live selalu ada noise/
            # gerakan (lalu lintas/bendera) shg diff > eps; hanya freeze sejati ~0.
            if self.skip_frozen:
                sig = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (32, 32)).astype(np.int16)
                if self._prev_sig is not None and float(np.abs(sig - self._prev_sig).mean()) < 0.35:
                    continue                       # frame beku -> lewati (tak update inferensi/display)
                self._prev_sig = sig
            with self._lock:
                self._frame = frame
                self._seq += 1
                self._buf.append((self._seq, frame))  # (seq, frame) utk sinkron box

    def get(self, last_seq):
        """Frame TERBARU bila ada yang baru sejak last_seq (utk thread INFERENSI:
        proses hanya frame baru). -> (frame, seq_baru) atau (None, last_seq)."""
        with self._lock:
            if self._frame is None or self._seq == last_seq:
                return None, last_seq
            return self._frame, self._seq

    def pop_display(self):
        """(seq, frame) berikutnya dari buffer playout FIFO (utk thread DISPLAY:
        video mulus @ LIVE_FPS). (None, None) bila kosong -> tahan frame terakhir.
        `seq` dipakai utk sinkron+interpolasi bounding box ke frame ini."""
        with self._lock:
            return self._buf.popleft() if self._buf else (None, None)

    def buffered(self):
        """Jumlah frame siap-tampil di buffer playout (utk prebuffer awal)."""
        with self._lock:
            return len(self._buf)
