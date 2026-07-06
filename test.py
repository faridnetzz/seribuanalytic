"""
Stream CCTV (lewat proxy lokal) + deteksi tumpukan sampah real-time (YOLO best.pt),
playback MULUS.

Arsitektur anti-patah:
- Thread baca : ambil frame -> jalankan YOLO -> gambar kotak -> taruh di buffer.
- Loop tampil : ambil frame dari buffer dengan laju stabil (~25 fps).
Deteksi dilakukan di thread baca, jadi loop tampilan tetap halus.

Pastikan proxy.py SUDAH jalan di terminal lain.
"""
import cv2
import time
import threading
from collections import deque
from ultralytics import YOLO

STREAM    = "http://127.0.0.1:8787/playlist"
MODEL     = "best.pt"
CONF      = 0.40       # ambang keyakinan; 0.25 ngeloloskan kotak raksasa skor-rendah, 0.40 lebih bersih
FPS       = 25
PREBUFFER = 50         # ~2 dtk buffer awal
MAXBUF    = 125        # ~5 dtk buffer (delay) demi kemulusan

model = YOLO(MODEL)
buf = deque(maxlen=MAXBUF)
lock = threading.Lock()
stop = False


def reader():
    """Baca frame -> deteksi sampah -> gambar kotak -> masukkan buffer."""
    global stop
    cap = cv2.VideoCapture(STREAM, cv2.CAP_FFMPEG)
    while not stop:
        ok, frame = cap.read()
        if not ok:
            print("stream putus, reconnect...")
            cap.release()
            time.sleep(1)
            cap = cv2.VideoCapture(STREAM, cv2.CAP_FFMPEG)
            continue
        # deteksi + anotasi (kotak + label "garbage <skor>")
        res = model.predict(frame, conf=CONF, device=0, verbose=False)[0]
        annotated = res.plot()
        n = len(res.boxes)
        if n:
            cv2.putText(annotated, f"SAMPAH TERDETEKSI: {n}", (15, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        with lock:
            buf.append(annotated)
    cap.release()


t = threading.Thread(target=reader, daemon=True)
t.start()

print("memuat model & mengisi buffer awal...")
while len(buf) < PREBUFFER and not stop:
    time.sleep(0.05)
print("mulai tampil. Tekan 'q' untuk keluar.")

frame_interval = 1.0 / FPS
next_t = time.time()
last = None
while True:
    with lock:
        frame = buf.popleft() if buf else None
    if frame is not None:
        last = frame
    if last is not None:
        cv2.imshow("CCTV Lorong Pasar Smep - Deteksi Sampah", last)

    next_t += frame_interval
    delay = max(1, int((next_t - time.time()) * 1000))
    if cv2.waitKey(delay) & 0xFF == ord("q"):
        break

stop = True
t.join(timeout=2)
cv2.destroyAllWindows()
