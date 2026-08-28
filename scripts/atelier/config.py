"""
config.py: Load device-dependent parameters from semantic.toml.

The config file is gitignored (device-specific). If missing, safe defaults
are used that work on any machine with >=16GB RAM.

Config path: <repo_root>/semantic.toml
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = REPO_ROOT / "semantic.toml"

# Safe defaults (work on any machine with >=16GB)
DEFAULTS: Dict[str, Any] = {
    "max_tokens": 512,
    "encode_batch_size": 4,
    "device": "auto",  # auto-detect: mps > cuda > cpu
}


def _load_toml(path: Path) -> Dict[str, Any]:
    """Load TOML file. Python 3.11+ has tomllib in stdlib."""
    import tomllib

    with open(path, "rb") as f:
        return tomllib.load(f)


def load() -> Dict[str, Any]:
    """Return merged config: file values override defaults."""
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            file_cfg = _load_toml(CONFIG_PATH)
            # Flatten [embedding] section if present
            if "embedding" in file_cfg:
                cfg.update(file_cfg["embedding"])
            else:
                cfg.update(file_cfg)
        except Exception as exc:
            import sys

            print(
                f"warning: {CONFIG_PATH} is malformed "
                f"({type(exc).__name__}: {exc}); using built-in defaults",
                file=sys.stderr,
            )
    return cfg


def resolve_device(cfg_device: str) -> str:
    """Resolve 'auto' to the best available device."""
    if cfg_device != "auto":
        return cfg_device
    try:
        import torch

        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"
