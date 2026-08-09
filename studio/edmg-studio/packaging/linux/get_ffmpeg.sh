#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
studio_dir="$(cd -- "${script_dir}/../.." && pwd)"
out_dir="${1:-${studio_dir}/electron-resources/bin}"

if [[ "${out_dir}" != /* ]]; then
  out_dir="${studio_dir}/${out_dir}"
fi

command -v node >/dev/null 2>&1 || {
  echo "Node.js is required to stage pinned FFmpeg and FFprobe." >&2
  exit 1
}

node "${studio_dir}/scripts/stage-media-tools.mjs" --out-dir "${out_dir}"
[[ -x "${out_dir}/ffmpeg" ]] || { echo "Missing staged FFmpeg: ${out_dir}/ffmpeg" >&2; exit 1; }
[[ -x "${out_dir}/ffprobe" ]] || { echo "Missing staged FFprobe: ${out_dir}/ffprobe" >&2; exit 1; }

echo "OK: staged checksum-verified FFmpeg and FFprobe into ${out_dir}"
