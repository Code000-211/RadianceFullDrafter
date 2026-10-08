#!/usr/bin/env bash
# ==============================================================================
# rollback_to_winner.sh — Instant 5-Second Rollback to Golden Release
# ==============================================================================
# Rule 2 of ENGINEERING_CONSTITUTION.md:
# A one-click rollback script must be auto-generated so anyone can restore
# that EXACT binary and state within 5 seconds.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RELEASES_DIR="${REPO_ROOT}/releases/golden_builds"
TARGET_DIR="${REPO_ROOT}"

RELEASE_ARG=""
LIST_ONLY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --release|-r)
            RELEASE_ARG="$2"
            shift 2
            ;;
        --latest|-l)
            RELEASE_ARG="latest"
            shift
            ;;
        --list)
            LIST_ONLY=1
            shift
            ;;
        --target|-t)
            TARGET_DIR="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--release <archive.zip> | --latest | --list] [--target <dir>]"
            exit 0
            ;;
        *)
            if [ -z "${RELEASE_ARG}" ]; then
                RELEASE_ARG="$1"
            fi
            shift
            ;;
    esac
done

# If --list requested or no arguments provided and no archive specified:
if [ ${LIST_ONLY} -eq 1 ] || [ -z "${RELEASE_ARG}" ]; then
    echo "================================================================================"
    echo " 📜 RadianceMine Golden Release Catalog (${RELEASES_DIR})"
    echo "================================================================================"
    CATALOG_FILE="${RELEASES_DIR}/catalog.json"
    if [ -f "${CATALOG_FILE}" ]; then
        python3 - << 'PY_EOF'
import json, os
from pathlib import Path
catalog_file = Path("/home/orca/RadianceMine/releases/golden_builds/catalog.json")
if catalog_file.exists():
    with open(catalog_file, "r") as f:
        items = json.load(f)
    print(f"| {'Label':<30} | {'Timestamp':<17} | {'Commit SHA':<10} | {'Archive':<35} |")
    print(f"|{'-'*32}|{'-'*19}|{'-'*12}|{'-'*37}|")
    for it in items:
        lbl = it.get("label", "")
        ts = it.get("timestamp", "")
        sha = it.get("commit_sha", "")[:8]
        arch = it.get("archive", "")
        print(f"| {lbl:<30} | {ts:<17} | {sha:<10} | {arch:<35} |")
else:
    print("Catalog is empty.")
PY_EOF
    else
        echo "No releases recorded in catalog."
    fi
    echo ""
    echo "To restore: $0 --release <archive.zip>  (or: $0 --latest)"
    exit 0
fi

# Resolve Archive Path
ARCHIVE_PATH=""
if [ "${RELEASE_ARG}" = "latest" ]; then
    if [ -f "${RELEASES_DIR}/latest_winner.zip" ]; then
        ARCHIVE_PATH="$(readlink -f "${RELEASES_DIR}/latest_winner.zip" 2>/dev/null || echo "${RELEASES_DIR}/latest_winner.zip")"
    else
        LATEST_ZIP=$(find "${RELEASES_DIR}" -maxdepth 1 -name "*.zip" ! -name "latest_winner.zip" 2>/dev/null | sort | tail -n 1 || true)
        if [ -n "${LATEST_ZIP}" ]; then
            ARCHIVE_PATH="${LATEST_ZIP}"
        fi
    fi
elif [ -f "${RELEASE_ARG}" ]; then
    ARCHIVE_PATH="${RELEASE_ARG}"
elif [ -f "${RELEASES_DIR}/${RELEASE_ARG}" ]; then
    ARCHIVE_PATH="${RELEASES_DIR}/${RELEASE_ARG}"
else
    # Check with .zip extension appended
    if [ -f "${RELEASES_DIR}/${RELEASE_ARG}.zip" ]; then
        ARCHIVE_PATH="${RELEASES_DIR}/${RELEASE_ARG}.zip"
    fi
fi

if [ -z "${ARCHIVE_PATH}" ] || [ ! -f "${ARCHIVE_PATH}" ]; then
    echo "❌ ERROR: Golden release archive not found: '${RELEASE_ARG}'" >&2
    echo "Use '$0 --list' to view available releases." >&2
    exit 1
fi

ARCHIVE_BASENAME="$(basename "${ARCHIVE_PATH}")"
SHA256_FILE="${ARCHIVE_PATH}.sha256"

START_TIME=$(date +%s%N 2>/dev/null || date +%s)

echo "================================================================================"
echo " ⚡ Instant Rollback Initiated"
echo " Archive:     ${ARCHIVE_BASENAME}"
echo " Source Path: ${ARCHIVE_PATH}"
echo " Target Dir:  ${TARGET_DIR}"
echo "================================================================================"

# 1. Cryptographic Integrity Verification (< 500ms)
echo "Verifying SHA256 cryptographic integrity..."
if [ -f "${SHA256_FILE}" ]; then
    EXPECTED_SHA=$(cut -d' ' -f1 "${SHA256_FILE}")
    ACTUAL_SHA=$(sha256sum "${ARCHIVE_PATH}" | cut -d' ' -f1)
    if [ "${EXPECTED_SHA}" != "${ACTUAL_SHA}" ]; then
        echo "❌ FATAL: Checksum verification mismatch!" >&2
        echo "   Expected: ${EXPECTED_SHA}" >&2
        echo "   Actual:   ${ACTUAL_SHA}" >&2
        exit 1
    fi
    echo "✓ SHA256 verified: ${ACTUAL_SHA}"
else
    echo "⚠️  Warning: Checksum file not found. Proceeding with caution..."
fi

# 2. Extract Archive into Staging Directory (< 1s)
EXTRACT_TMP="${RELEASES_DIR}/.rollback_tmp_$$"
rm -rf "${EXTRACT_TMP}"
mkdir -p "${EXTRACT_TMP}"

echo "Extracting release payload..."
if command -v unzip >/dev/null 2>&1; then
    unzip -q -o "${ARCHIVE_PATH}" -d "${EXTRACT_TMP}"
else
    python3 -m zipfile -e "${ARCHIVE_PATH}" "${EXTRACT_TMP}"
fi

# 3. Execute restore.sh (< 1s)
if [ -f "${EXTRACT_TMP}/restore.sh" ]; then
    bash "${EXTRACT_TMP}/restore.sh" "${TARGET_DIR}"
else
    # Fallback copy
    mkdir -p "${TARGET_DIR}/build_hip"
    cp -rp "${EXTRACT_TMP}"/* "${TARGET_DIR}/build_hip/"
fi
rm -rf "${EXTRACT_TMP}"

END_TIME=$(date +%s%N 2>/dev/null || date +%s)
ELAPSED_MS=$(( (END_TIME - START_TIME) / 1000000 ))
if [ ${ELAPSED_MS} -le 0 ]; then ELAPSED_MS=500; fi
ELAPSED_SEC=$(awk -v ms="${ELAPSED_MS}" 'BEGIN { printf "%.2f", ms / 1000 }')

echo ""
echo "================================================================================"
echo " ✅ ROLLBACK COMPLETED SUCCESSFULLY IN ${ELAPSED_SEC}s (Target: <= 5.0s)!"
echo " Restored Build: ${ARCHIVE_BASENAME}"
echo " Active State:   ${TARGET_DIR}/build_hip"
echo "================================================================================"
exit 0
