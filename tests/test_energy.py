"""The integration step behind the Battery Charge / Discharge Energy counters."""

import pytest

from fossibot_ha.sensor import MAX_INTEGRATION_GAP, add_energy


def test_left_riemann_step():
    # 1200 W held for 30 s = 10 Wh = 0.01 kWh
    assert add_energy(0.0, 1200, 30) == pytest.approx(0.01)
    assert add_energy(1.5, 600, 60) == pytest.approx(1.51)


@pytest.mark.parametrize("power,seconds", [
    (1200, 0),                          # no time passed
    (1200, -5),                         # clock went backwards
    (1200, MAX_INTEGRATION_GAP + 1),    # gap too long to trust (restart, reconnect)
    (0, 30),                            # idle
    (-50, 30),                          # the split keys are never negative; guard anyway
])
def test_step_is_skipped(power, seconds):
    assert add_energy(2.0, power, seconds) == 2.0


def test_gap_limit_is_inclusive():
    assert add_energy(0.0, 3600, MAX_INTEGRATION_GAP) == pytest.approx(MAX_INTEGRATION_GAP / 3600)
