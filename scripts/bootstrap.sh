#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
task_cache_dir="${UV_CACHE_DIR:-/tmp/space-stds-uv-cache}"

cd "$project_root"
UV_CACHE_DIR="$task_cache_dir" uv sync --frozen
UV_CACHE_DIR="$task_cache_dir" uv run space-stds init

if [[ -n "${SPACE_STDS_MANIFEST:-}" ]]; then
  UV_CACHE_DIR="$task_cache_dir" uv run space-stds ingest-manifest "$SPACE_STDS_MANIFEST"
fi

echo "space-stds is ready. Copy authorised PDFs into the printed corpus directory."

