#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
nvidia-smi
python3 --version
docker --version
docker compose version
docker compose config --quiet
docker compose build worker-gpu0
docker compose run --rm --no-deps worker-gpu0 python -c 'import torch, torchvision; print(torch.__version__, torch.version.cuda, torch.cuda.get_arch_list()); print(torch.cuda.get_device_name(0), torch.cuda.get_device_capability(0)); value=torch.randn(256,256,device="cuda"); print((value@value).mean().item()); torchvision.ops.nms(torch.tensor([[0,0,4,4]],device="cuda",dtype=torch.float32),torch.ones(1,device="cuda"),0.5); torch.cuda.synchronize()'
