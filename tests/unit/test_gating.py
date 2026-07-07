"""Tests for the responsible-gaming/jurisdiction gating chokepoint."""

import pytest

from hailmary.delivery.gating import check_gating


@pytest.mark.unit
def test_gating_disabled_always_passes():
    check_gating(gating_enabled=False, user_id="u1")  # no exception


@pytest.mark.unit
def test_gating_enabled_raises_not_implemented_for_the_stub():
    with pytest.raises(NotImplementedError):
        check_gating(gating_enabled=True, user_id="u1")
