-- =====================================================================
-- SIGAP — Data awal (referensi modul, kamera, zona parkir)
-- Angka deteksi nyata diisi runtime oleh simulator / DeepStream.
-- =====================================================================

-- --- Modul analitik ---
INSERT INTO modules (code, name, description, accent, model_name, accuracy) VALUES
  ('pedestrian', 'Pedestrian Tracking', 'Deteksi, hitung & jejak pergerakan orang lintas kamera', '#37e0c8', 'YOLO + InsightFace ReID', 96.20),
  ('waste',      'Deteksi Sampah',                  'Titik tumpukan sampah liar',       '#f2b733', 'YOLOv8-seg-waste',        89.50),
  ('water',      'Debit Air Sungai',                'Estimasi ketinggian & status banjir','#3aa0ff','VirtualStaffGauge-UNet',  94.10),
  ('parking',    'Deteksi Parkir Liar',             'Kendaraan di zona terlarang',      '#ff5e7a', 'YOLOv8-vehicle + DCF',    92.80);

-- --- Kamera CCTV (8 titik, koordinat sekitar Bandar Lampung) ---
INSERT INTO cameras (id, name, area, lat, lng, rtsp_url, modules, status) VALUES
  ('CAM-01', 'Pasar Tengah',         'Tanjung Karang Pusat', -5.4297, 105.2610, 'rtsp://edge/cam01', '{parking,pedestrian}',        'online'),
  ('CAM-02', 'Gang Pasar Bawah',     'Teluk Betung Selatan', -5.4485, 105.2640, 'rtsp://edge/cam02', '{waste,pedestrian}',          'online'),
  ('CAM-03', 'Pasar Gintung',        'Tanjung Karang Pusat', -5.40817, 105.25570, 'rtsp://edge/cam03', '{waste}',                    'online'),
  ('CAM-04', 'Jl. Selat Sunda',      'Kedaton',              -5.3920, 105.2670, 'rtsp://edge/cam04', '{parking}',                   'online'),
  ('CAM-05', 'Jembatan Milenial 1',  'Enggal',               -5.42938, 105.26211, 'rtsp://edge/cam05', '{pedestrian}',               'online'),
  ('CAM-06', 'Jembatan Milenial 3',  'Enggal',               -5.42950, 105.26150, 'rtsp://edge/cam06', '{pedestrian}',               'online'),
  ('CAM-07', 'Kelurahan Gulak Galik','Teluk Betung Utara',   -5.43590, 105.25867, 'rtsp://edge/cam07', '{pedestrian}',               'online'),
  ('CAM-08', 'Kantor Kelurahan',     'Rajabasa',             -5.3700, 105.2410, 'rtsp://edge/cam08', '{pedestrian,waste}',          'online');

-- --- Zona parkir terlarang ---
INSERT INTO parking_zones (camera_id, name, polygon, dwell_limit_s) VALUES
  ('CAM-01', 'Dilarang Parkir — Badan Jalan', '[[0.10,0.55],[0.85,0.55],[0.85,0.95],[0.10,0.95]]', 20),
  ('CAM-04', 'Marka Kuning',                   '[[0.05,0.60],[0.60,0.60],[0.60,0.92],[0.05,0.92]]', 20);

-- --- Baseline ketinggian air (agar tren punya titik awal) ---
INSERT INTO water_levels (camera_id, level_m, status, trend_cm_30min, confidence, ts) VALUES
  ('CAM-03', 0.84, 'aman',    1.2,  0.941, now() - interval '30 min'),
  ('CAM-06', 1.35, 'waspada', 6.5,  0.918, now() - interval '30 min');
