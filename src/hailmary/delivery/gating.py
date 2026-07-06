"""Responsible-gaming / jurisdiction gating chokepoint (DESIGN.md §12, §5 Phase 5).

A deterministic chokepoint that runs before ANY report is returned to the
user — locally it's a no-op stub (GATING_ENABLED=false), but the call site
and control flow exist so the architecture demonstrates the principle.
Production behavior (not implemented here): a configurable jurisdiction
allowlist plus an age attestation check, gating on the user's declared/derived
location and confirmed age before releasing any report.
"""


class GatingDeniedError(Exception):
    """Raised when gating is enabled and a request fails the (stubbed) check."""


def check_gating(gating_enabled: bool, user_id: str) -> None:
    """Chokepoint: called before every report is returned. Raises GatingDeniedError
    on denial. Locally this always passes (GATING_ENABLED=false)."""
    if not gating_enabled:
        return
    # Production: look up user_id's jurisdiction + age attestation and deny if
    # outside the allowlist or attestation is missing/false. Not implemented —
    # DESIGN.md §12 explicitly scopes this as a stub for the local demo.
    raise NotImplementedError(
        "GATING_ENABLED=true requires a real jurisdiction/age-attestation "
        "implementation, out of scope for the local demo (DESIGN.md §12)."
    )
