# Model source snapshots

`CatVTON/` is a source snapshot of the official Zheng-Chong/CatVTON repository at commit `7818397f25613beedb3d861a34769f607cfcf3b1`. The upstream LICENSE is retained. It is bundled to avoid depending on GitHub access at Docker build time. `scripts/patch-upstream.py` applies explicit, checked loader adaptations inside the image only. Finder `.DS_Store` metadata is excluded from publication.

`CatV2TON/` comes from the official Zheng-Chong/CatV2TON repository at commit `d8abdab93c9e3ffc89f6f9e13dbbee6b88e85cfc`. Its example utility's author-specific local dataset path is replaced by `VITONHD_IMAGE_DIR`, defaulting to `./datasets/VITONHD-1024/test/Images`. Upstream attribution and license notices are retained.
