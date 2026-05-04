"""
Tests for server/models/consulting_model.py

Covers:
  - Revenue calculation arithmetic
  - Revenue split between retainer and project work
  - EBITDA and net-income calculations
  - Tax handling (zero tax, positive tax, negative-EBITDA case)
  - Cashflow structure (length, IRR type)
  - Smoke test with example_inputs()
"""
import pytest
from server.models.consulting_model import (
    StaffLevel,
    ConsultingInputs,
    calculate_income_statement,
    example_inputs,
)

AVAILABLE_HOURS_PER_YEAR = 52 * 40  # 2080


def _make_single_analyst(
    headcount: int = 1,
    billing_rate: float = 100.0,
    salary: float = 80_000.0,
    utilization: float = 1.0,
    realization: float = 1.0,
    overhead: dict | None = None,
    tax_rate: float = 0.0,
    equity_investment: float = 0.0,
    retainer_fraction: float = 0.6,
    project_fraction: float = 0.4,
) -> ConsultingInputs:
    """Minimal, deterministic input focused on a single analyst for isolated tests."""
    level = StaffLevel(
        headcount=headcount,
        billing_rate=billing_rate,
        salary=salary,
        utilization=utilization,
        realization=realization,
    )
    zero = StaffLevel(headcount=0, billing_rate=0, salary=0, utilization=0, realization=0)
    return ConsultingInputs(
        partners=zero,
        managers=zero,
        analysts=level,
        retainer_fraction=retainer_fraction,
        project_fraction=project_fraction,
        overhead=overhead or {},
        working_capital={"wip_days": 0, "ar_days": 0, "ap_days": 0},
        financing={"equity_investment": equity_investment},
        tax_rate=tax_rate,
    )


# ── Revenue ──────────────────────────────────────────────────────────────────

class TestRevenue:
    def test_zero_headcount_yields_zero_revenue(self):
        zero = StaffLevel(headcount=0, billing_rate=500, salary=200_000, utilization=0.7, realization=0.9)
        inputs = ConsultingInputs(
            partners=zero, managers=zero, analysts=zero,
            retainer_fraction=0.5, project_fraction=0.5,
            overhead={}, working_capital={}, financing={}, tax_rate=0.25,
        )
        result = calculate_income_statement(inputs)
        assert result["annual_revenue"] == 0.0

    def test_revenue_formula_with_full_utilization_and_realization(self):
        """Revenue = headcount × available_hours × utilization × billing_rate × realization."""
        inputs = _make_single_analyst(billing_rate=100.0, utilization=1.0, realization=1.0)
        result = calculate_income_statement(inputs)
        expected = 1 * AVAILABLE_HOURS_PER_YEAR * 1.0 * 100.0 * 1.0
        assert abs(result["annual_revenue"] - expected) < 0.01

    def test_utilization_scales_revenue_proportionally(self):
        half = _make_single_analyst(utilization=0.5, realization=1.0)
        full = _make_single_analyst(utilization=1.0, realization=1.0)
        r_half = calculate_income_statement(half)["annual_revenue"]
        r_full = calculate_income_statement(full)["annual_revenue"]
        assert abs(r_half - r_full * 0.5) < 0.01

    def test_realization_scales_revenue_proportionally(self):
        half = _make_single_analyst(utilization=1.0, realization=0.5)
        full = _make_single_analyst(utilization=1.0, realization=1.0)
        r_half = calculate_income_statement(half)["annual_revenue"]
        r_full = calculate_income_statement(full)["annual_revenue"]
        assert abs(r_half - r_full * 0.5) < 0.01

    def test_retainer_plus_project_equals_total_revenue(self):
        inputs = _make_single_analyst(retainer_fraction=0.6, project_fraction=0.4)
        result = calculate_income_statement(inputs)
        assert abs(
            result["retainer_revenue"] + result["project_revenue"] - result["annual_revenue"]
        ) < 0.01

    def test_retainer_fraction_applied_correctly(self):
        inputs = _make_single_analyst(retainer_fraction=0.6, project_fraction=0.4)
        result = calculate_income_statement(inputs)
        assert abs(result["retainer_revenue"] - result["annual_revenue"] * 0.6) < 0.01


# ── EBITDA & Net Income ───────────────────────────────────────────────────────

class TestIncomeStatement:
    def test_zero_tax_net_income_equals_ebitda(self):
        inputs = _make_single_analyst(tax_rate=0.0)
        result = calculate_income_statement(inputs)
        assert abs(result["net_income"] - result["ebitda"]) < 0.01

    def test_positive_tax_reduces_net_income(self):
        inputs = _make_single_analyst(tax_rate=0.30)
        result = calculate_income_statement(inputs)
        assert result["net_income"] < result["ebitda"]

    def test_overhead_reduces_ebitda_by_exact_amount(self):
        no_overhead = _make_single_analyst()
        with_overhead = _make_single_analyst(overhead={"rent": 50_000.0})
        r_no = calculate_income_statement(no_overhead)["ebitda"]
        r_with = calculate_income_statement(with_overhead)["ebitda"]
        assert abs(r_no - r_with - 50_000.0) < 0.01

    def test_negative_ebitda_incurs_zero_tax(self):
        """When overhead exceeds revenue, tax = 0 (not negative)."""
        inputs = _make_single_analyst(overhead={"loss": 999_999_999.0}, tax_rate=0.30)
        result = calculate_income_statement(inputs)
        # net_income = ebitda (deeply negative) - 0 tax
        assert abs(result["net_income"] - result["ebitda"]) < 0.01

    def test_salary_counted_in_operating_expenses(self):
        low_sal = _make_single_analyst(salary=50_000.0, tax_rate=0.0)
        high_sal = _make_single_analyst(salary=200_000.0, tax_rate=0.0)
        r_low = calculate_income_statement(low_sal)["ebitda"]
        r_high = calculate_income_statement(high_sal)["ebitda"]
        assert abs(r_low - r_high - 150_000.0) < 0.01


# ── Cashflows & IRR ───────────────────────────────────────────────────────────

class TestCashflows:
    def test_cashflow_length_equals_years_plus_one(self):
        inputs = _make_single_analyst()
        for years in (1, 5, 10):
            result = calculate_income_statement(inputs, years=years)
            assert len(result["cashflows"]) == years + 1, f"Expected {years+1} cashflows for years={years}"

    def test_irr_is_float_not_none(self):
        """IRR should be a float — not None.
        
        If this test fails it almost certainly means np.irr / numpy_financial
        is broken in the current environment.
        """
        inputs = _make_single_analyst(
            billing_rate=200.0,
            utilization=0.8,
            realization=0.9,
            salary=80_000.0,
            tax_rate=0.26,
            equity_investment=500_000.0,  # Negative year-0 cashflow needed for valid IRR
        )
        result = calculate_income_statement(inputs, years=5)
        assert result["irr"] is not None, (
            "IRR returned None. This indicates np.irr is broken in the current "
            "NumPy version (removed in NumPy ≥ 1.20). Fix: use numpy_financial.irr()."
        )
        assert isinstance(result["irr"], float)


# ── Smoke test ────────────────────────────────────────────────────────────────

def test_example_inputs_runs_and_produces_valid_result():
    result = calculate_income_statement(example_inputs())
    assert result["annual_revenue"] > 0
    assert "ebitda" in result
    assert "net_income" in result
    assert "cashflows" in result
    assert len(result["cashflows"]) == 6  # default years=5
