# Clean Environment Configuration for opt146_golden_baseline (2026-10-08_091556)
export RADIANCE_HOME="${RADIANCE_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/radiance_home" && pwd)}"
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0,1}"
export RDNA_ARCH="gfx1201"
export RADIANCE_HEAT_RESIDENCY=0
export RADIANCE_SPEC_FLOOR=3
