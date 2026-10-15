"""BF16 Safetensors Sidecar Exporter for FullDrafter (K=12, gfx1201 Dual GPU TP=2).

Converts PyTorch checkpoint (drafter_final.pt) into a BF16 safetensors binary and companion manifest.
Enforces strict teacher matrix quarantine and SHA-256 cryptographic binding against model contracts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch
from safetensors.torch import save_file

# Architectural constants
EXPECTED_PARAM_COUNT = 87688704
EXPECTED_TENSOR_COUNT = 38
EXPECTED_BYTE_SIZE = 175377408  # 87,688,704 * 2 bytes in BF16

FORBIDDEN_TEACHER_PATTERNS = [
    r"target_embedding",
    r"target_lm_head",
    r"target_endnorm",
    r"target_final_norm",
    r"target_trunk",
    r"teacher\.",
    r"frozen_teacher",
]

HEX_SHA256_REGEX = re.compile(r"^[0-9a-fA-F]{64}$")

DEFAULT_CHECKPOINT = Path("/home/orca/drafter_data/checkpoints/flash_next_k12/drafter_final.pt")
DEFAULT_OUTPUT = Path("/home/orca/drafter_data/checkpoints/flash_next_k12/drafter_final.safetensors")
DEFAULT_CONTRACT = Path("/home/orca/Drafter/research/block_drafter/contracts/model_contract_flash_next.json")


class SidecarSecurityError(RuntimeError):
    """Raised when quarantine or security isolation rules are violated."""


class SidecarValidationError(ValueError):
    """Raised when shapes, parameter counts, or hashes violate specifications."""


def compute_file_sha256(filepath: Path) -> str:
    """Computes SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest().lower()


def expected_tensor_shapes() -> dict[str, tuple[int, ...]]:
    """The fixed FullDrafter ABI, not merely its aggregate parameter count."""
    shapes = {
        "drafter.mask_vector": (768,), "drafter.context_proj.weight": (768, 7680),
        "drafter.context_norm.weight": (768,), "drafter.anchor_proj.weight": (768, 2560),
        "drafter.final_norm.weight": (768,), "drafter.out_proj.weight": (2560, 768),
        "conv.w_base": (2, 768), "conv.w_proj.weight": (96, 768),
        "recurrent_norm.weight": (768,),
        "markov.matrix_a.weight": (248320, 64), "markov.matrix_b.weight": (248320, 64),
        "selector.pred_codebook.weight": (248320, 64),
        "selector.succ_codebook.weight": (248320, 64),
        "selector.hidden_proj.weight": (64, 768),
    }
    for head in ("confidence", "verification"):
        for name, shape in (("norm", (768,)), ("fc1", (256, 768)), ("fc2", (1, 256))):
            shapes[f"{head}.{name}.weight"] = shape
    for block in range(2):
        prefix = f"drafter.blocks.{block}."
        for name, shape in {
            "input_layernorm": (768,), "post_attention_layernorm": (768,),
            "self_attn.q_proj": (768, 768), "self_attn.k_proj": (256, 768),
            "self_attn.v_proj": (256, 768), "self_attn.o_proj": (768, 768),
            "mlp.gate_proj": (2304, 768), "mlp.up_proj": (2304, 768),
            "mlp.down_proj": (768, 2304),
        }.items():
            shapes[prefix + name + ".weight"] = shape
    return shapes


def validate_tensor_shapes(state_dict: dict) -> None:
    expected = expected_tensor_shapes()
    if set(state_dict) != set(expected):
        raise SidecarValidationError("Tensor names do not match the FullDrafter ABI")
    for name, shape in expected.items():
        tensor = state_dict[name]
        if not isinstance(tensor, torch.Tensor) or tuple(tensor.shape) != shape:
            raise SidecarValidationError(f"Invalid tensor shape for {name}; expected {shape}")


def export_fulldrafter_sidecar(
    checkpoint_path: Path,
    output_path: Path,
    contract_path: Path | None = None,
    strict: bool = True,
) -> tuple[Path, Path, dict[str, Any]]:
    """Loads drafter checkpoint, validates quarantine, converts to BF16, and writes safetensors & manifest."""
    print(f"[SidecarExporter] Loading checkpoint: {checkpoint_path}")
    if not checkpoint_path.exists():
        raise FileNotFoundError(f"Checkpoint does not exist: {checkpoint_path}")

    ckpt = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    state_dict = ckpt.get("model_state_dict", ckpt)
    if not isinstance(state_dict, dict):
        raise SidecarValidationError(f"Expected dict state_dict, got {type(state_dict)}")

    # 1. Enforce strict Teacher Weight Quarantine
    print("[SidecarExporter] Validating teacher weight quarantine...")
    for tensor_name in state_dict:
        for pat in FORBIDDEN_TEACHER_PATTERNS:
            if re.search(pat, tensor_name, re.IGNORECASE):
                raise SidecarSecurityError(
                    f"Quarantine violation! Forbidden pattern '{pat}' matched tensor '{tensor_name}'. "
                    "Frozen teacher weights must never be packaged into sidecar weights."
                )

    if strict and len(state_dict) != EXPECTED_TENSOR_COUNT:
        raise SidecarValidationError(
            f"Expected {EXPECTED_TENSOR_COUNT} tensors, found {len(state_dict)}"
        )

    # 2. Extract and validate target hashes from contract or checkpoint
    target_emb_sha = ""
    target_head_sha = ""
    target_norm_sha = ""
    target_model_id = "Qwen3.8-Flash-Next"

    if contract_path and contract_path.exists():
        print(f"[SidecarExporter] Reading contract: {contract_path}")
        with open(contract_path, "r", encoding="utf-8") as f:
            contract_data = json.load(f)
        target_model_id = contract_data.get("target_model", target_model_id)
        target_hashes = contract_data.get("target_hashes", {})
        target_emb_sha = target_hashes.get("target_embedding_sha256", "")
        target_head_sha = target_hashes.get("target_head_sha256", "")
        target_norm_sha = target_hashes.get("target_final_norm_sha256") or target_hashes.get("target_endnorm_sha256", "")

    # A contract must not relabel weights trained against a different teacher.
    ckpt_teacher = ckpt.get("teacher", {})
    for key, declared in (("target_embedding_sha256", target_emb_sha),
                          ("target_head_sha256", target_head_sha)):
        trained = ckpt_teacher.get(key, "")
        if declared and trained and declared.lower() != trained.lower():
            raise SidecarValidationError(f"Teacher binding mismatch for {key}")
    # Fallback only when the contract does not provide the binding.
    if not target_emb_sha:
        target_emb_sha = ckpt_teacher.get("target_embedding_sha256", "")
    if not target_head_sha:
        target_head_sha = ckpt_teacher.get("target_head_sha256", "")

    print(f"[SidecarExporter] Target embedding SHA-256: {target_emb_sha}")
    print(f"[SidecarExporter] Target LM head SHA-256:   {target_head_sha}")

    if strict:
        if not target_emb_sha or not HEX_SHA256_REGEX.match(target_emb_sha):
            raise SidecarValidationError(f"Invalid target_embedding_sha256: '{target_emb_sha}'")
        if not target_head_sha or not HEX_SHA256_REGEX.match(target_head_sha):
            raise SidecarValidationError(f"Invalid target_head_sha256: '{target_head_sha}'")

    if strict:
        validate_tensor_shapes(state_dict)

    # 3. Convert all tensors to contiguous BF16
    print("[SidecarExporter] Converting weights to BF16 and computing memory footprint...")
    bf16_dict: dict[str, torch.Tensor] = {}
    total_elements = 0
    total_bytes = 0

    for name, tensor in state_dict.items():
        if not isinstance(tensor, torch.Tensor):
            raise SidecarValidationError(f"Entry '{name}' is not a torch.Tensor")
        t_bf16 = tensor.detach().cpu().to(torch.bfloat16).contiguous()
        bf16_dict[name] = t_bf16
        total_elements += t_bf16.numel()
        total_bytes += t_bf16.numel() * 2

    print(f"[SidecarExporter] Converted {len(bf16_dict)} tensors: {total_elements} elements, {total_bytes} bytes")
    if strict and total_elements != EXPECTED_PARAM_COUNT:
        raise SidecarValidationError(
            f"Parameter count mismatch: expected {EXPECTED_PARAM_COUNT}, got {total_elements}"
        )
    if strict and total_bytes != EXPECTED_BYTE_SIZE:
        raise SidecarValidationError(
            f"Byte size mismatch: expected {EXPECTED_BYTE_SIZE}, got {total_bytes}"
        )

    # 4. Prepare safetensors metadata header
    exported_at = datetime.now(timezone.utc).isoformat()
    header_meta = {
        "format": "safetensors",
        "version": "1.0",
        "dtype": "bfloat16",
        "parameter_count": str(total_elements),
        "sidecar_size_bytes": str(total_bytes),
        "target_model_id": target_model_id,
        "target_embedding_sha256": target_emb_sha,
        "target_head_sha256": target_head_sha,
        "target_final_norm_sha256": target_norm_sha or "",
        "target_endnorm_sha256": target_norm_sha or "",
        "model_type": "full",
        "architecture": "FullDrafter",
        "stages": "2",
        "proposal_length_k": "12",
        "exported_at": exported_at,
    }

    # 5. Write Safetensors binary
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[SidecarExporter] Writing safetensors to {output_path}...")
    save_file(bf16_dict, str(output_path), metadata=header_meta)
    actual_file_size = output_path.stat().st_size
    print(f"[SidecarExporter] Safetensors file size: {actual_file_size} bytes ({actual_file_size / (1024*1024):.2f} MiB)")

    # 6. Compute file SHA-256 for manifest binding
    file_sha256 = compute_file_sha256(output_path)
    print(f"[SidecarExporter] Safetensors file SHA-256: {file_sha256}")

    # 7. Write Companion JSON Manifest
    manifest_data: dict[str, Any] = {
        "format": "safetensors",
        "version": "1.0",
        "sidecar_size_bytes": actual_file_size,
        "parameter_count": total_elements,
        "dtype": "bfloat16",
        "target_model_id": target_model_id,
        "target_embedding_sha256": target_emb_sha,
        "target_head_sha256": target_head_sha,
        "target_final_norm_sha256": target_norm_sha or "",
        "target_endnorm_sha256": target_norm_sha or "",
        "model_type": "full",
        "architecture": {
            "name": "FullDrafter",
            "stages": 2,
            "block_k": 6,
            "total_k": 12,
            "hidden_size": 768,
            "target_width": 2560,
            "context_dim": 7680,
            "vocab_size": 248320,
            "active_vocab": 248077,
        },
        "safetensors_file_sha256": file_sha256,
        "exported_at": exported_at,
    }

    # Write primary manifest (drafter_final.manifest.json)
    manifest_path = output_path.with_suffix(".manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)
    print(f"[SidecarExporter] Wrote companion manifest: {manifest_path}")

    # A directory can hold several checkpoints. A shared discovery manifest would
    # silently associate the newest export with older safetensors in that directory.
    # Consumers must use output_path.with_suffix(".manifest.json").

    return output_path, manifest_path, manifest_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Export FullDrafter PyTorch checkpoint to BF16 safetensors")
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT, help="Source .pt checkpoint")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Destination .safetensors path")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT, help="Path to model_contract JSON")
    parser.add_argument("--non-strict", action="store_true", help="Disable strict tensor count/size assertions")
    args = parser.parse_args()

    try:
        out_path, man_path, _ = export_fulldrafter_sidecar(
            checkpoint_path=args.checkpoint,
            output_path=args.output,
            contract_path=args.contract,
            strict=not args.non_strict,
        )
        print(f"[SidecarExporter] Export completed successfully: {out_path} (manifest: {man_path})")
    except (SidecarSecurityError, SidecarValidationError, FileNotFoundError, RuntimeError, ValueError) as e:
        print(f"[SidecarExporter] ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
