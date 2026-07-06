<script setup>
import { ref, onMounted, computed } from 'vue';
import { api } from '../api/client.js';
import { useLiveStore } from '../stores/live.js';
import KpiCard from '../components/KpiCard.vue';
import ModuleCard from '../components/ModuleCard.vue';
import AlertRow from '../components/AlertRow.vue';
import LineChart from '../components/LineChart.vue';
import Donut from '../components/Donut.vue';

const live = useLiveStore();
const data = ref(null);
const cameras = ref([]);
const faces = ref(0);                          // wajah terdeteksi (galeri snapshot engine)
const loading = ref(true);
const streamBase = import.meta.env.VITE_STREAM_BASE || 'http://localhost:8090';
const accentByModule = { pedestrian: 'var(--ped)', waste: 'var(--waste)', water: 'var(--water)', parking: 'var(--park)' };
const routeByModule = { pedestrian: '/pedestrian', waste: '/waste', water: '/water', parking: '/parking' };

async function load() {
  try {
    const [ov, cams] = await Promise.all([api.overview(), api.cameras()]);
    data.value = ov;
    cameras.value = cams;
  } catch (e) {
    console.error('Gagal memuat overview:', e.message);
  } finally {
    loading.value = false;
  }
  // Wajah terdeteksi = jumlah snapshot wajah di galeri (semua snapshot kini ada wajah).
  try {
    faces.value = ((await (await fetch(`${streamBase}/snapshots?limit=500`)).json()).items || []).length;
  } catch {}
}
onMounted(load);

const trend = (pct) => (pct == null ? 'flat' : pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat');
const trendVal = (pct) => (pct == null ? '0' : `${pct > 0 ? '+' : ''}${pct}%`);
const donutSegs = computed(() =>
  (data.value?.contribution ?? []).map((c) => ({ v: c.total, c: accentByModule[c.module] }))
);
</script>

<template>
  <section class="view">
    <div class="page-head">
      <div>
        <h2>Ringkasan Kota
          <span class="chip" style="background: rgba(14,165,233,.15); color: var(--water)">REAL-TIME</span>
        </h2>
        <p>Pemantauan terpadu 8 titik kamera CCTV kota dengan 4 modul kecerdasan buatan berjalan paralel di edge.</p>
      </div>
    </div>

    <p v-if="loading" class="muted">Memuat data…</p>

    <template v-else-if="data">
      <div class="kpi-grid">
        <KpiCard accent="var(--ped)" label="Pedestrian Counting"
          :value="data.kpi.pedestrianTracked.toLocaleString('id-ID')" foot="orang terlacak hari ini" />
        <KpiCard accent="var(--ped)" label="Wajah Terdeteksi"
          :value="faces.toLocaleString('id-ID')" foot="tertangkap kamera" />
        <KpiCard accent="var(--park)" label="Pelanggaran Parkir"
          :value="data.kpi.parkingViolations" foot="hari ini" />
        <KpiCard accent="var(--waste)" label="Deteksi Sampah"
          :value="(data.kpi.wasteDetections ?? 0).toLocaleString('id-ID')" foot="hari ini" />
      </div>

      <div class="mod-grid">
        <ModuleCard v-for="m in data.modules" :key="m.code" :to="routeByModule[m.code]"
          :accent="accentByModule[m.code]" :title="m.name" :desc="m.description" :stats="m.stats" />
      </div>

      <div class="cols c-2-1">
        <div class="card">
          <h3><span class="acc-dot" style="background: var(--water)"></span>Volume Deteksi per Jam</h3>
          <div class="card-sub">Akumulasi seluruh modul · hari ini</div>
          <div style="margin-top: 14px">
            <LineChart :series="data.hourly.series"
              :labels="data.hourly.labels.map((l, i) => (i % 3 === 0 ? l : ''))" accent="var(--water)" />
          </div>
        </div>

        <div class="card">
          <h3><span class="acc-dot" style="background: var(--crit)"></span>Aliran Alert Terkini</h3>
          <div class="card-sub">Notifikasi lintas modul · live</div>
          <div class="alert-feed">
            <AlertRow v-for="a in live.alerts.slice(0, 8)" :key="a.id" :alert="a" />
            <p v-if="!live.alerts.length" class="muted">Belum ada alert.</p>
          </div>
        </div>
      </div>

      <div class="cols c-1-1" style="margin-top: 14px">
        <div class="card">
          <h3><span class="acc-dot" style="background: var(--ped)"></span>Kontribusi per Modul</h3>
          <div class="card-sub">Distribusi total deteksi hari ini</div>
          <div class="donut-wrap">
            <Donut :segments="donutSegs" />
            <div class="legend">
              <div class="leg-row" v-for="c in data.contribution" :key="c.module">
                <i :style="{ background: accentByModule[c.module] }"></i>
                <span>{{ c.module }}</span><b>{{ c.pct }}%</b>
              </div>
            </div>
          </div>
        </div>

        <div class="card">
          <h3><span class="acc-dot" style="background: var(--water)"></span>Peta Sebaran Kamera</h3>
          <div class="card-sub">{{ cameras.length }} titik · Bandar Lampung</div>
          <div class="cam-list">
            <div class="cam" v-for="c in cameras" :key="c.id">
              <span class="cam-dot" :class="c.status"></span>
              <div class="cam-body">
                <b>{{ c.id }} · {{ c.name }}</b>
                <span>{{ c.area }} — {{ c.modules.join(', ') }}</span>
              </div>
              <span class="cam-count mono">{{ c.detections_today }}</span>
            </div>
          </div>
        </div>
      </div>

      <p class="foot-note">SIGAP · data deteksi dihasilkan oleh pipeline edge (DeepStream/simulator) dan dialirkan via MQTT → PostgreSQL.</p>
    </template>
  </section>
</template>

<style scoped>
.muted { color: var(--txt-faint); font-size: 13px; padding: 8px 0; }
.alert-feed { margin-top: 8px; max-height: 360px; overflow-y: auto; }
.donut-wrap { display: flex; align-items: center; gap: 26px; padding: 8px 4px; }
.legend { flex: 1; }
.leg-row { display: flex; align-items: center; gap: 9px; padding: 7px 0; border-bottom: 1px solid var(--line-soft); }
.leg-row i { width: 11px; height: 11px; border-radius: 3px; }
.leg-row span { font-size: 12.5px; color: var(--txt-dim); flex: 1; text-transform: capitalize; }
.leg-row b { font-size: 13px; font-weight: 700; }
.cam-list { margin-top: 10px; max-height: 320px; overflow-y: auto; }
.cam { display: flex; align-items: center; gap: 11px; padding: 9px 0; border-bottom: 1px solid var(--line-soft); }
.cam-dot { width: 9px; height: 9px; border-radius: 50%; flex: none; background: var(--ok); }
.cam-dot.degraded { background: var(--warn); }
.cam-dot.offline { background: var(--crit); }
.cam-body { flex: 1; min-width: 0; }
.cam-body b { font-size: 12.5px; display: block; }
.cam-body span { font-size: 10.5px; color: var(--txt-faint); }
.cam-count { font-size: 13px; font-weight: 700; color: var(--txt-dim); }
.foot-note { margin-top: 18px; font-size: 11px; color: var(--txt-faint); }
</style>
