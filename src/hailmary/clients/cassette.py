"""Shared cassette read/write mechanism for deterministic, keyless CI (PLAN.md M1.9).

"real Anthropic responses recorded once, keyed by SHA-256 of (model, prompt_version,
rendered prompt); replayed as validated instructor outputs. CI needs no secrets.
Prompt change -> cassette miss -> CI fails loudly -> re-record. Same pattern for
Voyage query embeddings."
"""

import hashlib
import json
from pathlib import Path


class CassetteMissError(Exception):
    """Raised in replay mode when no recorded cassette matches the request key.

    This is a loud failure by design — a missing cassette after a prompt/model
    change must fail CI, not silently fall through to a live call.
    """


def cassette_key(*parts: str) -> str:
    payload = json.dumps(list(parts), sort_keys=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cassette_path(cassette_dir: Path, key: str) -> Path:
    return cassette_dir / f"{key}.json"


def load_cassette(cassette_dir: Path, key: str) -> dict:
    path = cassette_path(cassette_dir, key)
    if not path.exists():
        raise CassetteMissError(
            f"No cassette for key {key} in {cassette_dir}. "
            "Run scripts/record_cassettes.py to record it against the real API."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def save_cassette(cassette_dir: Path, key: str, response: dict) -> None:
    cassette_dir.mkdir(parents=True, exist_ok=True)
    path = cassette_path(cassette_dir, key)
    path.write_text(json.dumps(response, indent=2), encoding="utf-8")
