"""Test terisolasi logika PARKIR LIAR — TANPA YOLO/CCTV/docker.

Jalankan:  python engine/tests/test_park_logic.py
Skenario sintetis (deteksi kendaraan buatan) mengecek perilaku yang BENAR:
- kendaraan diam di zona > ambang  -> 1 pelanggaran
- kendaraan lewat / nunggu lampu   -> 0 pelanggaran (INI yg bocor di persimpangan)
- kedipan deteksi / ganti track-id -> tetap 1 sesi (tak terpecah)

Fokus: sebuah SESI = SATU kendaraan fisik yg benar-benar diam; timer TIDAK boleh
diwariskan antar-kendaraan berbeda yg kebetulan berhenti di titik sama.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from park_logic import ParkingTracker, ParkingParams   # noqa: E402

FPS = 5
DT = 1.0 / FPS
DWELL = 20.0
ROI = [(200, 200), (800, 200), (800, 800), (200, 800)]   # kotak zona (piksel)


def box(cx, cy, s=100):
    return (cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2)


def run(dets_fn, duration, tail_s=45, params=None):
    """Simulasikan frame @FPS selama `duration` detik, lalu `tail_s` detik tanpa
    deteksi (agar sesi difinalisasi). Return (jml_start, list_clear)."""
    tr = ParkingTracker(params or ParkingParams())
    starts, clears = [], []
    n = int((duration + tail_s) * FPS)
    for i in range(n):
        t = i * DT
        dets = dets_fn(t) if t < duration else []
        _, events = tr.update(t, dets, ROI, DWELL)
        for e in events:
            (starts if e["kind"] == "start" else clears).append(e)
    return len(starts), clears


# ---------- skenario ----------
def s_parked(t):
    return [(1, *box(450, 450), "car")]                       # diam di zona


def s_moving(t):
    x = 250 + (750 - 250) * (t / 30.0)                        # menyeberang zona 30s
    return [(1, *box(x, 450), "car")]


def s_short_wait(t):
    return [(1, *box(450, 450), "car")] if t < 15 else []     # diam 15s (< ambang)


def s_junction(t):
    # 8 kendaraan BERBEDA, tiap satu diam ~10s di titik sama lalu pergi, jeda 3s.
    k = int(t // 13)
    if t - k * 13 < 10:
        return [(k + 1, *box(450, 450), "car")]               # track-id beda tiap kendaraan
    return []


def s_blink(t):
    if 30 <= t < 33:                                          # deteksi hilang 3s (kedip)
        return []
    return [(1, *box(450, 450), "car")]


def s_idswitch(t):
    tid = 1 if t < 30 else 2                                  # track-id ganti (mobil sama, diam)
    return [(tid, *box(450, 450), "car")]


def s_two_parked(t):
    return [(1, *box(350, 350), "car"), (2, *box(650, 650), "truck")]


def s_outside(t):
    return [(1, *box(60, 60), "car")]                         # diam TAPI di luar zona


CASES = [
    ("parkir beneran (diam 60s)",        s_parked,     60, 1),
    ("kendaraan lewat (menyeberang)",    s_moving,     30, 0),
    ("nunggu sebentar (15s < ambang)",   s_short_wait, 20, 0),
    ("PERSIMPANGAN (8 kendaraan lewat)", s_junction,  104, 0),
    ("kedip deteksi 3s (mobil sama)",    s_blink,      60, 1),
    ("ganti track-id (mobil parkir)",    s_idswitch,   60, 1),
    ("dua mobil parkir beda titik",      s_two_parked, 60, 2),
    ("diam tapi di luar zona",           s_outside,    60, 0),
]


def main():
    fails = 0
    print(f"{'SKENARIO':38} {'harap':>6} {'dapat':>6}  hasil")
    print("-" * 62)
    for name, fn, dur, expect in CASES:
        got, clears = run(fn, dur)
        ok = got == expect
        fails += 0 if ok else 1
        print(f"{name:38} {expect:>6} {got:>6}  {'[ OK ]' if ok else '[FAIL]'}")
    print("-" * 62)
    if fails:
        print(f"{fails} skenario GAGAL -- logika parkir belum benar.")
        sys.exit(1)
    print("SEMUA skenario LULUS")


if __name__ == "__main__":
    main()
