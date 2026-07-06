<script setup>
const props = defineProps({ alert: Object });
const accentMap = {
  pedestrian: 'var(--ped)', waste: 'var(--waste)',
  water: 'var(--water)', parking: 'var(--park)',
};
const time = (ts) =>
  new Date(ts).toLocaleTimeString('id-ID', { timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit' });
const meta = (m) => (Array.isArray(m) ? m : (() => { try { return JSON.parse(m); } catch { return []; } })());
</script>

<template>
  <div class="alert-row" :class="{ acked: alert.acknowledged }">
    <div class="a-bar" :style="{ background: accentMap[alert.module] }"></div>
    <div class="a-body">
      <div class="a-title">{{ alert.title }}</div>
      <div class="a-meta"><span v-for="(m, i) in meta(alert.meta)" :key="i">{{ m }}</span></div>
    </div>
    <div class="a-side">
      <span class="sev" :class="alert.severity">{{ alert.severity }}</span>
      <span class="a-time mono">{{ time(alert.ts) }}</span>
    </div>
  </div>
</template>

<style scoped>
.alert-row { display: flex; gap: 11px; padding: 11px 0; border-bottom: 1px solid var(--line-soft); }
.alert-row.acked { opacity: 0.45; }
.a-bar { width: 3px; border-radius: 3px; flex: none; }
.a-body { flex: 1; min-width: 0; }
.a-title { font-size: 12.5px; font-weight: 600; }
.a-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 5px; }
.a-meta span { font-size: 10px; color: var(--txt-faint); background: var(--panel-2); padding: 2px 7px; border-radius: 6px; }
.a-side { display: flex; flex-direction: column; align-items: flex-end; gap: 5px; }
.sev { font-size: 9px; font-weight: 700; text-transform: uppercase; padding: 2px 6px; border-radius: 5px; }
.sev.crit { background: rgba(228,0,20, 0.18); color: var(--crit); }
.sev.warn { background: rgba(245,158,11, 0.18); color: var(--warn); }
.sev.info { background: rgba(14,165,233, 0.18); color: var(--water); }
.a-time { font-size: 11px; color: var(--txt-dim); }
</style>
