"""AI-platform inventory: the models and prompts in use, as a governable manifest.

Two enterprise-AI concerns made concrete and auditable:

- **model inventory** (``config/models.yaml``): what models run, at which version,
  for what purpose, owned by whom, with what approval status; and
- **prompt versioning** (``brain_app.prompts``): the named, versioned, content-hashed
  prompts the agent team is built from.

``manifest()`` combines them into one record. It is deliberately dependency-light
(no ADK, no cloud), so ``brain platform`` and the UI can display it anywhere.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .prompts import registry

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODELS_FILE = _REPO_ROOT / "config" / "models.yaml"


def models() -> list[dict]:
    """The registered models (from ``config/models.yaml``)."""
    if not _MODELS_FILE.is_file():
        return []
    data = yaml.safe_load(_MODELS_FILE.read_text(encoding="utf-8")) or {}
    return list(data.get("models", []))


def prompts() -> list[dict]:
    """The versioned prompts the agent is built from (name, version, content hash)."""
    return [{"name": p.name, "version": p.version, "sha": p.sha} for p in registry()]


def manifest() -> dict:
    """The full AI-platform manifest: models + prompt versions."""
    return {"models": models(), "prompts": prompts()}


def main() -> int:
    m = manifest()
    print("Models in use:")
    for mo in m["models"]:
        print(f"  {mo['id']:22} {mo.get('status', ''):9} {mo.get('purpose', '')}")
    print("\nPrompts (versioned, content-hashed):")
    for p in m["prompts"]:
        print(f"  {p['name']:14} v{p['version']}  {p['sha']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
