import { Router } from 'express';
import { query } from '../db.js';
import { config } from '../config.js';

const router = Router();

// Status kebersihan dari jumlah tumpukan AKTIF (terlihat <60s) + ada yg berat.
function cleanliness(active, heavy) {
  if (!active) return 'bersih';
  if (heavy || active >= 3) return 'sangat_kotor';
  return 'kotor';
}

router.get('/summary', async (_req, res, next) => {
  try {
    const FRESH = `status='active' AND last_seen >= now() - interval '60 seconds'`;
    const activePiles = await scalar(`SELECT count(*) FROM waste_piles WHERE ${FRESH}`);
    const notCollected = await scalar(
      `SELECT count(*) FROM waste_piles WHERE ${FRESH} AND duration_seconds >= $1`,
      [config.thresholds.wasteNotCollectedS]
    );
    const todayEpisodes = await scalar(
      `SELECT count(*) FROM waste_piles WHERE first_seen >= date_trunc('day', now())`
    );
    const clearedToday = await scalar(
      `SELECT count(*) FROM waste_piles WHERE status='cleared' AND cleared_at >= date_trunc('day', now())`
    );
    // SLA = rata-rata lama tumpukan ada sampai diangkut (cleared) hari ini.
    const avgResponse = await scalar(
      `SELECT COALESCE(round(avg(duration_seconds)),0) FROM waste_piles
       WHERE status='cleared' AND cleared_at >= date_trunc('day', now())`
    );
    const accuracy = await scalar(`SELECT accuracy FROM modules WHERE code='waste'`);

    // Status kebersihan per kamera sampah.
    const cams = await query(`
      SELECT c.id AS "cameraId", c.name, c.area,
             count(p.id) FILTER (WHERE p.status='active' AND p.last_seen >= now() - interval '60 seconds') AS active,
             bool_or(p.status='active' AND p.last_seen >= now() - interval '60 seconds'
                     AND p.severity IN ('high','critical')) AS heavy
      FROM cameras c
      LEFT JOIN waste_piles p ON p.camera_id = c.id
      WHERE 'waste' = ANY(c.modules)
      GROUP BY c.id, c.name, c.area
      ORDER BY c.id
    `);
    const perCamera = cams.rows.map((r) => ({
      cameraId: r.cameraId, name: r.name, area: r.area,
      active: Number(r.active),
      status: cleanliness(Number(r.active), r.heavy),
    }));

    res.json({
      activePiles, notCollected, todayEpisodes, clearedToday,
      avgResponseSeconds: avgResponse, accuracy, perCamera,
      contacts: { dlhWa: config.contacts.dlhWa, dlhName: config.contacts.dlhName },
    });
  } catch (e) {
    next(e);
  }
});

// Episode tumpukan (1 baris = 1 tumpukan), urut update terbaru.
router.get('/recent', async (req, res, next) => {
  try {
    const limit = Math.min(parseInt(req.query.limit || '40', 10), 100);
    const { rows } = await query(
      `SELECT p.id, p.camera_id AS "cameraId", c.name AS "cameraName", c.area,
              p.pile_uid AS "pileUid", p.severity, p.area_ratio AS "areaRatio",
              p.snapshot_url AS "snapshotId", p.status, p.reported,
              p.duration_seconds AS "durationSeconds",
              p.first_seen AS "firstSeen", p.last_seen AS "lastSeen", p.cleared_at AS "clearedAt"
       FROM waste_piles p JOIN cameras c ON c.id = p.camera_id
       ORDER BY p.last_seen DESC LIMIT $1`,
      [limit]
    );
    res.json(rows);
  } catch (e) {
    next(e);
  }
});

// Heatmap jam rawan: jumlah tumpukan MUNCUL per jam hari ini.
router.get('/heatmap', async (_req, res, next) => {
  try {
    const { rows } = await query(`
      SELECT EXTRACT(HOUR FROM first_seen)::int AS h, count(*)::int AS total
      FROM waste_piles WHERE first_seen >= date_trunc('day', now())
      GROUP BY 1 ORDER BY 1
    `);
    const series = Array(24).fill(0);
    for (const r of rows) series[r.h] = r.total;
    res.json({ labels: [...Array(24).keys()].map((h) => String(h).padStart(2, '0')), series });
  } catch (e) {
    next(e);
  }
});

// Ranking lokasi terkotor hari ini: jumlah tumpukan + total persistensi (menit).
router.get('/ranking', async (_req, res, next) => {
  try {
    const { rows } = await query(`
      SELECT p.camera_id AS "cameraId", c.name AS "cameraName",
             count(*)::int AS piles,
             round(sum(p.duration_seconds)/60.0)::int AS "persistMinutes"
      FROM waste_piles p JOIN cameras c ON c.id = p.camera_id
      WHERE p.first_seen >= date_trunc('day', now())
      GROUP BY 1,2 ORDER BY "persistMinutes" DESC, piles DESC LIMIT 10
    `);
    res.json(rows);
  } catch (e) {
    next(e);
  }
});

router.post('/pile/report', async (req, res, next) => {
  try {
    const { pileUid } = req.body || {};
    if (!pileUid) return res.status(400).json({ ok: false, error: 'pileUid wajib' });
    await query(`UPDATE waste_piles SET reported=true WHERE pile_uid=$1`, [pileUid]);
    res.json({ ok: true });
  } catch (e) { next(e); }
});

router.post('/pile/delete', async (req, res, next) => {
  try {
    const { pileUid } = req.body || {};
    if (!pileUid) return res.status(400).json({ ok: false, error: 'pileUid wajib' });
    const { rowCount } = await query(`DELETE FROM waste_piles WHERE pile_uid=$1`, [pileUid]);
    res.json({ ok: true, deleted: rowCount });
  } catch (e) { next(e); }
});

router.post('/piles/clear', async (_req, res, next) => {
  try {
    const { rowCount } = await query(`DELETE FROM waste_piles`);
    res.json({ ok: true, deleted: rowCount });
  } catch (e) { next(e); }
});

async function scalar(sql, params) {
  const { rows } = await query(sql, params);
  return Number(Object.values(rows[0])[0]);
}

export default router;
