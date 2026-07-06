# =====================================================================
# SIGAP — DeepStream edge inference (GPU)
# Base image NVIDIA DeepStream 7.0 (Triton). Butuh NVIDIA Container Toolkit.
# Aktifkan via: docker compose --profile gpu up deepstream
# =====================================================================
FROM nvcr.io/nvidia/deepstream:7.0-triton-multiarch

# Klien MQTT untuk protocol adapter nvmsgbroker (sudah tersedia di DS 7.0:
# /opt/nvidia/deepstream/deepstream/lib/libnvds_mqtt_proto.so).
RUN apt-get update && apt-get install -y --no-install-recommends \
      mosquitto-clients \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/sigap

# Konfigurasi pipeline di-mount sebagai volume dari ./deepstream/configs.
# Model (.onnx/.engine) ditaruh di ./deepstream/models (lihat README).

# Jalankan aplikasi referensi deepstream-app dengan config SIGAP.
# Ganti sesuai kebutuhan (mis. aplikasi C/Python custom).
CMD ["deepstream-app", "-c", "/opt/sigap/configs/deepstream_app_config.txt"]
