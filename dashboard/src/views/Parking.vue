<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue';
import { api } from '../api/client.js';
import KpiCard from '../components/KpiCard.vue';

const sum = ref(null);
const violations = ref([]);
const loading = ref(true);

// --- Video live + editor ROI (drawable) ---
const streamBase = import.meta.env.VITE_STREAM_BASE || 'http://localhost:8090';
const parkCams = [
  { id: 'CAM-01', name: 'Yos Sudarso - M. Salim' },
  { id: 'CAM-04', name: 'ZA Pagar Alam Depan DKP' },
];
const editingCam = ref(null);
const points = ref([]);                       // [[x,y],...] ternormalisasi 0..1
const svgPoints = computed(() => points.value.map((p) => `${p[0] * 100},${p[1] * 100}`).join(' '));
const snapUrl = (cam) => `${streamBase}/snapshot/${cam}?t=${Date.now()}`;

// ROI nyata dari engine per kamera -> "Zona Terpantau" = jumlah ROI yang digambar.
const roiInfo = ref({});                       // cam -> {polygon, dwellSeconds}
const dwellEdit = ref({});                     // cam -> ambang DETIK (input dashboard)
const zonesMonitored = computed(
  () => Object.values(roiInfo.value).filter((r) => (r.polygon || []).length >= 3).length
);
async function loadRois() {
  const out = {}, ed = {};
  for (const c of parkCams) {
    try { out[c.id] = await (await fetch(`${streamBase}/roi/${c.id}`)).json(); }
    catch { out[c.id] = { polygon: [], dwellSeconds: 20 }; }
    ed[c.id] = Math.round(out[c.id].dwellSeconds || 20);
  }
  roiInfo.value = out;
  dwellEdit.value = ed;
}

// Notifikasi ringkas (speaker/dishub).
const notice = ref('');
let noticeTimer = null;
function flash(msg) { notice.value = msg; clearTimeout(noticeTimer); noticeTimer = setTimeout(() => (notice.value = ''), 4500); }

async function startEdit(cam) {
  editingCam.value = cam;
  try {
    const r = await (await fetch(`${streamBase}/roi/${cam}`)).json();
    points.value = r.polygon || [];
    dwellEdit.value[cam] = Math.round(r.dwellSeconds || 20);
  } catch { points.value = []; dwellEdit.value[cam] = 20; }
}
function addPoint(e) {
  const rect = e.currentTarget.getBoundingClientRect();
  points.value.push([(e.clientX - rect.left) / rect.width, (e.clientY - rect.top) / rect.height]);
}
function undo() { points.value.pop(); }
async function saveRoi(cam) {
  await fetch(`${streamBase}/roi/${cam}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ polygon: points.value, dwellSeconds: Math.max(5, dwellEdit.value[cam] || 20) }),
  });
  editingCam.value = null;
  loadRois();
}
// Ubah AMBANG WAKTU saja (detik) tanpa menggambar ulang ROI — langsung dari dashboard.
async function saveDwell(cam) {
  const poly = (roiInfo.value[cam] || {}).polygon || [];
  if (poly.length < 3) { flash('Gambar ROI dulu sebelum atur ambang'); return; }
  const secs = Math.max(5, Math.round(dwellEdit.value[cam] || 20));
  await fetch(`${streamBase}/roi/${cam}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ polygon: poly, dwellSeconds: secs }),
  });
  loadRois();
  flash(`⏱ Ambang ${cam} = ${secs} detik`);
}

// --- Tombol aksi: Speaker (peringatan suara) + Hubungi Dishub (wa.me + foto) ---
async function callSpeaker(cam) {
  try {
    const r = await api.parkingSpeaker(cam);
    flash(r.delivered ? `🔊 Peringatan suara dikirim ke speaker ${cam}`
                      : `🔊 (Simulasi) Peringatan ${cam} — IP speaker belum dikonfigurasi`);
  } catch { flash('Gagal menghubungi speaker command center'); }
}
// Satu tombol laporan ke Dishub (bukan per-snapshot): rangkum pelanggaran aktif.
function contactDishub() {
  const wa = sum.value?.contacts?.dishubWa;
  if (!wa) { flash('Nomor WhatsApp Dishub belum diatur (DISHUB_WA)'); return; }
  const nm = sum.value?.contacts?.dishubName || 'Dishub';
  const list = parkSnaps.value.slice(0, 10).map(s =>
    `• ${s.cam} — ${s.vehicleType} (ID #${s.trackId}), diam ${psDur(s.dwellSeconds)}, ${psTime(s.ts)}`).join('\n');
  const more = parkSnaps.value.length > 10 ? `\n… dan ${parkSnaps.value.length - 10} lainnya.` : '';
  const msg = `Halo ${nm}, terpantau ${parkSnaps.value.length} PELANGGARAN PARKIR LIAR di CCTV pemantauan:\n`
    + `${list}${more}\n\nDetail & foto tersedia di dashboard pemantauan. Mohon ditindaklanjuti. Terima kasih.`;
  window.open(`https://wa.me/${wa}?text=${encodeURIComponent(msg)}`, '_blank');
}
const time = (ts) => new Date(ts).toLocaleTimeString('id-ID', { timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit' });
const dwell = (s) => (s >= 60 ? `${Math.round(s / 60)} mnt` : `${s} dtk`);
const dwellClass = (s) => (s >= 600 ? 'crit' : s >= 300 ? 'warn' : '');

// --- Snapshot pelanggaran (mobil ditangkap saat tembus 2 menit) ---
const parkSnaps = ref([]);
const psTime = (ts) => new Date(ts).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const psDur = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
async function loadParkSnaps() {
  try { parkSnaps.value = (await (await fetch(`${streamBase}/park-snapshots?limit=60`)).json()).items || []; } catch {}
}
async function deleteParkSnap(s) {
  if (!confirm('Hapus foto pelanggaran ini beserta datanya?')) return;
  try {
    await fetch(`${streamBase}/park-snapshot-delete`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: s.id }),
    });
    try { await api.parkingDeleteViolation(s.id); } catch {}   // hapus baris DB juga
    loadParkSnaps(); load();
  } catch { flash('Gagal menghapus'); }
}
async function clearParkSnaps() {
  if (!parkSnaps.value.length) return;
  if (!confirm(`Hapus SEMUA ${parkSnaps.value.length} foto pelanggaran + datanya?`)) return;
  try {
    await fetch(`${streamBase}/park-snapshots-clear`, { method: 'POST' });
    try { await api.parkingClearViolations(); } catch {}
    loadParkSnaps(); load();
    flash('Semua data pelanggaran dihapus');
  } catch { flash('Gagal menghapus'); }
}
let psTimer = null;
onMounted(() => { loadParkSnaps(); loadRois(); psTimer = setInterval(loadParkSnaps, 8000); });
onUnmounted(() => { if (psTimer) clearInterval(psTimer); });

async function load() {
  try {
    [sum.value, violations.value] = await Promise.all([api.parking(), api.parkingViolations(30)]);
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
        <h2>Deteksi Parkir Liar
          <span class="chip" style="background: rgba(225,29,72,.15); color: var(--park)">ZONA + DWELL TIME</span>
        </h2>
        <p>Kendaraan yang berhenti melewati ambang waktu di zona terlarang terdeteksi otomatis via tracker + poligon zona.</p>
      </div>
    </div>

    <p v-if="loading" class="muted">Memuat…</p>
    <template v-else-if="sum">
      <div class="kpi-grid">
        <KpiCard accent="var(--park)" label="Pelanggaran Hari Ini" :value="sum.today" foot="total terdeteksi" />
        <KpiCard accent="var(--crit)" label="Sedang Aktif" :value="sum.active" foot="kendaraan di zona saat ini" />
        <KpiCard accent="var(--park)" label="Zona Terpantau" :value="zonesMonitored" foot="ROI digambar" />
        <KpiCard accent="var(--park)" label="Rata-rata Durasi Parkir" :value="dwell(sum.avgDwellSeconds)" foot="kendaraan melanggar" />
      </div>

      <div class="card">
        <h3><span class="acc-dot" style="background: var(--park)"></span>Pantauan & Zona Parkir
          <span class="chip" style="background: rgba(242,80,80,.15); color: var(--crit)">● LIVE</span>
        </h3>
        <div class="card-sub">Klik <b>Atur ROI</b> untuk menggambar area terlarang. Ubah <b>ambang waktu (detik)</b> langsung di bawah tiap kamera lalu <b>Simpan</b>. Kendaraan diam melebihi ambang di dalam ROI = parkir liar (1 kendaraan = 1 catatan, difinalisasi saat pergi). <b>🔊 Speaker</b> mengirim peringatan suara ke lokasi.</div>
        <div class="park-grid">
          <div class="pcam" v-for="c in parkCams" :key="c.id">
            <div class="frame">
              <img v-if="editingCam !== c.id" :src="streamBase + '/stream/' + c.id" :alt="c.id"
                   @error="(e) => e.target.classList.add('off')" />
              <template v-else>
                <img :src="snapUrl(c.id)" :alt="c.id" />
                <svg class="roi-svg" viewBox="0 0 100 100" preserveAspectRatio="none" @click="addPoint">
                  <polygon v-if="points.length > 1" :points="svgPoints"
                           fill="rgba(255,200,40,.18)" stroke="#ffc828" stroke-width="0.4" />
                  <circle v-for="(p, i) in points" :key="i" :cx="p[0] * 100" :cy="p[1] * 100" r="0.9" fill="#ffc828" />
                </svg>
              </template>
            </div>
            <div class="pcam-bar">
              <span class="pcam-name">{{ c.id }} · <span class="dim">{{ c.name }}</span></span>
              <div class="pcam-btns" v-if="editingCam === c.id">
                <label class="thr-input">Ambang
                  <input type="number" min="5" max="3600" v-model.number="dwellEdit[c.id]" /> dtk</label>
                <button @click="undo">↶ Undo</button>
                <button @click="points = []">Bersihkan</button>
                <button class="primary" @click="saveRoi(c.id)">Simpan ({{ points.length }})</button>
                <button @click="editingCam = null">Batal</button>
              </div>
              <div class="pcam-btns" v-else>
                <label class="thr-input" title="Ambang waktu parkir liar (detik)">⏱
                  <input type="number" min="5" max="3600" v-model.number="dwellEdit[c.id]" /> dtk</label>
                <button class="thr-save" @click="saveDwell(c.id)">Simpan</button>
                <button class="spk" @click="callSpeaker(c.id)">🔊 Speaker</button>
                <button class="edit-btn" @click="startEdit(c.id)">✏ Atur ROI</button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <h3><span class="acc-dot" style="background: var(--park)"></span>Snapshot Pelanggaran
          <span class="chip" style="background: rgba(225,29,72,.15); color: var(--park)">{{ parkSnaps.length }}</span>
          <button v-if="parkSnaps.length" class="dishub-top" @click="contactDishub" title="Kirim laporan pelanggaran ke Dishub via WhatsApp">📲 Hubungi Dishub</button>
          <button v-if="parkSnaps.length" class="clear-all" @click="clearParkSnaps">🗑 Hapus Semua</button>
        </h3>
        <div class="card-sub">Foto kendaraan otomatis ditangkap <b>sekali</b> saat pertama tembus ambang di ROI. <b>1 kendaraan = 1 foto</b>; durasi difinalisasi (mulai diam s/d pergi) saat kendaraan meninggalkan zona.</div>
        <div class="psnap-grid">
          <figure class="psnap" v-for="s in parkSnaps" :key="s.id">
            <img :src="`${streamBase}/snap-img/${s.id}?kind=body`" loading="lazy" />
            <figcaption>
              <div class="psnap-id">#{{ s.trackId }} · <span style="text-transform:capitalize">{{ s.vehicleType }}</span></div>
              <div class="psnap-meta">{{ s.cam }} · diam {{ psDur(s.dwellSeconds) }}</div>
              <div class="psnap-meta">{{ psTime(s.ts) }}</div>
              <button class="del-btn" @click="deleteParkSnap(s)" title="Hapus foto + data pelanggaran">
                🗑 Hapus</button>
            </figcaption>
          </figure>
          <p v-if="!parkSnaps.length" class="muted">Belum ada pelanggaran (kendaraan diam melebihi ambang di dalam ROI).</p>
        </div>
      </div>

      <div class="cols c-2-1">
        <div class="card">
          <h3><span class="acc-dot" style="background: var(--park)"></span>Pelanggaran Terbaru</h3>
          <div class="card-sub">Urut waktu terbaru</div>
          <div class="tbl">
            <div class="tr th"><span>Kamera</span><span>Zona</span><span>Kendaraan</span><span>Durasi</span><span>Status</span><span>Waktu</span></div>
            <div class="tr" v-for="v in violations" :key="v.id">
              <span>{{ v.cameraId }}</span>
              <span class="dim">{{ v.zoneName || '–' }}</span>
              <span>{{ v.vehicleType || '–' }}</span>
              <span class="mono" :class="dwellClass(v.dwellSeconds)">{{ dwell(v.dwellSeconds) }}</span>
              <span><span class="pill" :class="v.status">{{ v.status }}</span></span>
              <span class="mono dim">{{ time(v.ts) }}</span>
            </div>
            <p v-if="!violations.length" class="muted">Belum ada pelanggaran.</p>
          </div>
        </div>

        <div class="card">
          <h3><span class="acc-dot" style="background: var(--park)"></span>Per Jenis Kendaraan</h3>
          <div class="card-sub">Distribusi hari ini</div>
          <div style="margin-top: 12px">
            <div class="veh" v-for="b in sum.byVehicle" :key="b.vehicleType">
              <span>{{ b.vehicleType }}</span><b>{{ b.total }}</b>
            </div>
            <p v-if="!sum.byVehicle.length" class="muted">Belum ada data.</p>
          </div>
        </div>
      </div>
    </template>

    <div v-if="notice" class="toast">{{ notice }}</div>
  </section>
</template>

<style scoped>
.muted { color: var(--txt-faint); font-size: 13px; }
.tbl { margin-top: 12px; }
.tr { display: grid; grid-template-columns: 0.8fr 1.5fr 1fr 0.8fr 0.9fr 0.8fr; gap: 8px; padding: 9px 0; border-bottom: 1px solid var(--line-soft); font-size: 12px; align-items: center; }
.tr.th { color: var(--txt-faint); font-size: 10px; text-transform: uppercase; letter-spacing: 1px; }
.dim { color: var(--txt-faint); }
.mono.warn { color: var(--warn); font-weight: 700; }
.mono.crit { color: var(--crit); font-weight: 700; }
.pill { font-size: 9px; font-weight: 700; text-transform: uppercase; padding: 2px 7px; border-radius: 5px; }
.pill.active { background: rgba(228,0,20,.18); color: var(--crit); }
.pill.cleared { background: rgba(0,165,68,.15); color: var(--ok); }
.veh { display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid var(--line-soft); font-size: 13px; text-transform: capitalize; }
.veh b { font-weight: 700; }
.park-grid { margin-top: 12px; display: grid; grid-template-columns: repeat(auto-fit, minmax(460px, 1fr)); gap: 16px; }
.pcam { background: #000; border: 1px solid var(--line-soft); border-radius: 10px; overflow: hidden; }
.frame { position: relative; line-height: 0; }
.frame img { width: 100%; display: block; aspect-ratio: 16/9; object-fit: cover; background: #f8fafc; }
.frame img.off { opacity: .25; }
.roi-svg { position: absolute; inset: 0; width: 100%; height: 100%; cursor: crosshair; }
.pcam-bar { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 10px; background: var(--panel, #ffffff); flex-wrap: wrap; }
.pcam-name { font-size: 12px; font-weight: 600; }
.pcam-btns { display: flex; gap: 6px; flex-wrap: wrap; }
.pcam button { font-size: 11px; padding: 4px 9px; border-radius: 6px; border: 1px solid var(--line-soft); background: transparent; color: var(--txt); cursor: pointer; }
.pcam button.primary { background: var(--park); border-color: var(--park); color: #fff; font-weight: 700; }
.pcam button:hover { border-color: var(--park); }
.muted { color: var(--txt-faint); font-size: 13px; }
.psnap-grid { margin-top: 14px; display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; max-height: 520px; overflow-y: auto; }
.psnap { margin: 0; background: #f8fafc; border: 1px solid var(--line-soft); border-radius: 9px; overflow: hidden; }
.psnap img { width: 100%; aspect-ratio: 4/3; object-fit: cover; display: block; background: #000; }
.psnap figcaption { padding: 6px 9px; }
.psnap-id { font-size: 12px; font-weight: 700; color: var(--crit); }
.psnap-meta { font-size: 10px; color: var(--txt-faint); margin-top: 1px; }
.dishub-top { margin-left: auto; font-size: 11px; font-weight: 700; padding: 4px 12px; border-radius: 7px; border: 1px solid rgba(37,211,102,.5); background: rgba(37,211,102,.12); color: #25d366; cursor: pointer; }
.dishub-top:hover { background: rgba(37,211,102,.22); }
.del-btn { margin-top: 6px; width: 100%; font-size: 11px; font-weight: 700; padding: 6px 0; border-radius: 7px; border: 1px solid rgba(228,0,20,.4); background: rgba(228,0,20,.10); color: var(--crit); cursor: pointer; }
.del-btn:hover { background: rgba(228,0,20,.2); }
.clear-all { margin-left: 8px; font-size: 11px; font-weight: 700; padding: 4px 12px; border-radius: 7px; border: 1px solid rgba(228,0,20,.4); background: rgba(228,0,20,.10); color: var(--crit); cursor: pointer; }
.clear-all:hover { background: rgba(228,0,20,.2); }
.thr { color: var(--txt-faint); font-weight: 500; }
.thr-input { font-size: 11px; color: var(--txt-faint); display: flex; align-items: center; gap: 5px; }
.thr-input input { width: 52px; padding: 3px 6px; border-radius: 6px; border: 1px solid var(--line-soft); background: #f8fafc; color: var(--txt); font-size: 12px; }
.pcam button.thr-save { border-color: rgba(225,29,72,.5); color: var(--park); }
.pcam button.thr-save:hover { background: rgba(225,29,72,.15); }
.pcam button.spk { border-color: rgba(255,200,40,.5); color: #ffc828; }
.pcam button.spk:hover { background: rgba(255,200,40,.15); }
.toast { position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%); z-index: 200; background: #ffffff; border: 1px solid var(--park); color: var(--txt); padding: 11px 18px; border-radius: 10px; font-size: 13px; box-shadow: 0 8px 30px rgba(0,0,0,.5); }
</style>
