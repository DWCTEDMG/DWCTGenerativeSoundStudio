#!/usr/bin/env bash
set -euo pipefail

# Linux/Lightning S3 model-cache setup for EDMG Studio.
#
# Credentials are intentionally not stored by this script. Use normal AWS
# sources: instance role, AWS_PROFILE, AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY,
# AWS_SESSION_TOKEN, or the provider's S3-compatible environment.

EDMG_STUDIO_HOME="${EDMG_STUDIO_HOME:-${HOME}/edmg-studio-home}"
S3_PYTHON_BIN="${S3_PYTHON_BIN:-python}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=uv_toolchain.sh
source "${SCRIPT_DIR}/uv_toolchain.sh"
UV_BIN="$(edmg_require_uv)"
EDMG_AWS_MODEL_CACHE_BUCKET="${EDMG_AWS_MODEL_CACHE_BUCKET:-${EDMG_AWS_MODEL_BUCKET:-${EDMG_S3_MODEL_CACHE_BUCKET:-}}}"
EDMG_AWS_MODEL_CACHE_PREFIX="${EDMG_AWS_MODEL_CACHE_PREFIX:-${EDMG_S3_MODEL_CACHE_PREFIX:-models}}"
EDMG_MODEL_STORAGE_MODE="${EDMG_MODEL_STORAGE_MODE:-local_cache}" # local_cache|cloud_only
EDMG_AWS_MODEL_CACHE_STORAGE_CLASS="${EDMG_AWS_MODEL_CACHE_STORAGE_CLASS:-${EDMG_S3_MODEL_CACHE_STORAGE_CLASS:-STANDARD}}"
AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
EDMG_S3_ENDPOINT_URL="${EDMG_S3_ENDPOINT_URL:-${AWS_ENDPOINT_URL:-}}"
S3_CREATE_BUCKET="${S3_CREATE_BUCKET:-0}"
S3_VALIDATE_WRITE="${S3_VALIDATE_WRITE:-1}"
S3_INSTALL_BOTO3="${S3_INSTALL_BOTO3:-1}"
S3_ENV_FILE="${S3_ENV_FILE:-${EDMG_STUDIO_HOME}/s3-model-cache.env}"

export EDMG_STUDIO_HOME
export EDMG_AWS_MODEL_CACHE=1
export EDMG_AWS_MODEL_CACHE_BUCKET
export EDMG_AWS_MODEL_CACHE_PREFIX
export EDMG_MODEL_STORAGE_MODE
export EDMG_AWS_MODEL_CACHE_STORAGE_CLASS
export AWS_REGION
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-${AWS_REGION}}"
export EDMG_S3_ENDPOINT_URL

log() {
  echo "[s3-model-cache] $*"
}

fail() {
  echo "[s3-model-cache][error] $*" >&2
  exit 1
}

if [[ -z "${EDMG_AWS_MODEL_CACHE_BUCKET}" ]]; then
  fail "Set EDMG_AWS_MODEL_CACHE_BUCKET to your S3 bucket name."
fi

case "${EDMG_MODEL_STORAGE_MODE}" in
  local_cache|cloud_only) ;;
  s3_only|remote_only)
    EDMG_MODEL_STORAGE_MODE="cloud_only"
    export EDMG_MODEL_STORAGE_MODE
    ;;
  *)
    fail "Unsupported EDMG_MODEL_STORAGE_MODE=${EDMG_MODEL_STORAGE_MODE}. Use local_cache or cloud_only."
    ;;
esac

mkdir -p "${EDMG_STUDIO_HOME}"

if [[ "${S3_INSTALL_BOTO3}" == "1" ]]; then
  log "Ensuring boto3 is installed"
  "${UV_BIN}" pip install --python "${S3_PYTHON_BIN}" -U boto3
fi

log "Validating S3 model cache"
"${S3_PYTHON_BIN}" - <<'PY'
from __future__ import annotations

import os
import uuid

import boto3
from botocore.exceptions import ClientError

bucket = os.environ["EDMG_AWS_MODEL_CACHE_BUCKET"]
prefix = os.environ.get("EDMG_AWS_MODEL_CACHE_PREFIX", "models").strip("/")
region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
endpoint_url = os.environ.get("EDMG_S3_ENDPOINT_URL") or None
create_bucket = os.environ.get("S3_CREATE_BUCKET", "0").lower() in {"1", "true", "yes", "on"}
validate_write = os.environ.get("S3_VALIDATE_WRITE", "1").lower() in {"1", "true", "yes", "on"}

session = boto3.session.Session(region_name=region)
sts = session.client("sts", endpoint_url=endpoint_url)
s3 = session.client("s3", endpoint_url=endpoint_url)

ident = sts.get_caller_identity()
print(f"account={ident.get('Account')}")
print(f"region={region}")
print(f"bucket={bucket}")
print(f"prefix={prefix}")
if endpoint_url:
    print(f"endpoint_url={endpoint_url}")

try:
    s3.head_bucket(Bucket=bucket)
except ClientError as exc:
    code = str((exc.response or {}).get("Error", {}).get("Code") or "")
    if not create_bucket:
        raise SystemExit(
            f"Bucket check failed ({code}). Create the bucket or rerun with S3_CREATE_BUCKET=1 if your credentials allow it."
        )
    kwargs = {"Bucket": bucket}
    if region != "us-east-1" and not endpoint_url:
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
    s3.create_bucket(**kwargs)
    print("bucket_created=true")

if validate_write:
    key = "/".join(part for part in (prefix, ".edmg-cache-check", f"{uuid.uuid4().hex}.txt") if part)
    body = b"edmg-s3-model-cache-check\n"
    s3.put_object(Bucket=bucket, Key=key, Body=body)
    got = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    if got != body:
        raise SystemExit("S3 write/read probe failed: body mismatch")
    s3.delete_object(Bucket=bucket, Key=key)
    print(f"write_probe=ok key={key}")
else:
    print("write_probe=skipped")
PY

cat >"${S3_ENV_FILE}" <<EOF
export EDMG_AWS_MODEL_CACHE=1
export EDMG_AWS_MODEL_CACHE_BUCKET=${EDMG_AWS_MODEL_CACHE_BUCKET}
export EDMG_AWS_MODEL_CACHE_PREFIX=${EDMG_AWS_MODEL_CACHE_PREFIX}
export EDMG_MODEL_STORAGE_MODE=${EDMG_MODEL_STORAGE_MODE}
export EDMG_AWS_MODEL_CACHE_STORAGE_CLASS=${EDMG_AWS_MODEL_CACHE_STORAGE_CLASS}
export AWS_REGION=${AWS_REGION}
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}
EOF

if [[ -n "${EDMG_S3_ENDPOINT_URL}" ]]; then
  cat >>"${S3_ENV_FILE}" <<EOF
export EDMG_S3_ENDPOINT_URL=${EDMG_S3_ENDPOINT_URL}
EOF
fi

chmod 600 "${S3_ENV_FILE}" || true

log "Done"
log "Env file: ${S3_ENV_FILE}"
log "Storage mode: ${EDMG_MODEL_STORAGE_MODE}"
log "Restart backend with:"
echo "  source \"${S3_ENV_FILE}\""
echo "  EDMG_BACKEND_ENV_MODE=active EDMG_SKIP_BOOTSTRAP=1 bash scripts/start_lightning_backend.sh"
