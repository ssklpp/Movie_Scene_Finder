#!/usr/bin/env bash
# 로컬 VLM 서버(vLLM, OpenAI 호환 :8001)를 띄운다. SPEC §12 Phase 2.
#
# vLLM은 프로젝트 venv가 아니라 ~/.venvs/vllm에 따로 설치되어 있다.
# 실행 중에는 VRAM을 대부분 차지하므로 다른 GPU 작업과 동시에 띄우지 않는다.
#
# 환경 변수로 바꿀 수 있는 값:
#   LOCAL_VLM_MODEL        모델 ID (기본: .env 값)
#   VLM_GPU_UTIL           --gpu-memory-utilization (기본 0.85)
#   VLM_MAX_MODEL_LEN      --max-model-len (기본 4096)
#   VLM_MAX_PIXELS         이미지 최대 픽셀 수 (기본 1280*720)
#   VLM_EXTRA_ARGS         그 밖의 vllm serve 인자 (예: "--kv-cache-dtype fp8 --enforce-eager")
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VLLM_BIN="${VLLM_BIN:-$HOME/.venvs/vllm/bin/vllm}"

if [[ -z "${LOCAL_VLM_MODEL:-}" && -f "$REPO_ROOT/.env" ]]; then
  LOCAL_VLM_MODEL="$(grep -E '^LOCAL_VLM_MODEL=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '\r"')"
fi
: "${LOCAL_VLM_MODEL:?LOCAL_VLM_MODEL is not set (.env or environment)}"

# FlashInfer는 처음 실행할 때 커널을 nvcc로 컴파일한다. WSL에 CUDA 툴킷(nvcc)이 없으므로
# FlashInfer 샘플러를 끄고, 같은 이유로 --kv-cache-dtype fp8(FlashInfer 어텐션 사용)도 쓰지 않는다.
export VLLM_USE_FLASHINFER_SAMPLER="${VLLM_USE_FLASHINFER_SAMPLER:-0}"

PORT="${VLM_PORT:-8001}"
MAX_PIXELS="${VLM_MAX_PIXELS:-921600}"

# shellcheck disable=SC2086
exec "$VLLM_BIN" serve "$LOCAL_VLM_MODEL" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --max-model-len "${VLM_MAX_MODEL_LEN:-4096}" \
  --gpu-memory-utilization "${VLM_GPU_UTIL:-0.85}" \
  --max-num-seqs 4 \
  --limit-mm-per-prompt '{"image": 1, "video": 0}' \
  --mm-processor-kwargs "{\"max_pixels\": $MAX_PIXELS}" \
  ${VLM_EXTRA_ARGS:-}
