"""Sinkronisasi bounding box ke frame yang DITAMPILKAN (anti "box lepas") + interpolasi.

Masalah: video ditampilkan dari buffer playout (delay demi kemulusan), tapi hasil
inferensi adalah utk frame TERBARU (real-time) -> box mendahului frame -> lepas dari
objek (parah utk objek bergerak). fps inferensi rendah -> box patah-patah.

Solusi: tiap hasil inferensi disimpan dgn `seq` frame asalnya. Saat menampilkan frame
ber-`seq` D, ambil box dari DUA hasil inferensi yang mengapit D lalu INTERPOLASI posisi
(per track id) -> box menempel persis di frame yang tampil & bergerak mulus.
"""
import threading
from collections import deque


class BoxHistory:
    """Riwayat hasil inferensi ber-seq utk satu kamera. Thread-safe.

    boxes = dict {id -> (x1, y1, x2, y2, *extra)} di mana `extra` (warna/label/conf)
    diambil apa adanya dari hasil terbaru saat interpolasi.
    """

    def __init__(self, maxlen=16):
        self._hist = deque(maxlen=maxlen)     # (seq, boxes_dict) urut naik
        self._lock = threading.Lock()

    def put(self, seq, boxes):
        with self._lock:
            self._hist.append((int(seq), boxes))

    def at(self, dseq, interpolate=True):
        """Box utk frame seq=dseq. Per track id:
        - dseq di antara 2 hasil inferensi -> INTERPOLASI (box menempel di frame delay).
        - dseq melewati hasil terbaru (display ~live) -> EKSTRAPOLASI maju (bounded)
          pakai 2 hasil terakhir -> box MENGEJAR kendaraan bergerak (anti-telat).
        Kembalikan list tuple (x1,y1,x2,y2,*extra)."""
        with self._lock:
            hist = list(self._hist)
        if not hist:
            return []
        if not interpolate:                     # objek statis -> nearest <= dseq (atau terlama)
            a = None
            for s, bx in hist:
                if s <= dseq:
                    a = bx
            return list((a if a is not None else hist[0][1]).values())

        # cari indeks A = terbaru seq<=dseq, B = terlama seq>=dseq
        ai = bi = None
        for i, (s, _bx) in enumerate(hist):
            if s <= dseq:
                ai = i
            if s >= dseq and bi is None:
                bi = i
        if ai is None:                          # display sebelum semua hasil -> hasil terlama
            return list(hist[bi][1].values()) if bi is not None else []

        sa, abx = hist[ai]
        if bi is not None and hist[bi][0] != sa:   # --- INTERPOLASI (mengapit) ---
            sb, bbx = hist[bi]
            t = (dseq - sa) / float(sb - sa)
            t = 0.0 if t < 0 else 1.0 if t > 1 else t
            return _blend(abx, bbx, t)

        # --- EKSTRAPOLASI maju: dseq >= hasil terbaru (display dekat live) ---
        if ai >= 1:
            sp, pbx = hist[ai - 1]              # hasil sebelum A
            if sa != sp:
                # t>1 = maju melebihi A; batasi 1.25 (prediksi maju ~0.25 interval saja)
                # -> kurangi telat tanpa overshoot box ke ruang kosong (hantu).
                t = (dseq - sp) / float(sa - sp)
                t = 1.0 if t < 1 else 1.25 if t > 1.25 else t
                return _blend(pbx, abx, t)
        return list(abx.values())


def _blend(abx, bbx, t):
    """Campur posisi box A->B pada faktor t (boleh >1 utk ekstrapolasi). extra dari B."""
    out = []
    seen = set()
    for tid, av in abx.items():
        bv = bbx.get(tid)
        seen.add(tid)
        if bv is not None:
            out.append((
                int(av[0] + (bv[0] - av[0]) * t),
                int(av[1] + (bv[1] - av[1]) * t),
                int(av[2] + (bv[2] - av[2]) * t),
                int(av[3] + (bv[3] - av[3]) * t),
                *bv[4:],
            ))
        else:
            out.append(av)
    for tid, bv in bbx.items():
        if tid not in seen:
            out.append(bv)
    return out
