#!/usr/bin/env bash
# ==============================================================================
# measure_hardware.sh — re-measures the numbers in HARDWARE_GROUND_TRUTH.md
# ==============================================================================
# Builds scripts/hwprobe/p2pbw.cpp and runs it three times. Works next to a running
# engine (uses 256 MiB per GPU), but an idle engine gives the cleanest numbers.
# ==============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${TMPDIR:-/tmp}/radiance_p2pbw"
/opt/rocm/bin/hipcc -O2 --offload-arch=gfx1201 "${HERE}/hwprobe/p2pbw.cpp" -o "${OUT}"
for i in 1 2 3; do
    echo "--- run ${i}"
    "${OUT}"
done
echo "--- memory clock levels"
grep -H . /sys/class/drm/card*/device/pp_dpm_mclk
