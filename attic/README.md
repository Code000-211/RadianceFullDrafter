# RadianceMine Attic (`attic/`)

> **Policy**: Rule 4 of [`ENGINEERING_CONSTITUTION.md`](file:///home/orca/RadianceMine/ENGINEERING_CONSTITUTION.md) — ZERO DESTRUCTIVE DELETIONS.  
> **Purpose**: Quarantined preservation of deprecated code, failed experimental branches, toxic patches, and forensic post-mortems.

---

## 1. The Zero-Deletion Invariant

In high-performance kernel engineering, negative results are as valuable as positive ones. Deleting failed code causes future engineers and agents to repeat identical architectural mistakes.

**Rule**: Code is never deleted via `rm` or `git rm` without archival. Any deprecated kernel, abandoned speculative prototype, or superseded optimization MUST be moved into `attic/<date>_<description>/`.

---

## 2. Mandatory Post-Mortem Requirements

Every directory in `attic/` must include a `POST_MORTEM.md` answering:

1. **Original Hypothesis**: What architectural gain was expected?
2. **Implementation Summary**: Which kernels, files, or dispatch pathways were modified?
3. **Failure Mode & Telemetry**:
   - Did it fail Tier 1 (token divergence, speed degradation)?
   - Did it fail Tier 2 (composite score drop, C8 concurrency collapse, prefill stall, latency tail breach)?
   - Did it fail Tier 3 (VGPR occupancy cliff > 96, LDS bank collisions, uncoalesced memory loads, CPU spinlocks)?
4. **Forensic Root Cause**: Why did the hardware reject this design?
5. **Key Lessons & Guidance**: Explicit instructions preventing future attempts from making the same assumption.

---

## 3. Quarantined Historical Regressions (Lessons from Post-Opt146)

Based on [`candidates/POST_OPT146_FORENSIC_AUDIT_AND_EVALUATION.md`](file:///home/orca/RadianceMine/candidates/POST_OPT146_FORENSIC_AUDIT_AND_EVALUATION.md):

| Quarantined Anti-Pattern | Root Cause of Failure | Impact on System |
|---|---|---|
| **Residency Lock (`RADIANCE_HEAT_RESIDENCY > 0`)** | Prohibited MoE expert eviction for 30 dispatches; prevented dynamic expert swap between Chat, Code, and Math prompts. | Forced active Code experts into slow host PCIe Zero-Copy. Decode collapsed from 210 to 75.6 tok/s. |
| **Unconstrained Static Draft Depth (`NUM_SPECULATIVE_TOKENS=5`)** | Forced 5 serial draft forward passes even when average draft acceptance was ~2.3 tokens. | Wasted GPU compute on un-accepted rounds; increased ITL variance. |
| **Background Polling Daemons (`gpu_sentinel` / `pulse_kernel`)** | Injected asynchronous GPU pulse kernels every 8ms. | Continuously contended for command queues and PCIe bus bandwidth during benchmarks. |
| **Atomic Arrival Dispatches in MoE Router** | Uncoalesced atomic counters in global memory across dual-GPU interconnect. | Caused severe wavefront serialization and memory latency bubbles. |
| **Unclamped Speculative Floor (`pld_max` clipping)** | Allowed depth to drop to 1 token during minor entropy spikes without recovery hysteresis. | Collapsed throughput on mixed-entropy code generation. |
