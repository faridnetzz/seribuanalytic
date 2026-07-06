<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { api } from '../api/client.js';
import KpiCard from '../components/KpiCard.vue';

const sum = ref(null);
const loading = ref(true);

// Video live 2 kamera pedestrian (server MJPEG engine, port 8090 di host).
const streamBase = import.meta.env.VITE_STREAM_BASE || 'http://localhost:8090';
const cams = [
  { id: 'CAM-05', name: 'Jembatan Milenial 1' },
  { id: 'CAM-06', name: 'Jembatan Milenial 3' },
  { id: 'CAM-07', name: 'Kelurahan Gulak Galik' },
];

// --- Galeri Snapshot (auto-capture semua orang; klik foto -> enroll) ---
const snaps = ref([]);
const snapFilter = ref('');                 // '' | 'unknown' | 'known'
const snapImg = (s) => `${streamBase}/snap-img/${s.id}`;
const snapTime = (ts) => new Date(ts).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
async function loadSnaps() {
  try {
    const q = `?limit=80${snapFilter.value ? '&identity=' + snapFilter.value : ''}`;
    snaps.value = (await (await fetch(`${streamBase}/snapshots${q}`)).json()).items || [];
  } catch {}
}
function setSnapFilter(v) { snapFilter.value = v; loadSnaps(); }

// Geo kamera (lat/lng dari DB) untuk PETA JEJAK lintas-kamera.
const camGeo = ref({});
async function loadCamGeo() {
  try {
    const rows = await api.cameras();
    const m = {};
    for (const c of rows || []) {
      const lat = Number(c.lat), lng = Number(c.lng);
      m[c.id] = { name: c.name, area: c.area,
                  lat: Number.isFinite(lat) ? lat : null,
                  lng: Number.isFinite(lng) ? lng : null };
    }
    camGeo.value = m;
  } catch {}
}
const camName = (id) => camGeo.value[id]?.name || (cams.find((c) => c.id === id) || {}).name || id;
const snapDetail = (s, kind) => `${streamBase}/snap-img/${s.id}?kind=${kind}`;

// --- modal detail snapshot ---
const selected = ref(null);
const snapTab = ref('scene');
const enrollMode = ref(false);
const enrollNameInput = ref('');
const traj = ref([]);                          // jejak lintas-kamera identitas terpilih
async function loadTraj(gid) {
  traj.value = [];
  if (!gid) return;
  try { traj.value = (await (await fetch(`${streamBase}/trajectory?gid=${gid}`)).json()).sightings || []; }
  catch {}
}
// --- PETA JEJAK (Leaflet): plot kemunculan lintas-kamera di peta + rute ---
const mapEl = ref(null);
let lmap = null, mapLayer = null;

// titik jejak terurut waktu, hanya yang kameranya punya koordinat
function buildTrajPoints() {
  const list = [...traj.value].sort((a, b) => new Date(a.ts) - new Date(b.ts));
  const pts = [];
  for (const s of list) {
    const g = camGeo.value[s.cam];
    if (g && g.lat != null && g.lng != null)
      pts.push({ lat: g.lat, lng: g.lng, cam: s.cam, name: g.name, ts: s.ts });
  }
  return pts;
}
const hasGeoTraj = computed(() => buildTrajPoints().length > 0);

function destroyMap() {
  if (lmap) { try { lmap.remove(); } catch {} lmap = null; mapLayer = null; }
}

async function renderMap() {
  await nextTick();
  if (!mapEl.value) return;
  destroyMap();
  const pts = buildTrajPoints();
  if (!pts.length) return;                       // template tampilkan pesan kosong
  lmap = L.map(mapEl.value, { zoomControl: true, attributionControl: false })
          .setView([pts[0].lat, pts[0].lng], 15);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(lmap);
  mapLayer = L.layerGroup().addTo(lmap);

  const latlngs = pts.map((p) => [p.lat, p.lng]);
  if (latlngs.length >= 2)                        // rute lintas-kamera (urut waktu)
    L.polyline(latlngs, { color: '#155dfc', weight: 3, opacity: .85, dashArray: '6 7' }).addTo(mapLayer);

  // marker per kamera (digabung), ukuran ~ jumlah kemunculan
  const visits = new Map();
  for (const p of pts) {
    const v = visits.get(p.cam) || { cam: p.cam, name: p.name, lat: p.lat, lng: p.lng, count: 0, first: p.ts, last: p.ts };
    v.count++; v.last = p.ts; visits.set(p.cam, v);
  }
  for (const v of visits.values()) {
    const r = Math.max(7, Math.min(16, 6 + Math.log2(Math.max(2, v.count)) * 2.5));
    L.circleMarker([v.lat, v.lng], { radius: r, color: '#155dfc', fillColor: '#155dfc', fillOpacity: .6, weight: 2 })
      .addTo(mapLayer)
      .bindPopup(`<b>${v.name || v.cam}</b><br>${v.cam}<br>Kemunculan: <b>${v.count}</b>`
        + `<br>Pertama: ${snapTime(v.first)}<br>Terakhir: ${snapTime(v.last)}`);
  }
  // penanda arah: titik awal (hijau) & terakhir (merah)
  const first = pts[0], last = pts[pts.length - 1];
  L.circleMarker([first.lat, first.lng], { radius: 6, color: '#fff', weight: 2, fillColor: '#00a544', fillOpacity: 1 })
    .addTo(mapLayer).bindTooltip('Mulai', { direction: 'top' });
  if (last !== first)
    L.circleMarker([last.lat, last.lng], { radius: 6, color: '#fff', weight: 2, fillColor: '#e40014', fillOpacity: 1 })
      .addTo(mapLayer).bindTooltip('Terakhir', { direction: 'top' });

  lmap.fitBounds(L.latLngBounds(latlngs), { padding: [40, 40], maxZoom: 16 });
  setTimeout(() => lmap && lmap.invalidateSize(), 60);   // perbaiki dimensi setelah panel tampil
}

function selectTab(t) {
  if (snapTab.value === 'map' && t !== 'map') destroyMap();
  snapTab.value = t;
  if (t === 'map') renderMap();
}
// jejak/koordinat datang asinkron — render ulang bila sedang di tab peta
watch([traj, camGeo], () => { if (snapTab.value === 'map') renderMap(); });

function openSnap(s) {
  selected.value = s;
  snapTab.value = s.hasScene ? 'pano' : 'scene';   // panorama jadi tampilan utama bila ada
  enrollMode.value = false;
  enrollNameInput.value = s.name || '';
  loadTraj(s.gid);
}
function closeSnap() { destroyMap(); selected.value = null; }
async function doEnroll() {
  const name = enrollNameInput.value.trim();
  if (!name) return;
  try {
    const r = await (await fetch(`${streamBase}/enroll-from-snapshot`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: selected.value.id, name }),
    })).json();
    if (r.ok) { closeSnap(); loadSnaps(); } else alert(r.error || 'Gagal enroll');
  } catch { alert('Tidak bisa hubungi engine'); }
}
async function deleteSnap() {
  if (!confirm('Hapus foto ini dari galeri? Data track-nya juga dihapus dari statistik.')) return;
  const s = selected.value;
  try {
    const r = await (await fetch(`${streamBase}/snapshot-delete`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: s.id }),
    })).json();
    if (r.ok) {
      // hapus juga baris track di DB -> hilang dari Distribusi Atribut & hitungan
      if (s.cam && s.trackId != null) {
        try { await api.deletePedestrianTrack(s.cam, s.trackId); } catch {}
      }
      closeSnap();
      loadSnaps();
      load();                          // refresh KPI + distribusi atribut
    }
  } catch { alert('Tidak bisa hubungi engine'); }
}
let snapTimer = null;
onMounted(() => { loadSnaps(); loadCamGeo(); snapTimer = setInterval(loadSnaps, 8000); });
onUnmounted(() => { if (snapTimer) clearInterval(snapTimer); destroyMap(); });   // cegah interval numpuk + bersihkan map

async function load() {
  try {
    sum.value = await api.pedestrian();
  } finally {
    loading.value = false;
  }
}
onMounted(load);
</script>

<template>
  <section class="view">
    <div class="page-head">
      <div>
        <h2>Pedestrian Attribute + Tracking
          <span class="chip" style="background: rgba(21,93,252,.15); color: var(--ped)">PAR + ReID</span>
        </h2>
        <p>Deteksi & pelacakan orang lintas-kamera + pengenalan wajah (enroll identitas). Klik foto di galeri untuk daftarkan nama.</p>
      </div>
    </div>

    <p v-if="loading" class="muted">Memuat…</p>
    <template v-else-if="sum">
      <div class="kpi-grid">
        <KpiCard accent="var(--ped)" label="Objek Terlacak Aktif" :value="sum.activeTracked" foot="30 detik terakhir" />
        <KpiCard accent="var(--ped)" label="Unique ID Hari Ini" :value="sum.uniqueToday.toLocaleString('id-ID')" foot="lintas kamera" />
        <KpiCard accent="var(--ped)" label="Akurasi PAR" :value="sum.parAccuracy ? sum.parAccuracy + '%' : '–'" foot="model atribut" />
        <KpiCard accent="var(--ped)" label="Match Rate ReID" :value="sum.reidMatchRate + '%'" foot="rerata skor" />
      </div>

      <div class="card">
        <h3><span class="acc-dot" style="background: var(--ped)"></span>Pantauan Langsung
          <span class="chip" style="background: rgba(242,80,80,.15); color: var(--crit)">● LIVE</span>
        </h3>
        <div class="card-sub">Video kamera realtime: deteksi orang + tracking + pengenalan wajah</div>
        <div class="cam-grid">
          <figure class="cam" v-for="c in cams" :key="c.id">
            <img :src="streamBase + '/stream/' + c.id" :alt="c.id"
                 @error="(e) => e.target.classList.add('off')" />
            <figcaption>{{ c.id }} · <span class="dim">{{ c.name }}</span></figcaption>
          </figure>
        </div>
      </div>

      <div class="card">
        <h3><span class="acc-dot" style="background: var(--ped)"></span>Galeri Snapshot
          <span class="chip" style="background: rgba(21,93,252,.15); color: var(--ped)">{{ snaps.length }}</span>
        </h3>
        <div class="card-sub">Semua orang yang terdeteksi tertangkap otomatis + metadata wajah. <b>Klik foto</b> untuk enroll (beri nama) → langsung dikenali di seluruh kamera.</div>
        <div class="snap-filter">
          <button :class="{ on: snapFilter === '' }" @click="setSnapFilter('')">Semua</button>
          <button :class="{ on: snapFilter === 'unknown' }" @click="setSnapFilter('unknown')">Belum dikenal</button>
          <button :class="{ on: snapFilter === 'known' }" @click="setSnapFilter('known')">Dikenali</button>
        </div>
        <div class="snap-grid">
          <figure class="snap" v-for="s in snaps" :key="s.id" @click="openSnap(s)" title="Klik untuk detail">
            <img :src="snapImg(s)" loading="lazy" />
            <figcaption>
              <div class="snap-name" :class="{ known: s.name }">{{ s.name || 'Unknown' }}</div>
              <div class="snap-meta">{{ s.cam }} · {{ snapTime(s.ts) }}</div>
              <div class="snap-attr" v-if="s.gender">{{ s.gender === 'L' ? 'Pria' : 'Wanita' }}</div>
            </figcaption>
          </figure>
          <p v-if="!snaps.length" class="muted">Belum ada snapshot — tunggu ada orang lewat di kamera.</p>
        </div>
      </div>

    </template>

    <!-- Modal detail snapshot -->
    <div v-if="selected" class="modal-overlay" @click.self="closeSnap">
      <div class="modal">
        <div class="modal-head">
          <h3>Detail Snapshot</h3>
          <button class="modal-x" @click="closeSnap">✕</button>
        </div>
        <div class="modal-body">
          <aside class="modal-side">
            <img class="modal-thumb" :src="snapDetail(selected, 'body')" />
            <div class="kv"><span>Waktu</span><b>{{ new Date(selected.ts).toLocaleString('id-ID') }}</b></div>
            <div class="kv"><span>Kamera</span><b>{{ selected.cam }} · {{ camName(selected.cam) }}</b></div>
            <div class="kv"><span>Identitas</span><b :class="{ known: selected.name }">{{ selected.name || 'Unknown' }}</b></div>
            <div class="kv" v-if="selected.hasFace && selected.score"><span>Skor cocok</span><b>{{ (selected.score * 100).toFixed(0) }}%</b></div>
            <div class="char" v-if="selected.gender">
              <div class="char-label">Karakteristik</div>
              <span class="char-chip">{{ selected.gender === 'L' ? 'Pria' : 'Wanita' }}</span>
            </div>
            <div class="traj">
              <div class="char-label">Jejak Lintas-Kamera</div>
              <div v-if="traj.length" class="traj-list">
                <div class="traj-row" v-for="(g, i) in traj" :key="i">
                  <span class="traj-dot"></span>
                  <span class="traj-cam">{{ camName(g.cam) }} <span class="dim">· {{ g.cam }}</span></span>
                  <span class="traj-time mono">{{ snapTime(g.ts) }}</span>
                </div>
              </div>
              <p v-else class="muted">Belum terlihat di kamera lain.</p>
            </div>
          </aside>
          <main class="modal-main">
            <div class="modal-tabs">
              <button v-if="selected.hasScene" :class="{ on: snapTab === 'pano' }" @click="selectTab('pano')">🖼 Foto Panorama</button>
              <button :class="{ on: snapTab === 'scene' }" @click="selectTab('scene')">Foto Tubuh</button>
              <button :class="{ on: snapTab === 'live' }" @click="selectTab('live')">Live Kamera</button>
              <button :class="{ on: snapTab === 'map' }" @click="selectTab('map')">🗺 Peta Jejak</button>
            </div>
            <div class="modal-img">
              <img v-show="snapTab === 'pano' && selected.hasScene" :src="snapDetail(selected, 'scene')" />
              <img v-show="snapTab === 'scene'" :src="snapDetail(selected, 'body')" />
              <img v-show="snapTab === 'live'" :src="streamBase + '/stream/' + selected.cam" />
              <div v-show="snapTab === 'map'" class="map-wrap">
                <div ref="mapEl" class="traj-map"></div>
                <p v-if="!hasGeoTraj" class="map-empty muted">
                  Belum ada koordinat jejak untuk orang ini — baru terlihat di satu titik
                  atau kameranya belum punya koordinat.
                </p>
              </div>
            </div>
          </main>
        </div>
        <div class="modal-foot">
          <a class="m-btn" :href="snapDetail(selected, 'body')" download target="_blank">⬇ Download</a>
          <template v-if="enrollMode">
            <input v-model="enrollNameInput" placeholder="Nama identitas" class="enroll-input2" @keyup.enter="doEnroll" />
            <button class="m-btn primary" @click="doEnroll">Simpan</button>
            <button class="m-btn" @click="enrollMode = false">Batal</button>
          </template>
          <template v-else>
            <button class="m-btn primary" @click="enrollMode = true">👤 Daftarkan Identitas</button>
            <button class="m-btn danger" @click="deleteSnap">🗑 Hapus Foto</button>
          </template>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.muted { color: var(--txt-faint); font-size: 13px; }
.dim { color: var(--txt-faint); }
.cam-grid { margin-top: 12px; display: grid; grid-template-columns: repeat(auto-fit, minmax(460px, 1fr)); gap: 16px; }
.cam { margin: 0; background: #000; border: 1px solid var(--line-soft); border-radius: 10px; overflow: hidden; }
.cam img { width: 100%; display: block; aspect-ratio: 16/9; object-fit: cover; background: #f8fafc; }
.cam img.off { opacity: .25; }
.cam figcaption { padding: 9px 12px; font-size: 13px; font-weight: 600; background: var(--panel, #ffffff); }
.snap-filter { display: flex; gap: 8px; margin-top: 12px; }
.snap-filter button { font-size: 12px; padding: 5px 12px; border-radius: 7px; border: 1px solid var(--line-soft); background: transparent; color: var(--txt-faint); cursor: pointer; }
.snap-filter button.on { background: var(--ped); border-color: var(--ped); color: #04221d; font-weight: 700; }
.snap-grid { margin-top: 14px; display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 12px; max-height: 560px; overflow-y: auto; }
.snap { margin: 0; background: #f8fafc; border: 1px solid var(--line-soft); border-radius: 9px; overflow: hidden; cursor: pointer; transition: border-color .15s, transform .1s; }
.snap:hover { border-color: var(--ped); transform: translateY(-2px); }
.snap img { width: 100%; aspect-ratio: 3/4; object-fit: cover; display: block; background: #000; }
.snap figcaption { padding: 6px 8px; }
.snap-name { font-size: 12px; font-weight: 700; color: var(--txt-faint); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.snap-name.known { color: var(--ped); }
.snap-meta { font-size: 10px; color: var(--txt-faint); margin-top: 2px; }
.snap-attr { font-size: 10px; color: var(--txt-faint); text-transform: capitalize; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.7); display: flex; align-items: center; justify-content: center; z-index: 100; padding: 24px; }
.modal { background: #ffffff; border: 1px solid var(--line-soft); border-radius: 16px; width: min(1000px, 96vw); max-height: 92vh; display: flex; flex-direction: column; overflow: hidden; }
.modal-head { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--line-soft); }
.modal-head h3 { font-size: 16px; color: var(--ped); }
.modal-x { background: transparent; border: 1px solid var(--line-soft); color: var(--txt); width: 32px; height: 32px; border-radius: 8px; cursor: pointer; }
.modal-body { display: grid; grid-template-columns: 250px 1fr; gap: 18px; padding: 18px 20px; overflow-y: auto; }
@media (max-width: 760px) { .modal-body { grid-template-columns: 1fr; } }
.modal-thumb { width: 100%; aspect-ratio: 3/4; object-fit: cover; border-radius: 10px; background: #000; margin-bottom: 14px; }
.kv { display: flex; justify-content: space-between; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--line-soft); font-size: 12px; }
.kv span { color: var(--txt-faint); }
.kv b { text-align: right; }
.kv b.known { color: var(--ped); }
.char { margin-top: 12px; }
.char-label { font-size: 10px; color: var(--txt-faint); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
.char-chip { display: inline-block; font-size: 12px; padding: 4px 11px; border-radius: 999px; background: rgba(21,93,252,.12); color: var(--ped); margin-right: 6px; }
.traj { margin-top: 16px; }
.traj-list { border-left: 2px solid var(--line); margin-left: 4px; padding-left: 2px; }
.traj-row { display: flex; align-items: center; gap: 8px; padding: 5px 0 5px 10px; position: relative; font-size: 12px; }
.traj-dot { position: absolute; left: -7px; width: 8px; height: 8px; border-radius: 50%; background: var(--ped); border: 2px solid var(--panel); }
.traj-cam { flex: 1; font-weight: 600; }
.traj-time { color: var(--txt-faint); }
.modal-tabs { display: flex; gap: 8px; margin-bottom: 12px; }
.modal-tabs button { font-size: 12px; padding: 6px 13px; border-radius: 8px; border: 1px solid var(--line-soft); background: transparent; color: var(--txt-faint); cursor: pointer; }
.modal-tabs button.on { background: rgba(21,93,252,.15); border-color: var(--ped); color: var(--ped); font-weight: 700; }
.modal-img { background: #000; border-radius: 10px; overflow: hidden; min-height: 300px; display: flex; align-items: center; justify-content: center; }
.modal-img img { width: 100%; max-height: 56vh; object-fit: contain; display: block; }
.map-wrap { position: relative; width: 100%; height: 56vh; min-height: 360px; }
.traj-map { width: 100%; height: 100%; background: #e8edf3; }
.map-empty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  text-align: center; padding: 26px; background: #f8fafc; color: var(--txt-faint); font-size: 13px; z-index: 500; }
.modal-foot { display: flex; gap: 10px; align-items: center; padding: 14px 20px; border-top: 1px solid var(--line-soft); flex-wrap: wrap; }
.m-btn { font-size: 13px; padding: 9px 16px; border-radius: 9px; border: 1px solid var(--line-soft); background: transparent; color: var(--txt); cursor: pointer; text-decoration: none; }
.m-btn.primary { background: var(--ped); border-color: var(--ped); color: #04221d; font-weight: 700; }
.m-btn.danger { background: rgba(242,80,80,.15); border-color: var(--crit); color: var(--crit); }
.m-btn:hover { border-color: var(--ped); }
.enroll-input2 { padding: 9px 12px; border-radius: 8px; border: 1px solid var(--line-soft); background: #f8fafc; color: var(--txt); font-size: 13px; flex: 1; min-width: 180px; }
</style>
