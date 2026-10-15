#!/usr/bin/env bash
# BetterBench single-stream decode on /home/orca/FullDrafter (build 51248ae) with the harness-proven memory settings
# (GPU_HEADROOM_MIB=384, VRAM_KV_MIB=1400). The first run with the start_engine.sh defaults (headroom 96 MiB) hit
# HSA_STATUS_ERROR_MEMORY_APERTURE_VIOLATION after the prose category.
set -uo pipefail
FD=/home/orca/FullDrafter
cd "$FD"
export HIP_VISIBLE_DEVICES=0,1 NUM_SPECULATIVE_TOKENS=12 ROCM_PATH=/opt/rocm
export GPU_HEADROOM_MIB=384 VRAM_KV_MIB=1400
export RADIANCE_FULLDRAFTER=1 RADIANCE_TEACHER_TAPS=0 RADIANCE_GDN_ANCHOR=1
export RADIANCE_FULLDRAFTER_SIDECAR=/home/orca/drafter_data/checkpoints/flash_next_k12_alodlm_v2/drafter_final.safetensors
export RADIANCE_TEACHER_MATRICES=/home/orca/drafter_data/teacher/teacher-matrices.safetensors
if ls /sys/class/kfd/kfd/proc | grep -q .; then echo "GPU busy, abort"; exit 3; fi
for c in /sys/class/drm/card*/device/hwmon/hwmon*/power1_cap; do echo "power cap $c: $(( $(cat $c) / 1000000 )) W"; done
cleanup() {
    local rc=$?
    bash "$FD/scripts/engine_manager.sh" stop; local src=$?
    echo "stop rc=$src"
    if [ "$src" -ne 0 ] && [ "$rc" -eq 0 ]; then rc=$src; fi
    exit "$rc"
}
trap cleanup EXIT
bash "$FD/scripts/engine_manager.sh" start --build-dir "$FD/build_hip" --port 8002 --timeout 900 || { echo "start failed rc=$?"; exit 2; }
mkdir -p "$FD/reports"
OUT="$FD/reports/betterbench_2x4_project_51248ae_hr384_$(date +%Y%m%d_%H%M%S).json"
cd /home/orca/BetterBench
python3 -c "import betterbench.cli as c; c.main()" run --no-update-check --endpoint http://127.0.0.1:8002/v1 --model qwen4exp --decode --passes 1 --warmup 1 --no-html --name fulldrafter_project_51248ae_hr384 --note build=51248ae --note drafter=drafter_final --note headroom_mib=384 --out "$OUT"
rc=$?; echo "betterbench rc=$rc out=$OUT"; exit $rc
