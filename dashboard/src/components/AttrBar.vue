<script setup>
defineProps({
  label: String,
  pct: { type: Number, default: 0 },
  accent: { type: String, default: 'var(--ped)' },
});
</script>

<template>
  <div class="attr">
    <div class="attr-head"><span>{{ label }}</span><b>{{ pct }}%</b></div>
    <div class="bar"><i :style="{ width: pct + '%', background: accent }"></i></div>
  </div>
</template>

<style scoped>
.attr { margin-bottom: 11px; }
.attr-head { display: flex; justify-content: space-between; font-size: 11.5px; margin-bottom: 5px; }
.attr-head span { color: var(--txt-dim); }
.attr-head b { font-weight: 700; }
.bar { height: 6px; border-radius: 4px; background: var(--line); overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: 4px; transition: width 0.5s ease; }
</style>
