FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HF_HOME=/models/huggingface OMP_NUM_THREADS=4
RUN apt-get update && apt-get install -y --no-install-recommends git libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/backend/requirements.txt
COPY worker/requirements.txt /app/worker/requirements.txt
RUN pip install --no-cache-dir torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128 && pip install --no-cache-dir -r worker/requirements.txt
COPY vendor/CatVTON /opt/CatVTON
COPY scripts/patch-upstream.py /app/scripts/patch-upstream.py
RUN python scripts/patch-upstream.py /opt/CatVTON
COPY backend /app/backend
COPY worker /app/worker
COPY scripts /app/scripts
CMD ["python", "-m", "worker.worker"]
