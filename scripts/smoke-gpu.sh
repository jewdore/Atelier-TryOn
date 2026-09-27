#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose run --rm model-init
docker compose run --rm --no-deps worker-gpu0 python -m worker.inference \
  --person /opt/CatVTON/resource/demo/example/person/men/model_5.png \
  --garment /garments/tops/black_graphic_tee.jpg --output /data/smoke-result.png
