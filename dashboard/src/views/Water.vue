<script setup>
import { ref, onMounted, watch } from 'vue';
import { api } from '../api/client.js';
import KpiCard from '../components/KpiCard.vue';
import LineChart from '../components/LineChart.vue';

const sum = ref(null);
const loading = ref(true);
const selected = ref(null);
const series = ref([]);
const statusColor = { aman: 'var(--ok)', waspada: 'var(--warn)', siaga: 'var(--park)', bahaya: 'var(--crit)' };

async function load() {
  try {
    sum.value = await api.water();
    if (sum.value.stations.length) selected.value = sum.value.stations[0].cameraId;
  } finally {
    loading.value = false;
  }
}
async function loadSeries(cam) {
  if (!cam) return;
  const rows = await api.waterSeries(cam, 24);
  series.value = rows.map((r) => Number(r.levelM));
}
watch(selected, (c) => loadSeries(c));
onMounted(async () => { await load(); await loadSeries(selected.value); });
</script>

<template>
  <section class="view">
    <div class="page-head">
      <div>
        <h2>Deteksi Debit Air Sungai
          <span class="chip" style="background: rgba(14,165,233,.15); color: var(--water)">VIRTUAL STAFF GAUGE</span>
        </h2>
        <p>Estimasi ketinggian muka air dan status banjir berbasis penanda virtual pada citra kamera sungai.</p>
      </div>
    </div>

    <p v-if="loading" class="muted">Memuat…</p>
    <template v-else-if="sum">
      <div class="kpi-grid">
        <KpiCard v-for="s in sum.stations" :key="s.cameraId"
          :accent="statusColor[s.status] || 'var(--water)'"
          :label="`${s.cameraId} · ${s.cameraName}`"
          :value="`${Number(s.levelM).toFixed(2)} m`"
          :trend="s.trendCm30min > 0 ? 'up' : s.trendCm30min < 0 ? 'down' : 'flat'"
          :trendValue="`${s.trendCm30min > 0 ? '+' : ''}${s.trendCm30min} cm`"
          :foot="`Status: ${s.status}`" />
      </div>

      <div class="card">
        <div class="head-row">
          <div>
            <h3><span class="acc-dot" style="background: var(--water)"></span>Tren Ketinggian Air — 24 Jam</h3>
            <div class="card-sub">Deret pembacaan model staff-gauge</div>
          </div>
          <select v-model="selected" class="sel">
            <option v-for="s in sum.stations" :key="s.cameraId" :value="s.cameraId">{{ s.cameraId }} · {{ s.cameraName }}</option>
          </select>
        </div>
        <div style="margin-top: 14px">
          <LineChart v-if="series.length" :series="series" accent="var(--water)" :height="200" />
          <p v-else class="muted">Belum cukup data untuk grafik.</p>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.muted { color: var(--txt-faint); font-size: 13px; }
.head-row { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.sel { background: var(--panel-2); color: var(--txt); border: 1px solid var(--line); border-radius: 8px; padding: 7px 10px; font-size: 12px; }
</style>
