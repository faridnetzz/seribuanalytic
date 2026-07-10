import { ref, onBeforeUnmount } from 'vue';

// Stream MJPEG (<img src=".../stream/<cam>">) menahan 1 koneksi HTTP TERBUKA
// selama-lamanya. Browser membatasi ~6 koneksi per origin — dan seluruh sistem
// (API, WebSocket, stream, gambar) berbagi satu origin lewat nginx. Meninggalkan
// halaman kamera TANPA menutup stream membuat koneksi mati menumpuk sampai kuota
// habis, lalu fetch halaman berikutnya (mis. /api/pedestrian/summary) MENGANTRE
// tanpa batas -> halaman nyangkut di "Memuat…".
//
// Pakai: const rootEl = useStreamCleanup(); lalu <section ... ref="rootEl">.
// Saat view di-unmount (pindah halaman), semua <img> stream di dalamnya diputus
// -> slot koneksi browser langsung bebas untuk halaman berikutnya.
export function useStreamCleanup() {
  const rootEl = ref(null);
  onBeforeUnmount(() => {
    rootEl.value?.querySelectorAll('img[src*="/stream/"]').forEach((img) => {
      img.src = '';   // putus koneksi MJPEG SEGERA (jangan tunggu GC/teardown browser)
    });
  });
  return rootEl;
}
