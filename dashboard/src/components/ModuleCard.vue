<script setup>
import { useRouter } from 'vue-router';
const props = defineProps({
  to: String,
  accent: { type: String, default: 'var(--water)' },
  title: String,
  desc: String,
  stats: { type: Array, default: () => [] }, // [[value,label],...]
});
const router = useRouter();
</script>

<template>
  <div class="mod-card" :style="{ '--acc': accent }" @click="router.push(to)">
    <div class="m-strip"></div>
    <div class="m-go">Buka →</div>
    <h4>{{ title }}</h4>
    <p>{{ desc }}</p>
    <div class="m-stats">
      <div class="ms" v-for="(s, i) in stats" :key="i">
        <b>{{ s[0] }}</b><span>{{ s[1] }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mod-card {
  background: var(--panel); border: 1px solid var(--line); border-radius: var(--r);
  padding: 16px 18px; position: relative; cursor: pointer; transition: all 0.18s ease; overflow: hidden;
}
.mod-card:hover { border-color: color-mix(in srgb, var(--acc) 45%, transparent); transform: translateY(-2px); }
.m-strip { position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--acc); }
.m-go { position: absolute; top: 14px; right: 16px; font-size: 11px; color: var(--acc); font-weight: 600; opacity: 0; transition: opacity 0.18s; }
.mod-card:hover .m-go { opacity: 1; }
h4 { font-size: 14px; font-weight: 700; }
p { font-size: 11.5px; color: var(--txt-dim); margin-top: 5px; }
.m-stats { display: flex; gap: 18px; margin-top: 14px; }
.ms b { font-size: 17px; font-weight: 800; display: block; }
.ms span { font-size: 9px; color: var(--txt-faint); letter-spacing: 1px; text-transform: uppercase; }
</style>
