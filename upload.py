"""
Upload semua gambar dataset_upload/ ke Roboflow lewat API (bypass batas 10 gambar UI).
Isi API_KEY dulu (ambil di Roboflow: Settings -> API Keys, atau dari snippet download kemarin).
Jalankan:  python upload.py
"""
import os
from roboflow import Roboflow

API_KEY   = "iemkKJ4H3wtgHcxXZCvJ"
WORKSPACE = "farid-ns68i"        # sesuaikan kalau beda (lihat snippet download Roboflow)
PROJECT   = "deteksi-sampah-bulk"  # project Traditional (Rapid tdk dukung API upload)
FOLDER    = "dataset_upload"
SPLIT     = "train"              # nanti bisa di-rebalance saat Generate version

rf = Roboflow(api_key=API_KEY)
project = rf.workspace(WORKSPACE).project(PROJECT)

files = [f for f in sorted(os.listdir(FOLDER)) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
print(f"akan upload {len(files)} gambar ke {WORKSPACE}/{PROJECT} ...")

ok = fail = 0
for i, f in enumerate(files, 1):
    path = os.path.join(FOLDER, f)
    try:
        project.upload(image_path=path, batch_name="recording-06-09", split=SPLIT)
        ok += 1
    except Exception as e:
        fail += 1
        print(f"  GAGAL {f}: {str(e)[:80]}")
    if i % 10 == 0:
        print(f"  {i}/{len(files)} (berhasil={ok}, gagal={fail})")

print(f"\nSELESAI. Berhasil: {ok}, gagal: {fail}. Cek di Roboflow -> Annotate.")
