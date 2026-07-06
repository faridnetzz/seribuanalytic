# Enrollment Wajah (Face Recognition)

Daftarkan orang yang ingin dikenali sistem. Struktur:

```
engine/enrollment/
├── Budi Santoso/
│   ├── depan.jpg
│   ├── samping_kiri.jpg
│   └── samping_kanan.jpg
├── Siti Aminah/
│   ├── 1.jpg
│   └── 2.jpg
```

Aturan:
- **1 folder = 1 orang.** Nama folder = nama yang muncul di dashboard.
- Taruh **2–5 foto** per orang (depan + sedikit menyamping → lebih akurat).
- Wajah jelas, tidak terlalu kecil/blur. Format `.jpg` / `.png`.
- Embedding tiap orang = rata-rata semua fotonya (dihitung saat engine start).

Setelah menaruh/mengubah foto, restart engine:
`docker compose --profile gpu up -d engine`

Identitas yang sama otomatis dikenali di kamera mana pun (Re-ID berbasis wajah).
