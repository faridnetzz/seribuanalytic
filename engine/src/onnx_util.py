"""Helper pemuat ONNX Runtime (GPU bila tersedia, fallback CPU)."""
import logging

log = logging.getLogger("engine.onnx")


def load_session(model_path: str):
    """Buat InferenceSession ONNX. Kembalikan None bila gagal/tak ada model."""
    if not model_path:
        return None
    try:
        import onnxruntime as ort
        providers = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"]
            if "CUDAExecutionProvider" in ort.get_available_providers()
            else ["CPUExecutionProvider"]
        )
        sess = ort.InferenceSession(model_path, providers=providers)
        log.info("Model dimuat: %s (%s)", model_path, sess.get_providers()[0])
        return sess
    except Exception as e:
        log.error("Gagal memuat model %s: %s", model_path, e)
        return None
