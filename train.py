"""
Train YOLO lokal dari dataset Roboflow yang sudah didownload -> hasil best.pt.
Jalankan SEKALI:  python train.py
Hasil akhir:      runs/detect/garbage/weights/best.pt
"""
from ultralytics import YOLO

# Base YOLO11 (didukung ultralytics 8.3.28). yolo26n.pt dari Roboflow TIDAK dipakai
# karena arsitekturnya butuh ultralytics >=8.4. yolo11s = akurat utk objek kecil, tetap cepat.
BASE    = "yolo11s.pt"                       # auto-download sekali
# dataset gabungan lama(173)+baru(149), sudah di-split train/valid oleh merge.py
DATA    = r"C:\Users\OSS_LAPTOP\Documents\project\seribuwajah lampung\dataset_merged\data.yaml"


def main():
    model = YOLO(BASE)
    model.train(
        data=DATA,
        epochs=100,
        imgsz=640,
        batch=16,
        device=0,            # GPU RTX 4060
        patience=25,         # stop kalau 25 epoch tak membaik (cegah overfit; dataset cuma 160 gbr)
        project="runs/detect",
        name="garbage_v3",
    )
    print("\nSELESAI. best.pt ada di: runs/detect/garbage_v3/weights/best.pt")


# WAJIB di Windows: lindungi entry-point agar worker multiprocessing tidak rekursif
if __name__ == "__main__":
    main()
