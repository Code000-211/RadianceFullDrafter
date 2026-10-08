# Files

- [Engine Runtime & Decode Pipeline](engine_runtime.md) - Architectural explanation of RadianceMine's dual-GPU decode loop, AQL packet dispatch, host-device synchronization, and zero-CPU-wait pipelining.
- [RDNA4 Kernel Architecture & GEMM](gemm_and_kernels.md) - Microarchitectural principles of AMD RDNA4 (gfx1201) compute kernels, Wave32 scheduling, 24-VGPR allocation granularity, and W4A8 GEMM optimization.
- [Dual-GPU P2P Interconnect & All-Reduce](p2p_interconnect.md) - Architecture of peer-to-peer All-Reduce across dual AMD Radeon AI PRO R9700 cards, WHT6 wire encoding, unified virtual addressing, and store-drain barrier synchronization.
- [MTP Speculative Decoding & Draft Heads](speculative_mtp.md) - Multi-Token Prediction (MTP) architecture in RadianceMine, reduced-vocabulary draft heads (FR-Spec), draft window progression, and speculative depth control.
