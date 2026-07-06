// Klien REST tipis. VITE_API_BASE kosong saat dev (pakai proxy Vite).
const BASE = import.meta.env.VITE_API_BASE || '';

async function get(path) {
  const res = await fetch(`${BASE}/api${path}`);
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
  return res.json();
}

async function post(path, body) {
  const res = await fetch(`${BASE}/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) throw new Error(`POST ${path} -> ${res.status}`);
  return res.json();
}

export const api = {
  health: () => get('/health'),
  cameras: () => get('/cameras'),
  overview: () => get('/overview'),
  alerts: (limit = 20) => get(`/alerts?limit=${limit}`),
  ackAlert: (id) => post(`/alerts/${id}/ack`),
  pedestrian: () => get('/pedestrian/summary'),
  pedestrianTracks: (limit = 50) => get(`/pedestrian/tracks?limit=${limit}`),
  deletePedestrianTrack: (cameraId, trackId) => post('/pedestrian/track/delete', { cameraId, trackId }),
  waste: () => get('/waste/summary'),
  wasteRecent: (limit = 40) => get(`/waste/recent?limit=${limit}`),
  wasteHeatmap: () => get('/waste/heatmap'),
  wasteRanking: () => get('/waste/ranking'),
  wasteReportPile: (pileUid) => post('/waste/pile/report', { pileUid }),
  wasteDeletePile: (pileUid) => post('/waste/pile/delete', { pileUid }),
  wasteClearPiles: () => post('/waste/piles/clear'),
  water: () => get('/water/summary'),
  waterSeries: (camera, hours = 24) => get(`/water/series?camera=${camera}&hours=${hours}`),
  parking: () => get('/parking/summary'),
  parkingViolations: (limit = 30) => get(`/parking/violations?limit=${limit}`),
  parkingSpeaker: (cameraId, message) => post('/parking/speaker', { cameraId, message }),
  parkingDeleteViolation: (violationId) => post('/parking/violation/delete', { violationId }),
  parkingClearViolations: () => post('/parking/violations/clear'),
};
