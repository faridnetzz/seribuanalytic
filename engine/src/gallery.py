"""Galeri enrollment wajah untuk Face Recognition + Re-ID.

Struktur folder:  ENROLL_DIR/<Nama Orang>/*.jpg   (beberapa foto per orang: depan/samping)
Embedding tiap orang = rata-rata embedding semua fotonya (lebih robust).
Pencocokan: cosine similarity (embedding sudah ternormalisasi) vs threshold.

Identitas yang sama dikenali di kamera mana pun -> ini sekaligus Re-ID berbasis wajah.
"""
import glob
import logging
import os

import cv2
import numpy as np

from . import config

log = logging.getLogger("engine.gallery")


class Gallery:
    def __init__(self, face_engine):
        self.fr = face_engine
        self.names = []        # list[str] nama identitas
        self.embs = None       # np.ndarray (N, 512) ternormalisasi

    def build(self):
        names, embs = [], []
        if not os.path.isdir(config.ENROLL_DIR):
            log.warning("Folder enrollment tak ada: %s (FR jalan tanpa identitas)", config.ENROLL_DIR)
            self.names, self.embs = [], None
            return
        for person in sorted(os.listdir(config.ENROLL_DIR)):
            pdir = os.path.join(config.ENROLL_DIR, person)
            if not os.path.isdir(pdir):
                continue
            vecs = []
            for img_path in sorted(glob.glob(os.path.join(pdir, "*.jpg"))
                                   + glob.glob(os.path.join(pdir, "*.png"))):
                img = cv2.imread(img_path)
                if img is None:
                    continue
                faces = self.fr.analyze(img)
                if not faces:
                    continue
                # ambil wajah terbesar (subjek utama foto enrollment)
                faces.sort(key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]),
                           reverse=True)
                vecs.append(faces[0]["embedding"])
            if vecs:
                mean = np.mean(vecs, axis=0)
                mean = mean / (np.linalg.norm(mean) + 1e-9)
                names.append(person)
                embs.append(mean.astype(np.float32))
                log.info("Enroll '%s': %d foto", person, len(vecs))
        self.names = names
        self.embs = np.vstack(embs) if embs else None
        log.info("Galeri siap: %d identitas", len(names))

    def match(self, embedding):
        """-> (nama, skor) bila >= threshold, selain itu (None, skor_terbaik)."""
        if self.embs is None:
            return None, 0.0
        sims = self.embs @ embedding           # cosine (keduanya ternormalisasi)
        i = int(np.argmax(sims))
        score = float(sims[i])
        if score >= config.FACE_MATCH_THRESHOLD:
            return self.names[i], score
        return None, score
