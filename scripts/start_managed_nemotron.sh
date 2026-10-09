#!/usr/bin/env bash
# Isolated optional Director server; existing Studio CUDA environment is untouched.
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
model_root=${EDMG_NEMOTRON_MODEL_PATH:-"$repo_root/models/director-nvidia/nemotron3-nano-omni"}
gpu_devices=${EDMG_NEMOTRON_GPU_DEVICES:-1,2}
server_port=${EDMG_NEMOTRON_PORT:-8001}
image=vllm/vllm-openai:v0.20.0
name=edmg-nemotron-director
[[ "$gpu_devices" =~ ^[0-9]+,[0-9]+$ ]] || { echo 'Exactly two GPU ordinals are required.' >&2; exit 2; }
IFS=, read -r first_gpu second_gpu <<< "$gpu_devices"
[[ "$first_gpu" != "$second_gpu" ]] || { echo 'GPU ordinals must be distinct.' >&2; exit 2; }
for gpu in "$first_gpu" "$second_gpu"; do
  free_mib=$(nvidia-smi -i "$gpu" --query-gpu=memory.free --format=csv,noheader,nounits)
  ((free_mib >= 40000)) || { echo "GPU $gpu has insufficient free memory; existing workloads were not changed." >&2; exit 2; }
done
[[ "$server_port" =~ ^[0-9]+$ ]] && ((server_port >= 1024 && server_port <= 65535)) || exit 2
python_path="$repo_root/studio/edmg-studio/python_backend/.venv/bin/python"
"$python_path" "$repo_root/scripts/qualify_director_models.py" "$model_root" \
  --receipt "$repo_root/logs/qualification/nemotron-prelaunch.json"
docker_command=(docker)
if ! docker info >/dev/null 2>&1; then docker_command=(sudo -n docker); fi
if "${docker_command[@]}" container inspect "$name" >/dev/null 2>&1; then
  echo "Container $name already exists; inspect its status instead of replacing it." >&2
  exit 3
fi
"${docker_command[@]}" image inspect "$image" >/dev/null
"${docker_command[@]}" run -d --name "$name" \
  --gpus "\"device=$gpu_devices\"" --shm-size 8g \
  -p "127.0.0.1:$server_port:8000" \
  -v "$model_root:/model:ro" \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  "$image" --model /model \
  --served-model-name nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-BF16 \
  --tensor-parallel-size 2 --dtype bfloat16 --max-model-len 8192 \
  --max-num-seqs 1 --gpu-memory-utilization 0.80 --enforce-eager \
  --trust-remote-code --reasoning-parser nemotron_v3
echo "Startup requested on localhost:$server_port; readiness and inference must be qualified separately."
