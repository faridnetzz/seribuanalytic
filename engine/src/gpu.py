"""Lock global akses GPU.

Beberapa pipeline (5 kamera YOLO + FR insightface) jalan di thread berbeda pada
GPU yang sama. Inference CUDA konkuren memicu:
  'CUDA error: operation not permitted when stream is capturing'
Lock ini menyerialkan SEMUA inference GPU (YOLO + FR) — decode/IO tetap paralel,
hanya bagian GPU yang gantian. Cegah crash + tetap cukup cepat.
"""
import threading

lock = threading.Lock()
