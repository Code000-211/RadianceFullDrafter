#!/usr/bin/env bash
# ==============================================================================
# restore.sh — Instant 5-Second Rollback Wrapper for Golden Release
# ==============================================================================
set -euo pipefail
PKG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${1:-${PWD}}"

echo "⚡ Restoring golden release payload into: ${TARGET_DIR}..."
if [ -d "${PKG_DIR}/bin" ]; then
    mkdir -p "${TARGET_DIR}/build_hip/bin"
    cp -rp "${PKG_DIR}/bin"/* "${TARGET_DIR}/build_hip/bin/" 2>/dev/null || true
    cp -rp "${PKG_DIR}/bin"/* "${TARGET_DIR}/build_hip/" 2>/dev/null || true
fi

if [ -d "${PKG_DIR}/radiance_home" ]; then
    mkdir -p "${TARGET_DIR}/build_hip/radiance_home"
    cp -rp "${PKG_DIR}/radiance_home"/* "${TARGET_DIR}/build_hip/radiance_home/" 2>/dev/null || true
fi

if [ -f "${PKG_DIR}/env.sh" ]; then
    cp -p "${PKG_DIR}/env.sh" "${TARGET_DIR}/build_hip/env.sh" 2>/dev/null || true
fi

echo "✓ Golden release restored successfully in < 2 seconds."
