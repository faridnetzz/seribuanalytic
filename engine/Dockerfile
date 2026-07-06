# =====================================================================
# SIGAP — Engine inferensi Python (GPU) — runtime Ultralytics YOLO
# "Otak" analitik: menjalankan model best.pt 4 modul, mengonsumsi metadata
# perception dari DeepStream, lalu menerbitkan event final ke MQTT.
#
# Base: PyTorch resmi (torch+CUDA sudah ada) → ultralytics tinggal pakai.
# =====================================================================
# cudnn9 agar selaras: torch 2.4 (cudnn9) + onnxruntime-gpu CUDA-12 (butuh cudnn9).
FROM pytorch/pytorch:2.4.0-cuda12.1-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Jakarta

# libGL/glib utk OpenCV; build-essential (g++) utk compile ekstensi Cython insightface.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 ffmpeg build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/engine

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# onnxruntime-gpu build CUDA-12 (cocok base cuda12.1+cudnn8). insightface menarik
# onnxruntime CPU; ganti dengan build GPU CUDA-12 dari index resmi Microsoft.
RUN pip uninstall -y onnxruntime onnxruntime-gpu \
 && pip install --no-cache-dir onnxruntime-gpu==1.18.1 \
      --extra-index-url https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/

# Agar onnxruntime-gpu menemukan lib CUDA-12 (cublasLt/cudart/curand/cufft di
# /opt/conda/lib) + cudnn9 (di torch/lib) -> FR jalan di GPU, bukan CPU.
ENV LD_LIBRARY_PATH=/opt/conda/lib:/opt/conda/lib/python3.10/site-packages/torch/lib:${LD_LIBRARY_PATH}

COPY src ./src

# Model di-mount dari ./engine/models, video uji dari ./engine/videos.
CMD ["python", "-m", "src.main"]
