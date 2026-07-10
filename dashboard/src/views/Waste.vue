<script setup>
import { ref, onMounted, onUnmounted } from 'vue';
import { api } from '../api/client.js';
import { useStreamCleanup } from '../api/streams.js';
import KpiCard from '../components/KpiCard.vue';
import LineChart from '../components/LineChart.vue';

const rootEl = useStreamCleanup();   // putus stream MJPEG saat pindah halaman (cegah starvation koneksi)

const sum = ref(null);
const piles = ref([]);
const ranking = ref([]);
const heat = ref(null);
const loading = ref(true);
const notice = ref('');
let noticeTimer = null;
function flash(m) { notice.value = m; clearTimeout(noticeTimer); noticeTimer = setTimeout(() => (notice.value = ''), 4500); }

const streamBase = import.meta.env.VITE_STREAM_BASE || 'http://localhost:8090';
const cams = [
  { id: 'CAM-02', name: 'Gang Pasar Bawah' },
  { id: 'CAM-03', name: 'Pasar Gintung' },
];
const SEV = { low: 'Ringan', medium: 'Sedang', high: 'Berat', critical: 'Parah' };
const sevColor = { low: 'var(--ok)', medium: 'var(--warn)', high: 'var(--waste)', critical: 'var(--crit)' };
const STATUS = {
  bersih: { t: 'Bersih', c: 'var(--ok)' },
  kotor: { t: 'Kotor', c: 'var(--warn)' },
  sangat_kotor: { t: 'Sangat Kotor', c: 'var(--crit)' },
};
const time = (ts) => new Date(ts).toLocaleTimeString('id-ID', { timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit' });
const fmtDur = (s) => {
  s = Math.max(0, Math.round(s || 0));
  if (s >= 3600) return `${Math.floor(s / 3600)}j ${Math.round((s % 3600) / 60)}m`;
  if (s >= 60) return `${Math.round(s / 60)} mnt`;
  return `${s} dtk`;
};
const sevLabel = (s) => SEV[s] || s;

async function load() {
  try {
    [sum.value, piles.value, ranking.value, heat.value] = await Promise.all([
      api.waste(), api.wasteRecent(40), api.wasteRanking(), api.wasteHeatmap(),
    ]);
  } finally {
    loading.value = false;
  }
}
let timer = null;
onMounted(() => { load(); timer = setInterval(load, 8000); });
onUnmounted(() => { if (timer) clearInterval(timer); });

// Satu tombol laporan ke DLH (bukan per-kartu): rangkum tumpukan yang masih aktif.
function reportAllDlh() {
  const wa = sum.value?.contacts?.dlhWa;
  if (!wa) { flash('Nomor DLH belum diatur (DLH_WA)'); return; }
  const active = piles.value.filter((p) => p.status !== 'cleared');
  if (!active.length) { flash('Tidak ada tumpukan aktif untuk dilaporkan'); return; }
  const nm = sum.value?.contacts?.dlhName || 'DLH';
  const list = active.slice(0, 10).map((p) =>
    `• ${p.cameraName} (${p.cameraId}) — ${sevLabel(p.severity)}, ${fmtDur(p.durationSeconds)}, sejak ${time(p.firstSeen)}\n  Foto: ${streamBase}/snap-img/${p.snapshotId}?kind=body`).join('\n');
  const more = active.length > 10 ? `\n… dan ${active.length - 10} lainnya.` : '';
  const msg = `Halo ${nm}, terpantau ${active.length} TUMPUKAN SAMPAH belum diangkut di CCTV pemantauan:\n`
    + `${list}${more}\n\nDetail & foto tersedia di dashboard pemantauan. Mohon ditindaklanjuti. Terima kasih.`;
  window.open(`https://wa.me/${wa}?text=${encodeURIComponent(msg)}`, '_blank');
  active.forEach((p) => api.wasteReportPile(p.pileUid).catch(() => {}));
}
async function delPile(p) {
  if (!confirm('Hapus data tumpukan ini?')) return;
  try {
    await fetch(`${streamBase}/waste-snapshot-delete`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: p.snapshotId }),
    });
    try { await api.wasteDeletePile(p.pileUid); } catch {}
    load();
  } catch { flash('Gagal menghapus'); }
}
async function clearAll() {
  if (!piles.value.length) return;
  if (!confirm(`Hapus SEMUA ${piles.value.length} data tumpukan?`)) return;
  try {
    await fetch(`${streamBase}/waste-snapshots-clear`, { method: 'POST' });
    try { await api.wasteClearPiles(); } catch {}
    load(); flash('Semua data tumpukan dihapus');
  } catch { flash('Gagal menghapus'); }
}
</script>

<template>
  <section class="view" ref="rootEl">
    <div class="page-head">
      <div>
        <h2>Deteksi Sampah
          <span class="chip" style="background: rgba(245,158,11,.15); color: var(--waste)">PERSISTENSI + SLA</span>
        </h2>
        <p>Tiap tumpukan dilacak dari muncul s/d diangkut — bukan sekadar log. Status kebersihan pasar, durasi belum diangkut, jam rawan, dan ranking lokasi terkotor.</p>
      </div>
    </div>

    <p v-if="loading" class="muted">Memuat…</p>
    <template v-else-if="sum">
      <div class="kpi-grid">
        <KpiCard accent="var(--waste)" label="Tumpukan Aktif" :value="sum.activePiles" foot="terdeteksi saat ini" />
        <KpiCard accent="var(--crit)" label="Belum Diangkut" :value="sum.notCollected" foot="lewat ambang waktu" />
        <KpiCard accent="var(--waste)" label="Episode Hari Ini" :value="sum.todayEpisodes" foot="tumpukan muncul" />
        <KpiCard accent="var(--ok)" label="Rata-rata Waktu Angkut" :value="fmtDur(sum.avgResponseSeconds)" foot="SLA pengangkutan" />
      </div>

      <div class="card">
        <h3><span class="acc-dot" style="background: var(--waste)"></span>Status Kebersihan Pasar</h3>
        <div class="card-sub">Kondisi tiap titik berdasarkan tumpukan aktif sekarang</div>
        <div class="status-grid">
          <div class="status-box" v-for="c in sum.perCamera" :key="c.cameraId" :style="{ borderColor: STATUS[c.status].c }">
            <div class="status-dot" :style="{ background: STATUS[c.status].c }"></div>
            <div class="status-body">
              <b>{{ c.name }}</b>
              <span>{{ c.cameraId }} · {{ c.active }} tumpukan aktif</span>
            </div>
            <span class="status-tag" :style="{ color: STATUS[c.status].c, borderColor: STATUS[c.status].c }">{{ STATUS[c.status].t }}</span>
          </div>
        </div>
      </div>

      <div class="card">
        <h3><span class="acc-dot" style="background: var(--waste)"></span>Pantauan Langsung
          <span class="chip" style="background: rgba(242,80,80,.15); color: var(--crit)">● LIVE</span>
        </h3>
        <div class="card-sub">Video kamera realtime + label durasi tumpukan</div>
        <div class="cam-grid">
          <figure class="cam" v-for="c in cams" :key="c.id">
            <img :src="streamBase + '/stream/' + c.id" :alt="c.id" @error="(e) => e.target.classList.add('off')" />
            <figcaption>{{ c.id }} · <span class="dim">{{ c.name }}</span></figcaption>
          </figure>
        </div>
      </div>

      <div class="card">
        <h3><span class="acc-dot" style="background: var(--waste)"></span>Tumpukan Terdeteksi
          <span class="chip" style="background: rgba(245,158,11,.15); color: var(--waste)">{{ piles.length }}</span>
          <button v-if="piles.length" class="dlh-top" @click="reportAllDlh" title="Kirim rekap tumpukan sampah aktif ke DLH via WhatsApp">📲 Lapor DLH</button>
          <button v-if="piles.length" class="clear-all" @click="clearAll">🗑 Hapus Semua</button>
        </h3>
        <div class="card-sub">1 kartu = 1 tumpukan (muncul → diangkut). Klik <b>Lapor DLH</b> di kanan atas untuk kirim rekap tumpukan aktif + foto ke petugas.</div>
        <div class="pile-grid">
          <figure class="pile" v-for="p in piles" :key="p.pileUid">
            <img :src="`${streamBase}/snap-img/${p.snapshotId}?kind=body`" loading="lazy" />
            <figcaption>
              <div class="pile-top">
                <span class="sev" :style="{ background: sevColor[p.severity] }"></span>
                <b>{{ sevLabel(p.severity) }}</b>
                <span class="pill" :class="p.status">{{ p.status === 'cleared' ? 'Diangkut' : 'Aktif' }}</span>
              </div>
              <div class="pile-meta">{{ p.cameraName }}</div>
              <div class="pile-meta">⏱ {{ fmtDur(p.durationSeconds) }} · {{ time(p.firstSeen) }}</div>
              <div class="pile-btns">
                <button class="del-btn" @click="delPile(p)" title="Hapus tumpukan ini">🗑 Hapus</button>
              </div>
            </figcaption>
          </figure>
          <p v-if="!piles.length" class="muted">Belum ada tumpukan terdeteksi.</p>
        </div>
      </div>

      <div class="cols c-1-1">
        <div class="card">
          <h3><span class="acc-dot" style="background: var(--crit)"></span>Ranking Lokasi Terkotor</h3>
          <div class="card-sub">Total persistensi tumpukan hari ini</div>
          <div class="rank">
            <div class="rank-row" v-for="(r, i) in ranking" :key="r.cameraId">
              <span class="rank-no">{{ i + 1 }}</span>
              <div class="rank-body"><b>{{ r.cameraName }}</b><span>{{ r.piles }} tumpukan</span></div>
              <span class="rank-val mono">{{ r.persistMinutes }} mnt</span>
            </div>
            <p v-if="!ranking.length" class="muted">Belum ada data hari ini.</p>
          </div>
        </div>

        <div class="card">
          <h3><span class="acc-dot" style="background: var(--waste)"></span>Jam Rawan Sampah</h3>
          <div class="card-sub">Jumlah tumpukan muncul per jam · hari ini</div>
          <div style="margin-top: 14px" v-if="heat">
            <LineChart :series="heat.series" :labels="heat.labels.map((l, i) => (i % 3 === 0 ? l : ''))" accent="var(--waste)" />
          </div>
        </div>
      </div>
    </template>

    <div v-if="notice" class="toast">{{ notice }}</div>
  </section>
</template>

<style scoped>
.muted { color: var(--txt-faint); font-size: 13px; }
.dim { color: var(--txt-faint); }
.status-grid { margin-top: 12px; display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.status-box { display: flex; align-items: center; gap: 11px; padding: 12px 14px; border: 1px solid var(--line); border-left-width: 4px; border-radius: 10px; background: var(--panel); }
.status-dot { width: 12px; height: 12px; border-radius: 50%; flex: none; }
.status-body { flex: 1; min-width: 0; }
.status-body b { font-size: 13px; display: block; }
.status-body span { font-size: 11px; color: var(--txt-faint); }
.status-tag { font-size: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: .5px; padding: 3px 9px; border: 1px solid; border-radius: 999px; }
.cam-grid { margin-top: 12px; display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 14px; }
.cam { margin: 0; background: #000; border: 1px solid var(--line-soft); border-radius: 10px; overflow: hidden; }
.cam img { width: 100%; display: block; aspect-ratio: 16/9; object-fit: cover; background: #f8fafc; }
.cam img.off { opacity: .25; }
.cam figcaption { padding: 7px 10px; font-size: 12px; font-weight: 600; background: var(--panel, #ffffff); }
.dlh-top { margin-left: auto; font-size: 11px; font-weight: 700; padding: 4px 12px; border-radius: 7px; border: 1px solid rgba(37,211,102,.5); background: rgba(37,211,102,.12); color: #1a9e4b; cursor: pointer; }
.dlh-top:hover { background: rgba(37,211,102,.22); }
.clear-all { margin-left: 8px; font-size: 11px; font-weight: 700; padding: 4px 12px; border-radius: 7px; border: 1px solid rgba(228,0,20,.4); background: rgba(228,0,20,.10); color: var(--crit); cursor: pointer; }
.pile-grid { margin-top: 14px; display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 12px; max-height: 560px; overflow-y: auto; }
.pile { margin: 0; background: var(--panel); border: 1px solid var(--line-soft); border-radius: 10px; overflow: hidden; }
.pile img { width: 100%; aspect-ratio: 4/3; object-fit: cover; display: block; background: #000; }
.pile figcaption { padding: 8px 9px; }
.pile-top { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.pile-top b { flex: 1; }
.sev { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.pill { font-size: 9px; font-weight: 800; text-transform: uppercase; padding: 2px 6px; border-radius: 5px; }
.pill.active { background: rgba(228,0,20,.15); color: var(--crit); }
.pill.cleared { background: rgba(0,165,68,.15); color: var(--ok); }
.pile-meta { font-size: 10.5px; color: var(--txt-faint); margin-top: 2px; }
.pile-btns { display: flex; gap: 5px; margin-top: 7px; }
.del-btn { flex: 1; font-size: 11px; font-weight: 700; padding: 6px 0; border-radius: 7px; border: 1px solid rgba(228,0,20,.4); background: rgba(228,0,20,.10); color: var(--crit); cursor: pointer; }
.del-btn:hover { background: rgba(228,0,20,.2); }
.rank { margin-top: 10px; }
.rank-row { display: flex; align-items: center; gap: 11px; padding: 9px 0; border-bottom: 1px solid var(--line-soft); }
.rank-no { width: 22px; height: 22px; border-radius: 50%; background: var(--panel-2); display: grid; place-items: center; font-size: 11px; font-weight: 800; color: var(--txt-dim); }
.rank-body { flex: 1; } .rank-body b { font-size: 13px; display: block; } .rank-body span { font-size: 11px; color: var(--txt-faint); }
.rank-val { font-size: 13px; font-weight: 700; color: var(--crit); }
.toast { position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%); z-index: 200; background: #0e1626; color: #fff; padding: 11px 18px; border-radius: 10px; font-size: 13px; box-shadow: 0 8px 30px rgba(0,0,0,.5); }
</style>
