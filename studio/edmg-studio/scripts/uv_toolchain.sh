#!/usr/bin/env bash

# Shared uv bootstrap for source, cloud, and sidecar setup scripts.
# Release packaging has its own stricter JavaScript entry point, but uses the
# same pinned uv release.

EDMG_UV_VERSION="0.11.28"

edmg_uv_archive() {
  local platform
  local machine
  platform="$(uname -s)"
  machine="$(uname -m)"
  case "${platform}:${machine}" in
    Linux:x86_64|Linux:amd64)
      printf '%s\t%s\n' \
        "uv-x86_64-unknown-linux-gnu.tar.gz" \
        "e490a6464492183c5d4534a5527fb4440f7f2bb2f228162ad7e4afe076dc0224"
      ;;
    Linux:aarch64|Linux:arm64)
      printf '%s\t%s\n' \
        "uv-aarch64-unknown-linux-gnu.tar.gz" \
        "03e9fe0a81b0718d0bc84625de3885df6cc3f89a8b6af6121d6b9f6113fb6533"
      ;;
    Darwin:x86_64|Darwin:amd64)
      printf '%s\t%s\n' \
        "uv-x86_64-apple-darwin.tar.gz" \
        "2ad79983127ffca7d77b77ce6a24278d7e4f7b817a1acf72fea5f8124b4aac5e"
      ;;
    Darwin:arm64|Darwin:aarch64)
      printf '%s\t%s\n' \
        "uv-aarch64-apple-darwin.tar.gz" \
        "33540eb7c883ab857eff79bd5ac2aa31fe27b595abecb4a9c003a2c998447232"
      ;;
    *)
      echo "No checksum-pinned uv ${EDMG_UV_VERSION} archive is configured for ${platform} ${machine}." >&2
      return 1
      ;;
  esac
}

edmg_sha256() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${path}" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${path}" | awk '{print $1}'
  elif command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 "${path}" | awk '{print $NF}'
  else
    echo "A SHA-256 utility (sha256sum, shasum, or openssl) is required to install uv." >&2
    return 1
  fi
}

edmg_install_uv_archive() {
  local install_dir="$1"
  local archive_name
  local expected_sha256
  local actual_sha256
  local temp_dir
  local archive_path
  local extract_dir
  local matches
  local source_uv

  IFS=$'\t' read -r archive_name expected_sha256 < <(edmg_uv_archive)
  [[ -n "${archive_name}" && -n "${expected_sha256}" ]] || return 1
  command -v curl >/dev/null 2>&1 || {
    echo "curl is required to install uv ${EDMG_UV_VERSION}." >&2
    return 1
  }
  command -v tar >/dev/null 2>&1 || {
    echo "tar is required to install uv ${EDMG_UV_VERSION}." >&2
    return 1
  }

  temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/edmg-uv.XXXXXX")"
  archive_path="${temp_dir}/${archive_name}"
  extract_dir="${temp_dir}/extract"
  mkdir -p "${extract_dir}" "${install_dir}"

  echo "[uv] downloading checksum-pinned uv ${EDMG_UV_VERSION} (${archive_name})" >&2
  if ! curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fL --retry 3 \
    "https://github.com/astral-sh/uv/releases/download/${EDMG_UV_VERSION}/${archive_name}" \
    -o "${archive_path}"; then
    rm -rf "${temp_dir}"
    return 1
  fi

  actual_sha256="$(edmg_sha256 "${archive_path}")"
  if [[ "${actual_sha256}" != "${expected_sha256}" ]]; then
    echo "uv archive checksum mismatch: expected ${expected_sha256}, got ${actual_sha256:-unavailable}." >&2
    rm -rf "${temp_dir}"
    return 1
  fi

  tar -xzf "${archive_path}" -C "${extract_dir}"
  matches="$(find "${extract_dir}" -type f -name uv -print)"
  if [[ -z "${matches}" || "$(printf '%s\n' "${matches}" | awk 'NF { count += 1 } END { print count + 0 }')" != "1" ]]; then
    echo "Pinned uv archive did not contain exactly one uv executable." >&2
    rm -rf "${temp_dir}"
    return 1
  fi
  source_uv="${matches}"
  cp "${source_uv}" "${install_dir}/uv"
  chmod 0755 "${install_dir}/uv"
  rm -rf "${temp_dir}"
}

edmg_require_uv() {
  local candidate="${EDMG_UV_BIN:-}"
  local install_dir="${EDMG_UV_INSTALL_DIR:-${HOME}/.local/bin}"

  if [[ -z "${candidate}" ]] && command -v uv >/dev/null 2>&1; then
    candidate="$(command -v uv)"
  fi

  if [[ -z "${candidate}" || ! -x "${candidate}" ]]; then
    echo "[uv] installing pinned uv ${EDMG_UV_VERSION} into ${install_dir}" >&2
    edmg_install_uv_archive "${install_dir}"
    candidate="${install_dir}/uv"
  fi

  local actual
  actual="$("${candidate}" --version 2>/dev/null || true)"
  if [[ "${actual}" != "uv ${EDMG_UV_VERSION}" && "${actual}" != "uv ${EDMG_UV_VERSION} "* ]]; then
    echo "Expected uv ${EDMG_UV_VERSION}, found ${actual:-unusable uv at ${candidate}}." >&2
    echo "Set EDMG_UV_BIN to the pinned uv executable or remove the mismatched executable." >&2
    return 1
  fi

  printf '%s\n' "${candidate}"
}

edmg_assert_uv_python_312() {
  local uv_bin="$1"
  local project_dir="$2"
  shift 2
  "${uv_bin}" run --project "${project_dir}" --frozen "$@" python -c \
    'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else f"EDMG Studio requires Python 3.12, got {sys.version.split()[0]}")'
}
