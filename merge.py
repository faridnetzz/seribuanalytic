"""
Gabung dataset LAMA (160+8+5) + BARU (150) -> dataset_merged/ dengan split train/valid 85/15.
Semua class 'garbage' (index 0) di kedua dataset, jadi merge langsung tanpa remap.
Jalankan:  python merge.py
"""
import os, glob, shutil, random

random.seed(42)
OUT = "dataset_merged"
VAL_RATIO = 0.15

# sumber: (folder_images, prefix biar nama file tak bentrok)
OLD = r"C:\Users\OSS_LAPTOP\Downloads\Compressed\Find garbage.v3-continuous-improvement-2026-05-29.yolo26"
SOURCES = [
    (os.path.join(OLD, "train", "images"), "old_tr"),
    (os.path.join(OLD, "valid", "images"), "old_va"),
    (os.path.join(OLD, "test",  "images"), "old_te"),
    ("dataset_v2/train/images",            "new"),
]

# kumpulkan pasangan (image, label)
pairs = []
for img_dir, prefix in SOURCES:
    lbl_dir = img_dir.replace("images", "labels")
    for img in glob.glob(os.path.join(img_dir, "*.jpg")) + glob.glob(os.path.join(img_dir, "*.png")):
        stem = os.path.splitext(os.path.basename(img))[0]
        lbl = os.path.join(lbl_dir, stem + ".txt")
        pairs.append((img, lbl if os.path.exists(lbl) else None, f"{prefix}_{stem}"))

random.shuffle(pairs)
n_val = int(len(pairs) * VAL_RATIO)
splits = {"valid": pairs[:n_val], "train": pairs[n_val:]}

# reset folder output
if os.path.exists(OUT):
    shutil.rmtree(OUT)
for split, items in splits.items():
    os.makedirs(os.path.join(OUT, split, "images"), exist_ok=True)
    os.makedirs(os.path.join(OUT, split, "labels"), exist_ok=True)
    for img, lbl, name in items:
        ext = os.path.splitext(img)[1]
        shutil.copy(img, os.path.join(OUT, split, "images", name + ext))
        # label kosong (negative sample) -> buat file txt kosong
        dst_lbl = os.path.join(OUT, split, "labels", name + ".txt")
        if lbl:
            shutil.copy(lbl, dst_lbl)
        else:
            open(dst_lbl, "w").close()

# data.yaml dengan path absolut
root = os.path.abspath(OUT).replace("\\", "/")
with open(os.path.join(OUT, "data.yaml"), "w") as f:
    f.write(f"train: {root}/train/images\n")
    f.write(f"val: {root}/valid/images\n")
    f.write("nc: 1\n")
    f.write("names: ['garbage']\n")

print(f"train: {len(splits['train'])} | valid: {len(splits['valid'])} | total: {len(pairs)}")
print("data.yaml:", os.path.join(OUT, "data.yaml"))
