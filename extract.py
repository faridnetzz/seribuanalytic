"""
Ekstrak frame dari video recording untuk dataset (di-upload ke Roboflow).
Ambil 1 frame tiap INTERVAL_SEC detik supaya frame TIDAK kembar (cegah overfitting).
Jalankan:  python extract.py   ->  hasil di folder dataset_raw/
"""
import cv2
import os

VIDEOS = [
    r"C:\Users\OSS_LAPTOP\Videos\1.mp4",
    r"C:\Users\OSS_LAPTOP\Videos\2.mp4",
    r"C:\Users\OSS_LAPTOP\Videos\3.mp4",
]
OUT_DIR      = "dataset_raw"
INTERVAL_SEC = 2          # 1 frame tiap 2 detik. Kecilkan utk lebih banyak gambar.

os.makedirs(OUT_DIR, exist_ok=True)
total = 0
for path in VIDEOS:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        print("GAGAL buka:", path)
        continue
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, int(round(fps * INTERVAL_SEC)))
    name = os.path.splitext(os.path.basename(path))[0]
    i = saved = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            cv2.imwrite(os.path.join(OUT_DIR, f"{name}_{saved:04d}.jpg"), frame)
            saved += 1
        i += 1
    cap.release()
    total += saved
    print(f"{name}.mp4 -> {saved} frame")

print(f"\nSELESAI. Total {total} gambar di folder '{OUT_DIR}'. Upload folder ini ke Roboflow.")
