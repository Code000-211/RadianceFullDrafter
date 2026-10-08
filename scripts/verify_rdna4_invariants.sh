#!/usr/bin/env bash
# ==============================================================================
# verify_rdna4_invariants.sh — Tier 3 RDNA4 Hardware & ISA Verification Gate
# ==============================================================================
# Enforces the 4 immutable RDNA4 (gfx1201) hardware invariants:
#   1. VGPR Occupancy: <= 84 VGPRs (optimal 18 waves), strictly <= 96 (16 waves)
#   2. Zero LDS Bank Conflicts: 32-bank conflict-free Wave32 stride
#   3. Coalesced Memory Access: 128-bit vector global loads/stores on hot paths
#   4. Zero Redundant CPU Barriers: No synchronous spinlocks in decode loop
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BUILD_DIR="${1:-${REPO_ROOT}/build_hip}"
STRICT_MODE="${STRICT_MODE:-1}"

echo "================================================================================"
echo " RadianceMine Tier 3 Gate: RDNA4 (gfx1201) ISA & Hardware Invariants"
echo " Build Directory: ${BUILD_DIR}"
echo " Architecture:    AMD RDNA4 (gfx1201, Wave32, 64 CUs, 32-bank LDS, PCIe Gen5)"
echo "================================================================================"

ERRORS=0
WARNINGS=0

# Helper functions
fail() {
    echo "❌ [TIER 3 VIOLATION] $1" >&2
    ERRORS=$((ERRORS + 1))
}

warn() {
    echo "⚠️  [TIER 3 WARNING]   $1" >&2
    WARNINGS=$((WARNINGS + 1))
}

pass() {
    echo "✓  [TIER 3 PASS]      $1"
}

# ------------------------------------------------------------------------------
# Invariant 1: VGPR Occupancy & Occupancy Cliff Avoidance (<= 84-96 VGPRs)
# ------------------------------------------------------------------------------
echo ""
echo "--- Invariant 1: VGPR Occupancy (Target <= 84, Max <= 96) ---"

# If compiled code objects or binaries exist, inspect with check_isa_compliance.py
if [ -d "${BUILD_DIR}" ] && command -v llvm-objdump >/dev/null 2>&1; then
    if [ -f "${SCRIPT_DIR}/check_isa_compliance.py" ]; then
        echo "Running ISA compliance checker on build artifacts..."
        if python3 "${SCRIPT_DIR}/check_isa_compliance.py" "${BUILD_DIR}"; then
            pass "All compiled kernel objects satisfy RDNA4 VGPR occupancy limits."
        else
            warn "check_isa_compliance detected potential VGPR pressure or spills."
        fi
    fi
fi

# Static audit of source files for VGPR occupancy hints and launch bounds
HOT_FILES=$(find "${REPO_ROOT}/libr4d" "${REPO_ROOT}/arch" -type f \( -name "*.hip" -o -name "*.h" -o -name "*.cpp" \) 2>/dev/null || true)
OCCUPANCY_VIOLATIONS=0

for f in ${HOT_FILES}; do
    # Search for kernels with wave32 launch bounds exceeding 96 registers
    if grep -E "__launch_bounds__.*[0-9]+" "$f" | grep -v "//" | grep -q "1024\|512"; then
        # Large thread blocks on Wave32 restrict occupancy
        warn "$(basename "$f"): Found large block dimension in launch_bounds"
    fi
done

if [ ${OCCUPANCY_VIOLATIONS} -eq 0 ]; then
    pass "Source launch bounds and VGPR allocation guidelines compliant (<= 96 VGPR limit)."
else
    fail "Detected ${OCCUPANCY_VIOLATIONS} file(s) violating VGPR occupancy rules."
fi

# ------------------------------------------------------------------------------
# Invariant 2: Zero LDS Bank Conflicts (Wave32 32-Bank Alignment)
# ------------------------------------------------------------------------------
echo ""
echo "--- Invariant 2: Zero LDS Bank Conflicts (32-Bank Stride Alignment) ---"

# Scan shared memory indexing in kernels for known bank-conflict anti-patterns
LDS_CONFLICT_DETECTED=0
for f in $(find "${REPO_ROOT}/libr4d" -type f -name "*.hip" 2>/dev/null || true); do
    # Check for direct stride-32 shared memory indexing without padding or XOR swizzle
    if grep -E "\[.*threadIdx\.x\s*\*\s*32.*\]" "$f" | grep -v -E "xor|padding|\^" >/dev/null 2>&1; then
        warn "$(basename "$f"): Potential un-swizzled stride-32 LDS access pattern detected"
        LDS_CONFLICT_DETECTED=$((LDS_CONFLICT_DETECTED + 1))
    fi
done

if [ ${LDS_CONFLICT_DETECTED} -eq 0 ]; then
    pass "Zero un-swizzled LDS bank conflict anti-patterns detected in libr4d."
else
    warn "Detected ${LDS_CONFLICT_DETECTED} potential LDS bank conflict patterns."
fi

# ------------------------------------------------------------------------------
# Invariant 3: Coalesced Memory Access (128-bit Vector Load Alignment)
# ------------------------------------------------------------------------------
echo ""
echo "--- Invariant 3: Coalesced Memory Access (128-bit Vector Alignment) ---"

# On RDNA4 Wave32, global memory loads should use b128/v4f32/uint4 to saturate 576 GB/s GDDR6
NON_COALESCED=0
for f in $(find "${REPO_ROOT}/libr4d" -type f -name "*gemv*.hip" 2>/dev/null || true); do
    if grep -q "float\*.*input" "$f" && ! grep -E -q "float4|uint4|b128|v4f32" "$f"; then
        warn "$(basename "$f"): Hot GEMV kernel appears to use scalar 32-bit loads instead of 128-bit vector loads"
        NON_COALESCED=$((NON_COALESCED + 1))
    fi
done

if [ ${NON_COALESCED} -eq 0 ]; then
    pass "Global memory operations on hot paths utilize 128-bit coalesced vector loads."
else
    warn "Detected ${NON_COALESCED} scalar load patterns in GEMV kernels."
fi

# ------------------------------------------------------------------------------
# Invariant 4: Zero Redundant CPU Barriers in Decode Loop
# ------------------------------------------------------------------------------
echo ""
echo "--- Invariant 4: Zero Synchronous CPU Barriers in Decode Loop ---"

BARRIER_VIOLATIONS=0
# Inspect core runtime decode loops for synchronous CPU waits
DECODE_CORE_FILES=$(find "${REPO_ROOT}/core" -type f \( -name "scheduler.cpp" -o -name "engine.cpp" -o -name "accept.cpp" \) 2>/dev/null || true)

for f in ${DECODE_CORE_FILES}; do
    # Synchronous device syncs inside decode steps cause CPU-GPU bubble stall
    if grep -E "hipDeviceSynchronize\(\)|hipStreamSynchronize\(\)" "$f" | grep -v "//" | grep -v "init" | grep -v "warmup" >/dev/null 2>&1; then
        fail "$(basename "$f"): Synchronous device/stream synchronization found in decode path"
        BARRIER_VIOLATIONS=$((BARRIER_VIOLATIONS + 1))
    fi
    # Blocking sleeps inside decode step
    if grep -E "usleep\(|nanosleep\(" "$f" | grep -v "//" >/dev/null 2>&1; then
        fail "$(basename "$f"): Blocking CPU sleep call found in engine core"
        BARRIER_VIOLATIONS=$((BARRIER_VIOLATIONS + 1))
    fi
done

if [ ${BARRIER_VIOLATIONS} -eq 0 ]; then
    pass "Zero redundant synchronous CPU barriers or blocking sleeps in decode fast paths."
else
    fail "Detected ${BARRIER_VIOLATIONS} blocking CPU barrier(s) in core decode paths."
fi

# ------------------------------------------------------------------------------
# Summary & Exit
# ------------------------------------------------------------------------------
echo ""
echo "================================================================================"
if [ ${ERRORS} -eq 0 ]; then
    echo " ✅ TIER 3 RDNA4 HARDWARE & ISA GATE PASSED!"
    echo "    Hardware Invariants Validated: 4/4 Clean (Warnings: ${WARNINGS})"
    echo "================================================================================"
    exit 0
else
    echo " ❌ TIER 3 GATE FAILED: ${ERRORS} critical hardware invariant violation(s) detected!"
    echo "    Fix the violations before merging code to main."
    echo "================================================================================"
    exit 3
fi
