"""
Tests for server/models/solar_model.py

Covers:
  - Cashflow array structure (length, year-0 sign)
  - CapEx calculation (ITC reduction, contingency scaling)
  - Debt/equity split
  - Production degradation
  - IRR type assertion (catches numpy_financial breakage)
  - Smoke test with example_inputs()
"""
import math
import pytest
from server.models.solar_model import SolarInputs, calculate_cashflows, example_inputs


def _make_solar(
    ac_mw: float = 10.0,
    dc_mw: float = 13.0,
    capacity_factor: float = 0.25,
    degradation: float = 0.005,
    fixed_om_per_kw: float = 20.0,
    insurance_per_kw: float = 2.0,
    ppa_price: float = 40.0,
    ppa_escalator: float = 0.0,
    merchant_percentage: float = 0.0,
    merchant_price: float = 0.0,
    debt_fraction: float = 0.0,
    debt_interest_rate: float = 0.05,
    debt_tenor_years: int = 18,
    equity_return_target: float = 0.12,
    tax_rate: float = 0.26,
    itc_percent: float = 0.30,
    module_cost_per_kw: float = 300.0,
    inverter_cost_per_kw: float = 50.0,
    bos_cost_per_kw: float = 200.0,
    interconnect_cost: float = 1_000_000.0,
    land_cost: float = 500_000.0,
    development_cost: float = 500_000.0,
    contingency_percent: float = 0.05,
    **overrides,
) -> SolarInputs:
    kwargs = dict(locals())
    kwargs.pop("overrides")
    kwargs.update(overrides)
    return SolarInputs(**kwargs)


# ── Cashflow structure ────────────────────────────────────────────────────────

class TestCashflowStructure:
    def test_cashflow_length_is_years_plus_one(self):
        inputs = _make_solar()
        for years in (5, 20, 30):
            result = calculate_cashflows(inputs, years=years)
            assert len(result["cashflows"]) == years + 1

    def test_year_zero_cashflow_is_negative(self):
        """Year 0 represents the equity investment — must be negative."""
        inputs = _make_solar(debt_fraction=0.0)
        result = calculate_cashflows(inputs, years=10)
        assert result["cashflows"][0] < 0

    def test_all_output_keys_present(self):
        result = calculate_cashflows(_make_solar(), years=5)
        for key in ("cashflows", "irr", "capex", "debt_amount", "equity_amount"):
            assert key in result


# ── CapEx & financing ─────────────────────────────────────────────────────────

class TestCapexAndFinancing:
    def test_itc_reduces_net_capex(self):
        no_itc = calculate_cashflows(_make_solar(itc_percent=0.0), years=5)
        with_itc = calculate_cashflows(_make_solar(itc_percent=0.30), years=5)
        assert with_itc["capex"] < no_itc["capex"]

    def test_contingency_increases_net_capex(self):
        base = calculate_cashflows(_make_solar(contingency_percent=0.0, itc_percent=0.0), years=5)
        cont = calculate_cashflows(_make_solar(contingency_percent=0.10, itc_percent=0.0), years=5)
        assert cont["capex"] > base["capex"]

    def test_zero_debt_fraction_means_all_equity(self):
        result = calculate_cashflows(_make_solar(debt_fraction=0.0), years=5)
        assert result["debt_amount"] == 0.0
        assert abs(result["equity_amount"] - result["capex"]) < 0.01

    def test_partial_debt_splits_correctly(self):
        result = calculate_cashflows(_make_solar(debt_fraction=0.6), years=5)
        total = result["debt_amount"] + result["equity_amount"]
        assert abs(total - result["capex"]) < 1.0  # rounding tolerance


# ── Production & degradation ──────────────────────────────────────────────────

class TestDegradation:
    def test_degradation_reduces_cashflow_over_time_at_fixed_ppa(self):
        """With no PPA escalation and positive degradation, later cashflows < earlier ones."""
        inputs = _make_solar(degradation=0.01, ppa_escalator=0.0, debt_fraction=0.0)
        result = calculate_cashflows(inputs, years=20)
        # Year 1 (index 1) should be higher than year 20 (index 20)
        assert result["cashflows"][1] > result["cashflows"][20]

    def test_zero_degradation_constant_revenue_at_fixed_ppa(self):
        """With zero degradation and no PPA escalation, operating cashflows should be equal."""
        inputs = _make_solar(degradation=0.0, ppa_escalator=0.0, debt_fraction=0.0, tax_rate=0.0)
        result = calculate_cashflows(inputs, years=5)
        cfs = result["cashflows"][1:]  # skip year 0
        # All annual cashflows should be roughly equal (same revenue, same opex)
        assert max(cfs) - min(cfs) < 1.0  # within $1 rounding


# ── IRR ───────────────────────────────────────────────────────────────────────

class TestIrr:
    def test_irr_is_float_not_none_with_example_inputs(self):
        """IRR must be a float — not None.
        
        Failure here means np.irr / numpy_financial is broken.
        """
        result = calculate_cashflows(example_inputs(), years=30)
        assert result["irr"] is not None, (
            "IRR is None. np.irr was removed in NumPy ≥ 1.20. "
            "Fix: use numpy_financial.irr() instead."
        )
        assert isinstance(result["irr"], float)
        assert not math.isnan(result["irr"]), "IRR is NaN — cashflow pattern may not converge"

    def test_irr_is_reasonable_for_example_inputs(self):
        """Example inputs represent a viable project — IRR should be between 5% and 50%."""
        result = calculate_cashflows(example_inputs(), years=30)
        if result["irr"] is None:
            pytest.skip("IRR could not be calculated (numpy_financial likely missing)")
        assert 0.05 <= result["irr"] <= 0.50, f"IRR {result['irr']:.1%} is outside reasonable range"


# ── Smoke test ────────────────────────────────────────────────────────────────

def test_example_inputs_runs_and_produces_valid_result():
    result = calculate_cashflows(example_inputs(), years=30)
    assert result["capex"] > 0
    assert result["equity_amount"] > 0
    assert len(result["cashflows"]) == 31
