#!/usr/bin/env bash
set -euo pipefail
curl --fail --silent --show-error "${TRYON_URL:-http://localhost:3000}/api/health" | python3 -m json.tool
nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total --format=csv
