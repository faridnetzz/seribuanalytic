<script setup>
// Basis Data Wajah — menelusuri SEMUA snapshot yg tersimpan di engine (pagination),
// terpisah dari dashboard Pedestrian (yg sengaja cuma 80 terbaru biar ringan).
// Tanpa stream live / peta -> halaman ringan meski data banyak.
import { ref, onMounted, computed } from 'vue';
import { api } from '../api/client.js';

const streamBase = import.meta.env.VITE_STREAM_BASE || 'http://localhost:8090';
const PAGE = 80;                                   // 80 per halaman (sesuai permintaan)
const items = ref([]);
const total = ref(0);
const page = ref(1);
const filter = ref('');                            // '' | 'unknown' | 'known'
const loading = ref(true);
const pages = computed(() => Math.max(1, Math.ceil(total.value / PAGE)));
const rangeFrom = computed(() => total.value ? (page.value - 1) * PAGE + 1 : 0);
const rangeTo = computed(() => Math.min(page.value * PAGE, total.value));

const snapImg = (s) => `${streamBase}/snap-img/${s.id}`;
const snapDetail = (s, kind) => `${streamBase}/snap-img/${s.id}?kind=${kind}`;
const snapTime = (ts) => new Date(ts).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const fullTime = (ts) => new Date(ts).toLocaleString('id-ID');

async function load() {
  loading.value = true;
  try {
    const q = `?limit=${PAGE}&offset=${(page.value - 1) * PAGE}${filter.value ? '&identity=' + filter.value : ''}`;
    const r = await (await fetch(`${streamBase}/snapshots${q}`)).json();
    items.value = r.items || [];
    total.value = r.total || 0;
  } catch { items.value = []; total.value = 0; }
  finally { loading.value = false; }
}
function setFilter(v) { filter.value = v; page.value = 1; load(); }
function goto(p) {
  const np = Math.min(pages.value, Math.max(1, p));
  if (np !== page.value) { page.value = np; load(); window.scrollTo({ top: 0, behavior: 'smooth' }); }
}
onMounted(load);

// --- modal detail (foto utuh + enroll + hapus) ---
const selected = ref(null);
const tab = ref('pano');
const enrollMode = ref(false);
const nameInput = ref('');
function open(s) { selected.value = s; tab.value = s.hasScene ? 'pano' : 'body'; enrollMode.value = false; nameInput.value = s.name || ''; }
function close() { selected.value = null; }
async function doEnroll() {
  const name = nameInput.value.trim();
  if (!name) return;
  try {
    const r = await (await fetch(`${streamBase}/enroll-from-snapshot`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: selected.value.id, name }),
    })).json();
    if (r.ok) { close(); load(); } else alert(r.error || 'Gagal enroll');
  } catch { alert('Tidak bisa hubungi engine'); }
}
async function del() {
  if (!confirm('Hapus foto ini dari galeri? Data track-nya juga dihapus dari statistik.')) return;
  const s = selected.value;
  try {
    const r = await (await fetch(`${streamBase}/snapshot-delete`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: s.id }),
    })).json();
    if (r.ok) {
      if (s.cam && s.trackId != null) { try { await api.deletePedestrianTrack(s.cam, s.trackId); } catch {} }
      close(); load();
    }
  } catch { alert('Tidak bisa hubungi engine'); }
}
</script>

<template>
  <section class="view">
    <div class="page-head">
      <div>
        <h2>Basis Data Wajah
          <span class="chip" style="background: rgba(21,93,252,.15); color: var(--ped)">SEMUA CAPTURE</span>
        </h2>
        <p>Seluruh wajah/orang yang pernah tertangkap kamera, tersimpan di engine. Klik foto untuk lihat utuh, beri nama (enroll), atau hapus.</p>
      </div>
    </div>

    <div class="card">
      <div class="bar">
        <div class="snap-filter">
          <button :class="{ on: filter === '' }" @click="setFilter('')">Semua</button>
          <button :class="{ on: filter === 'unknown' }" @click="setFilter('unknown')">Belum dikenal</button>
          <button :class="{ on: filter === 'known' }" @click="setFilter('known')">Dikenali</button>
        </div>
        <span class="count" v-if="!loading">{{ total.toLocaleString('id-ID') }} wajah · menampilkan {{ rangeFrom }}–{{ rangeTo }}</span>
      </div>

      <p v-if="loading" class="muted">Memuat…</p>
      <template v-else>
        <div class="snap-grid">
          <figure class="snap" v-for="s in items" :key="s.id" @click="open(s)" title="Klik untuk lihat utuh">
            <img :src="snapImg(s)" loading="lazy" />
            <figcaption>
              <div class="snap-name" :class="{ known: s.name }">{{ s.name || 'Unknown' }}</div>
              <div class="snap-meta">{{ s.cam }} · {{ snapTime(s.ts) }}</div>
              <div class="snap-attr" v-if="s.gender">{{ s.gender === 'L' ? 'Pria' : 'Wanita' }}</div>
            </figcaption>
          </figure>
          <p v-if="!items.length" class="muted">Belum ada data.</p>
        </div>

        <div class="pager" v-if="pages > 1">
          <button :disabled="page === 1" @click="goto(1)">« Awal</button>
          <button :disabled="page === 1" @click="goto(page - 1)">‹ Sebelumnya</button>
          <span class="pg">Halaman <b>{{ page }}</b> dari {{ pages }}</span>
          <button :disabled="page === pages" @click="goto(page + 1)">Berikutnya ›</button>
          <button :disabled="page === pages" @click="goto(pages)">Akhir »</button>
        </div>
      </template>
    </div>

    <!-- Modal detail -->
    <div v-if="selected" class="modal-overlay" @click.self="close">
      <div class="modal">
        <div class="modal-head">
          <h3>Detail Wajah</h3>
          <button class="modal-x" @click="close">✕</button>
        </div>
        <div class="modal-body">
          <aside class="modal-side">
            <div class="kv"><span>Waktu</span><b>{{ fullTime(selected.ts) }}</b></div>
            <div class="kv"><span>Kamera</span><b>{{ selected.cam }}</b></div>
            <div class="kv"><span>Identitas</span><b :class="{ known: selected.name }">{{ selected.name || 'Unknown' }}</b></div>
            <div class="kv" v-if="selected.hasFace && selected.score"><span>Skor cocok</span><b>{{ (selected.score * 100).toFixed(0) }}%</b></div>
            <div class="kv" v-if="selected.gender"><span>Jenis kelamin</span><b>{{ selected.gender === 'L' ? 'Pria' : 'Wanita' }}</b></div>
          </aside>
          <main class="modal-main">
            <div class="modal-tabs">
              <button v-if="selected.hasScene" :class="{ on: tab === 'pano' }" @click="tab = 'pano'">🖼 Foto Panorama</button>
              <button :class="{ on: tab === 'body' }" @click="tab = 'body'">Foto Tubuh</button>
            </div>
            <div class="modal-img">
              <img v-show="tab === 'pano' && selected.hasScene" :src="snapDetail(selected, 'scene')" />
              <img v-show="tab === 'body'" :src="snapDetail(selected, 'body')" />
            </div>
          </main>
        </div>
        <div class="modal-foot">
          <a class="m-btn" :href="snapDetail(selected, 'body')" download target="_blank">⬇ Download</a>
          <template v-if="enrollMode">
            <input v-model="nameInput" placeholder="Nama identitas" class="enroll-input" @keyup.enter="doEnroll" />
            <button class="m-btn primary" @click="doEnroll">Simpan</button>
            <button class="m-btn" @click="enrollMode = false">Batal</button>
          </template>
          <template v-else>
            <button class="m-btn primary" @click="enrollMode = true">👤 Daftarkan Identitas</button>
            <button class="m-btn danger" @click="del">🗑 Hapus Foto</button>
          </template>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.muted { color: var(--txt-faint); font-size: 13px; }
.bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.count { font-size: 12px; color: var(--txt-faint); }
.snap-filter { display: flex; gap: 8px; }
.snap-filter button { font-size: 12px; padding: 5px 12px; border-radius: 7px; border: 1px solid var(--line-soft); background: transparent; color: var(--txt-faint); cursor: pointer; }
.snap-filter button.on { background: var(--ped); border-color: var(--ped); color: #04221d; font-weight: 700; }
.snap-grid { margin-top: 14px; display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 12px; }
.snap { margin: 0; background: #f8fafc; border: 1px solid var(--line-soft); border-radius: 9px; overflow: hidden; cursor: pointer; transition: border-color .15s, transform .1s; }
.snap:hover { border-color: var(--ped); transform: translateY(-2px); }
.snap img { width: 100%; aspect-ratio: 3/4; object-fit: cover; display: block; background: #000; }
.snap figcaption { padding: 6px 8px; }
.snap-name { font-size: 12px; font-weight: 700; color: var(--txt-faint); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.snap-name.known { color: var(--ped); }
.snap-meta { font-size: 10px; color: var(--txt-faint); margin-top: 2px; }
.snap-attr { font-size: 10px; color: var(--txt-faint); text-transform: capitalize; }
.pager { margin-top: 18px; display: flex; align-items: center; justify-content: center; gap: 8px; flex-wrap: wrap; }
.pager button { font-size: 12px; padding: 7px 13px; border-radius: 8px; border: 1px solid var(--line-soft); background: transparent; color: var(--txt); cursor: pointer; }
.pager button:hover:not(:disabled) { border-color: var(--ped); }
.pager button:disabled { opacity: .4; cursor: default; }
.pager .pg { font-size: 12px; color: var(--txt-faint); padding: 0 8px; }
.pager .pg b { color: var(--txt); }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.7); display: flex; align-items: center; justify-content: center; z-index: 100; padding: 24px; }
.modal { background: #ffffff; border: 1px solid var(--line-soft); border-radius: 16px; width: min(1000px, 96vw); max-height: 92vh; display: flex; flex-direction: column; overflow: hidden; }
.modal-head { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--line-soft); }
.modal-head h3 { font-size: 16px; color: var(--ped); }
.modal-x { background: transparent; border: 1px solid var(--line-soft); color: var(--txt); width: 32px; height: 32px; border-radius: 8px; cursor: pointer; }
.modal-body { display: grid; grid-template-columns: 250px 1fr; gap: 18px; padding: 18px 20px; overflow-y: auto; }
@media (max-width: 760px) { .modal-body { grid-template-columns: 1fr; } }
.kv { display: flex; justify-content: space-between; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--line-soft); font-size: 12px; }
.kv span { color: var(--txt-faint); }
.kv b { text-align: right; }
.kv b.known { color: var(--ped); }
.modal-tabs { display: flex; gap: 8px; margin-bottom: 12px; }
.modal-tabs button { font-size: 12px; padding: 6px 13px; border-radius: 8px; border: 1px solid var(--line-soft); background: transparent; color: var(--txt-faint); cursor: pointer; }
.modal-tabs button.on { background: rgba(21,93,252,.15); border-color: var(--ped); color: var(--ped); font-weight: 700; }
.modal-img { background: #000; border-radius: 10px; overflow: hidden; min-height: 300px; display: flex; align-items: center; justify-content: center; }
.modal-img img { width: 100%; max-height: 62vh; object-fit: contain; display: block; }
.modal-foot { display: flex; gap: 10px; align-items: center; padding: 14px 20px; border-top: 1px solid var(--line-soft); flex-wrap: wrap; }
.m-btn { font-size: 13px; padding: 9px 16px; border-radius: 9px; border: 1px solid var(--line-soft); background: transparent; color: var(--txt); cursor: pointer; text-decoration: none; }
.m-btn.primary { background: var(--ped); border-color: var(--ped); color: #04221d; font-weight: 700; }
.m-btn.danger { background: rgba(242,80,80,.15); border-color: var(--crit); color: var(--crit); }
.m-btn:hover { border-color: var(--ped); }
.enroll-input { padding: 9px 12px; border-radius: 8px; border: 1px solid var(--line-soft); background: #f8fafc; color: var(--txt); font-size: 13px; flex: 1; min-width: 180px; }
</style>
