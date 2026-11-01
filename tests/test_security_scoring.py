"""Security decision matrix and opportunity scoring."""

from __future__ import annotations

import pytest

from app.models.enums import SecurityStatus
from app.providers.base import SecurityField, SecurityResult
from app.services.scoring import WEIGHTS, ScoreInputs, compute_score
from app.services.security import CRITICAL_FIELDS, assess


def _field(name: str, status: str = "PASS", value=None) -> SecurityField:
    return SecurityField(name=name, status=status, value=value, reason=f"{name} {status}", source="fake")


def _result(
    chain: str = "solana",
    *,
    provider: str = "goplus",
    overrides: dict[str, SecurityField] | None = None,
    omit: set[str] | None = None,
    available: bool = True,
) -> SecurityResult:
    defaults = {
        "honeypot": False,
        "mintable": False,
        "freezable": False,
        "lp_lock": 100.0,
        "buy_tax": 0.0,
        "sell_tax": 0.0,
        "ownership": "renounced",
        "holder_concentration": 25.0,
        "holder_count": 420,
    }
    fields = {
        name: _field(name, "PASS", value)
        for name, value in defaults.items()
        if name not in (omit or set())
    }
    fields.update(overrides or {})
    return SecurityResult(chain=chain, token_address="addr", provider=provider, fields=fields, available=available)


def _assess(results, chain="solana"):
    return assess(chain=chain, token_address="addr", results=results)


def test_all_critical_fields_pass_is_eligible():
    assessment = _assess([_result()])
    assert assessment.overall == SecurityStatus.PASS.value
    assert assessment.eligible is True
    assert assessment.critical_pass == assessment.critical_total == len(CRITICAL_FIELDS["solana"])
    assert assessment.critical_unknown == 0
    assert assessment.buy_tax_known and assessment.sell_tax_known
    assert 0 < assessment.risk_score < 50


def test_honeypot_failure_rejects_token():
    assessment = _assess(
        [_result(overrides={"honeypot": _field("honeypot", "FAIL", True)})]
    )
    assert assessment.overall == SecurityStatus.FAIL.value
    assert assessment.eligible is False
    assert assessment.risk_score >= 90


def test_high_tax_failure_rejects_token():
    assessment = _assess(
        [
            _result(
                chain="bsc",
                overrides={"sell_tax": _field("sell_tax", "FAIL", 25.0)},
            )
        ],
        chain="bsc",
    )
    assert assessment.overall == SecurityStatus.FAIL.value
    assert assessment.eligible is False


def test_lp_lock_below_ten_percent_is_forced_to_fail():
    assessment = _assess(
        [_result(overrides={"lp_lock": _field("lp_lock", "PASS", 5.0)})]
    )
    assert assessment.overall == SecurityStatus.FAIL.value
    assert assessment.fields["lp_lock"]["status"] == "FAIL"
    assert assessment.lp_lock_pct == pytest.approx(5.0)


def test_top_ten_concentration_above_sixty_percent_is_forced_to_fail():
    assessment = _assess(
        [
            _result(
                overrides={
                    "holder_concentration": _field("holder_concentration", "PASS", 72.0)
                }
            )
        ]
    )
    assert assessment.overall == SecurityStatus.FAIL.value
    assert assessment.holder_concentration == pytest.approx(72.0)


def test_missing_critical_field_is_unknown_and_ineligible():
    assessment = _assess([_result(omit={"freezable"})])
    assert assessment.overall == SecurityStatus.UNKNOWN.value
    assert assessment.eligible is False
    assert assessment.critical_unknown == 1
    assert assessment.critical_pass == len(CRITICAL_FIELDS["solana"]) - 1


def test_no_provider_data_is_unavailable_and_blocks_entry():
    assessment = _assess([])
    assert assessment.overall == SecurityStatus.UNAVAILABLE.value
    assert assessment.eligible is False
    assert assessment.risk_score == 90.0
    assert assessment.critical_pass == 0
    assert any("No security provider" in reason for reason in assessment.reasons)


def test_unavailable_provider_is_not_treated_as_safe():
    assessment = _assess([_result(available=False, omit={"honeypot", "buy_tax", "sell_tax"})])
    assert assessment.overall in {SecurityStatus.UNAVAILABLE.value, SecurityStatus.UNKNOWN.value}
    assert assessment.eligible is False


def test_single_warning_is_eligible_and_two_are_not():
    one = _assess([_result(overrides={"pausable": _field("pausable", "WARNING", False)})])
    assert one.overall == SecurityStatus.WARNING.value
    assert one.warning_count == 1
    assert one.eligible is True

    two = _assess(
        [
            _result(
                overrides={
                    "pausable": _field("pausable", "WARNING", False),
                    "blacklist": _field("blacklist", "WARNING", True),
                }
            )
        ]
    )
    assert two.overall == SecurityStatus.WARNING.value
    assert two.warning_count == 2
    assert two.eligible is False


def test_unknown_tax_is_reported_as_unknown():
    assessment = _assess(
        [
            _result(
                chain="bsc",
                overrides={
                    "buy_tax": _field("buy_tax", "UNKNOWN"),
                    "sell_tax": _field("sell_tax", "UNKNOWN"),
                },
            )
        ],
        chain="bsc",
    )
    assert assessment.buy_tax_known is False
    assert assessment.sell_tax_known is False
    assert assessment.buy_tax_pct is None


def test_solana_transfer_fee_synthesises_sell_tax():
    assessment = _assess(
        [_result(overrides={"transfer_fee": _field("transfer_fee", "PASS", 3.0)})]
    )
    assert assessment.sell_tax_pct == pytest.approx(3.0)
    assert assessment.buy_tax_pct == pytest.approx(0.0)


def test_bsc_requires_ownership_and_lp_lock():
    assessment = _assess([_result(chain="bsc")], chain="bsc")
    assert assessment.critical_total == len(CRITICAL_FIELDS["bsc"])
    assert assessment.overall == SecurityStatus.PASS.value


# -- scoring ------------------------------------------------------------------
def _inputs(**overrides) -> ScoreInputs:
    base = dict(
        liquidity_usd=250_000.0,
        volume_h1=200_000.0,
        volume_m5=20_000.0,
        buys_h1=120,
        sells_h1=60,
        pct_h1=12.0,
        pct_m5=1.0,
        holder_concentration=20.0,
        holder_count=800,
        security_overall=SecurityStatus.PASS.value,
        critical_pass=6,
        critical_total=6,
        providers_available=2,
        providers_total=2,
        snapshot_age_seconds=20.0,
        history_points=12,
        prices=[0.001, 0.00105, 0.0011, 0.00112],
    )
    base.update(overrides)
    return ScoreInputs(**base)


def test_weights_sum_to_one_hundred():
    assert sum(WEIGHTS.values()) == pytest.approx(100.0)


def test_strong_inputs_score_high_with_explanations():
    scored = compute_score(_inputs(), security_risk=10.0)
    assert scored.score >= 85.0
    assert scored.confidence >= 0.85
    assert scored.rank_score == pytest.approx(scored.score * scored.confidence, rel=1e-4)
    assert scored.components["liquidity"] > 23.0
    assert scored.components["liquidity"] <= WEIGHTS["liquidity"]
    assert len(scored.explanations) >= 7
    row = scored.as_row()
    assert set(row["components"]) == set(WEIGHTS)
    assert 0 <= row["score"] <= 100


def test_weak_inputs_score_low_and_spike_is_penalised():
    weak = compute_score(
        _inputs(
            liquidity_usd=6_000.0,
            volume_h1=100.0,
            buys_h1=5,
            sells_h1=9,
            pct_h1=-20.0,
            holder_concentration=80.0,
            holder_count=20,
            critical_pass=2,
        ),
        security_risk=80.0,
    )
    assert weak.score < 25.0
    assert weak.components["momentum"] < 3.0
    assert weak.components["liquidity"] < 5.0

    spike = compute_score(_inputs(pct_m5=40.0), security_risk=10.0)
    normal = compute_score(_inputs(), security_risk=10.0)
    assert spike.components["momentum"] < normal.components["momentum"]
    assert any("vertical" in note.lower() for note in spike.explanations)


def test_confidence_decays_with_staleness_and_missing_providers():
    fresh = compute_score(_inputs(snapshot_age_seconds=10), 10.0)
    aged = compute_score(_inputs(snapshot_age_seconds=900), 10.0)
    degraded = compute_score(_inputs(providers_available=1, providers_total=2), 10.0)
    assert fresh.confidence > aged.confidence
    assert fresh.confidence > degraded.confidence
    assert 0.0 <= aged.confidence <= 1.0


def test_security_component_zero_on_failure():
    failed = compute_score(
        _inputs(security_overall=SecurityStatus.FAIL.value, critical_pass=0), 95.0
    )
    assert failed.components["security"] == 0.0
    assert "0/6 critical checks verified" in failed.explanations[5]
