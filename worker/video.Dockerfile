FROM virtual-tryon-worker:local
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir einops==0.8.1 sentencepiece==0.2.0 timm==1.0.15
COPY vendor/CatV2TON /opt/CatV2TON
COPY backend /app/backend
COPY worker /app/worker
COPY scripts /app/scripts
ENV CATV2TON_SOURCE=/opt/CatV2TON MODEL_NAME=catv2ton WORKER_KIND=video
CMD ["python", "-m", "worker.worker"]
