#!/usr/bin/env bash
# Train every persona adapter, one after another, in the training venv.
# The GPU must be free — stop wsl/serve-model.sh first.
#   wsl -d Ubuntu-24.04 bash wsl/train-all.sh
set -uo pipefail
cd "$(dirname "$0")/.."

for config in training/configs/persona_*.yaml; do
  echo "=== ${config} ==="
  bash wsl/train-lora.sh "${config}" || echo "FAILED ${config}"
done
echo ALL_TRAINING_DONE
