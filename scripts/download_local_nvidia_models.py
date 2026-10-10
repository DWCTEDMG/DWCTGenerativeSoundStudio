"""Download the pinned Studio NVIDIA snapshots into local WSL storage."""
import argparse
from pathlib import Path
from huggingface_hub import snapshot_download

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--token-file", type=Path, help="Read an existing HF credential without printing it")
parser.add_argument("--root", type=Path, default=Path.home() / "edmg/models/director-nvidia")
args = parser.parse_args()
token = args.token_file.read_text().strip() if args.token_file else None
models = [
    ("nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-BF16", "e5e9932441de940c9a62185c870ea5bcd4cd24e2", "nemotron-omni-bf16"),
    ("nvidia/Cosmos-Reason2-8B", "a9fae2cf89dc64db96b12860417f0eb403013bb9", "cosmos-reason2-8b"),
]
for repo, revision, folder in models:
    print(f"Downloading {repo} at {revision}", flush=True)
    snapshot_download(repo, revision=revision, local_dir=args.root / folder, token=token, max_workers=4)
snapshot_download("nvidia/C-RADIOv4-H", revision="0057b339059c0b9e1b4ba996f975410ebbfdfcc8",
                  allow_patterns=["*.py", "config.json"], token=token)
print("NVIDIA snapshots downloaded. GPU inference must still be verified.", flush=True)
