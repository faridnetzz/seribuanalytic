import { Router } from 'express';
import { query } from '../db.js';

const router = Router();

// Ringkasan kota: KPI, kartu modul, volume per jam, kontribusi per modul.
router.get('/', async (_req, res, next) => {
  try {
    const [kpi, modules, hourly, contribution] = await Promise.all([
      buildKpis(),
      buildModuleCards(),
      buildHourlyVolume(),
      buildContribution(),
    ]);
    res.json({ kpi, modules, hourly, contribution });
  } catch (e) {
    next(e);
  }
});

async function buildKpis() {
  const totalToday = await scalar(
    `SELECT count(*) FROM detection_events WHERE ts >= date_trunc('day', now())`
  );
  const totalYday = await scalar(
    `SELECT count(*) FROM detection_events
     WHERE ts >= date_trunc('day', now()) - interval '1 day'
       AND ts <  date_trunc('day', now())`
  );
  const pedestrian = await scalar(
    `SELECT count(DISTINCT COALESCE(global_id, id)) FROM pedestrian_tracks
     WHERE last_seen >= date_trunc('day', now())`
  );
  const parking = await scalar(
    `SELECT count(*) FROM parking_violations WHERE started_at >= date_trunc('day', now())`
  );
  const waste = await scalar(
    `SELECT count(*) FROM waste_piles WHERE first_seen >= date_trunc('day', now())`
  );
  const highAlerts = await scalar(
    `SELECT count(*) FROM alerts WHERE severity='crit' AND acknowledged=false`
  );

  return {
    totalDetections: totalToday,
    totalDetectionsTrendPct: pct(totalToday, totalYday),
    pedestrianTracked: pedestrian,
    parkingViolations: parking,
    wasteDetections: waste,
    highPriorityAlerts: highAlerts,
  };
}

async function buildModuleCards() {
  // Akurasi & nama dari tabel referensi modules
  const meta = await query(`SELECT code, name, accent, accuracy FROM modules`);
  const byCode = Object.fromEntries(meta.rows.map((m) => [m.code, m]));

  const pedTracked = await scalar(
    `SELECT count(*) FROM pedestrian_tracks WHERE last_seen >= date_trunc('day', now())`
  );
  const wastePoints = await scalar(
    `SELECT count(DISTINCT camera_id) FROM waste_piles WHERE first_seen >= date_trunc('day', now())`
  );
  const wasteCritical = await scalar(
    `SELECT count(*) FROM waste_piles
     WHERE first_seen >= date_trunc('day', now()) AND severity IN ('high','critical')`
  );
  const water = await query(
    `SELECT level_m, status FROM water_levels ORDER BY ts DESC LIMIT 1`
  );
  const parkViol = await scalar(
    `SELECT count(*) FROM parking_violations WHERE ts >= date_trunc('day', now())`
  );
  const parkZones = await scalar(`SELECT count(*) FROM parking_zones`);

  return [
    {
      code: 'pedestrian',
      ...byCode.pedestrian,
      stats: [
        [String(pedTracked), 'TERLACAK'],
        [fmtPct(byCode.pedestrian?.accuracy), 'AKURASI'],
      ],
    },
    {
      code: 'waste',
      ...byCode.waste,
      stats: [
        [String(wastePoints), 'TITIK'],
        [String(wasteCritical), 'KRITIS'],
        [fmtPct(byCode.waste?.accuracy), 'AKURASI'],
      ],
    },
    {
      code: 'water',
      ...byCode.water,
      stats: [
        [water.rows[0] ? Number(water.rows[0].level_m).toFixed(2) : '–', 'METER'],
        [(water.rows[0]?.status ?? 'aman').toUpperCase(), 'STATUS'],
        [fmtPct(byCode.water?.accuracy), 'AKURASI'],
      ],
    },
    {
      code: 'parking',
      ...byCode.parking,
      stats: [
        [String(parkViol), 'PELANGGARAN'],
        [String(parkZones), 'ZONA'],
        [fmtPct(byCode.parking?.accuracy), 'AKURASI'],
      ],
    },
  ];
}

// 24 ember per jam untuk hari ini, total seluruh modul.
async function buildHourlyVolume() {
  const { rows } = await query(`
    SELECT EXTRACT(HOUR FROM ts)::int AS h, count(*)::int AS total
    FROM detection_events
    WHERE ts >= date_trunc('day', now())
    GROUP BY 1 ORDER BY 1
  `);
  const series = Array(24).fill(0);
  for (const r of rows) series[r.h] = r.total;
  return { labels: [...Array(24).keys()].map((h) => String(h).padStart(2, '0')), series };
}

async function buildContribution() {
  const { rows } = await query(`SELECT module, total FROM v_module_contribution_today`);
  const total = rows.reduce((s, r) => s + Number(r.total), 0) || 1;
  return rows.map((r) => ({
    module: r.module,
    total: Number(r.total),
    pct: Math.round((Number(r.total) / total) * 100),
  }));
}

// ---- util ----
async function scalar(sql, params) {
  const { rows } = await query(sql, params);
  return Number(Object.values(rows[0])[0]);
}
const pct = (now, prev) =>
  prev > 0 ? Math.round(((now - prev) / prev) * 1000) / 10 : null;
const fmtPct = (v) => (v == null ? '–' : `${Number(v).toFixed(1)}%`);

export default router;
