<script setup>
const props = defineProps({
  accent: { type: String, default: 'var(--water)' },
  label: String,
  value: [String, Number],
  trend: { type: String, default: 'flat' }, // up | down | flat
  trendValue: String,
  foot: String,
});
const arrow = { up: '▲', down: '▼', flat: '■' };
</script>

<template>
  <div class="kpi" :style="{ '--acc': accent }">
    <div class="k-label">{{ label }}</div>
    <div class="k-val">{{ value }}</div>
    <div class="k-foot">
      <span class="trend" :class="trend" v-if="trendValue">{{ arrow[trend] }} {{ trendValue }}</span>
      <span class="ft">{{ foot }}</span>
    </div>
  </div>
</template>

<style scoped>
.kpi {
  background: var(--panel); border: 1px solid var(--line); border-radius: var(--r);
  padding: 16px 18px; position: relative; overflow: hidden;
}
.kpi::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--acc); }
.k-label { font-size: 11.5px; color: var(--txt-dim); font-weight: 500; }
.k-val { font-size: 30px; font-weight: 800; margin: 8px 0 6px; letter-spacing: 0.3px; }
.k-foot { display: flex; align-items: center; gap: 9px; font-size: 11px; }
.trend { font-weight: 700; }
.trend.up { color: var(--ok); }
.trend.down { color: var(--crit); }
.trend.flat { color: var(--txt-faint); }
.ft { color: var(--txt-faint); }
</style>
