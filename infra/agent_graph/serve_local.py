"""Prepare or explicitly launch a local-only inference container. Never downloads.

The operator imports model weights + a reviewed image by digest and creates an
internal Docker network. --launch is explicit; default prints a reviewable plan.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def plan(weights, image, network):
    spec = json.loads((Path(__file__).parent / "local-reference.json").read_text())
    weights = Path(weights).resolve(strict=True)
    if not re.fullmatch(r"vllm/vllm-openai:v0\.15\.1@sha256:[a-f0-9]{64}", image):
        raise ValueError("reviewed_image_digest_required")
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", network):
        raise ValueError("invalid_network_name")
    index = weights / "model.safetensors.index.json"
    cfg = json.loads((weights / "config.json").read_text())
    if cfg.get("model_type") != "qwen3_moe" or cfg.get("quantization_config"):
        raise ValueError("reference_requires_qwen3_moe_BF16")
    hashes = {}
    for path in sorted(weights.rglob("*")):
        if path.is_symlink():
            raise ValueError("materialized_weights_required_no_symlinks")
        if not path.is_file():
            continue
        h = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                h.update(chunk)
        hashes[path.relative_to(weights).as_posix()] = h.hexdigest()
    shards = set(json.loads(index.read_text())["weight_map"].values())
    if not shards or not shards.issubset(hashes):
        raise ValueError("missing_weight_shards")
    # Comparing these hashes with an independently imported acquisition manifest
    # is operator responsibility; hashes alone don't prove Hugging Face origin.
    command = ["docker", "run", "--rm", "--pull=never", "--gpus", "device=0",
               "--network", network, "--publish", "127.0.0.1:8000:8000",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only",
               "--user", "10001:10001", "--tmpfs", "/tmp:rw,nosuid,size=8g", "--shm-size", "4g",
               "--mount", f"type=bind,source={weights},target=/weights,readonly",
               "--env", "HF_HUB_OFFLINE=1", "--env", "TRANSFORMERS_OFFLINE=1",
               "--env", "VLLM_NO_USAGE_STATS=1", "--env", "DO_NOT_TRACK=1",
               "--env", "HF_HOME=/tmp/hf", "--env", "HOME=/tmp", "--env", "XDG_CACHE_HOME=/tmp/cache",
               "--env", "TRITON_CACHE_DIR=/tmp/triton", image,
               "--model", "/weights", "--served-model-name", spec["served_model_name"],
               "--dtype", "bfloat16", "--max-model-len", str(spec["max_model_len"]),
               "--max-num-seqs", "1", "--gpu-memory-utilization", "0.9",
               "--disable-log-requests", "--host", "0.0.0.0", "--port", "8000"]
    return dict(status="PREPARED_NOT_GPU_QUALIFIED", model_revision=spec["model_revision"],
                image=image, hashes=hashes, command=command)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--weights", required=True)
    p.add_argument("--image", required=True)
    p.add_argument("--network", default="graph-inference-internal")
    p.add_argument("--output", required=True)
    p.add_argument("--launch", action="store_true")
    a = p.parse_args()
    result = plan(a.weights, a.image, a.network)
    Path(a.output).write_text(json.dumps(result, indent=2) + "\n")
    if a.launch:
        data = subprocess.run(["docker", "network", "inspect", a.network], check=True, capture_output=True, text=True)
        if not all(n.get("Internal") for n in json.loads(data.stdout)):
            raise ValueError("internal_network_required")
        subprocess.run(result["command"], check=True)
    else:
        print(json.dumps({k: v for k, v in result.items() if k != "hashes"}, indent=2))
