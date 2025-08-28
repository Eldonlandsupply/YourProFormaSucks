"""
Consulting firm financial model.

This module provides functions to compute revenues, costs and cash flows for a
consulting or professional services firm based on the assumptions defined in
`schemas/v1/consulting.json`. It is meant to illustrate how different
staffing mixes, utilization rates and overheads translate into profit and cash
flow. The calculations are simplified and assume constant staffing levels
throughout the model horizon.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Any
import numpy as np


@dataclass
class StaffLevel:
    headcount: int
    billing_rate: float  # $/hour
    salary: float  # $/year
    utilization: float  # fraction of available hours that are billable
    realization: float  # fraction of billed hours collected as revenue


@dataclass
class ConsultingInputs:
    partners: StaffLevel
    managers: StaffLevel
    analysts: StaffLevel
    retainer_fraction: float  # fraction of revenue from retainers
    project_fraction: float  # fraction of revenue from projects
    overhead: Dict[str, float]
    working_capital: Dict[str, float]
    financing: Dict[str, float]
    tax_rate: float


def calculate_income_statement(inputs: ConsultingInputs, years: int = 5) -> Dict[str, Any]:
    """Calculate a simplified income statement for a consulting firm.

    Args:
        inputs: ConsultingInputs object.
        years: Number of years to forecast.

    Returns:
        Dictionary with annual revenues, expenses, EBITDA, net income and IRR.
    """
    available_hours = 52 * 40  # 40h/week for 52 weeks

    # Revenue per year for each staff level
    def revenue_for_level(level: StaffLevel) -> float:
        billable_hours = level.headcount * available_hours * level.utilization
        billed_revenue = billable_hours * level.billing_rate
        collected = billed_revenue * level.realization
        return collected

    annual_revenue = (revenue_for_level(inputs.partners) +
                      revenue_for_level(inputs.managers) +
                      revenue_for_level(inputs.analysts))

    # Allocate between retainer and project revenue if needed
    retainer_rev = annual_revenue * inputs.retainer_fraction
    project_rev = annual_revenue * inputs.project_fraction

    # Expenses: salaries and overhead
    total_salaries = (inputs.partners.headcount * inputs.partners.salary +
                      inputs.managers.headcount * inputs.managers.salary +
                      inputs.analysts.headcount * inputs.analysts.salary)
    overhead_total = sum(inputs.overhead.values())
    operating_expenses = total_salaries + overhead_total

    # Simple tax on earnings before tax
    ebitda = annual_revenue - operating_expenses
    taxable_income = max(0.0, ebitda)
    tax = taxable_income * inputs.tax_rate
    net_income = ebitda - tax

    # Build cashflows for IRR: equity investment at year 0 equals zero (assuming financing covers working capital) and subsequent cash flows equal net income
    cashflows = [-inputs.financing.get("equity_investment", 0.0)]
    for _ in range(years):
        cashflows.append(net_income)

    try:
        irr = np.irr(cashflows)
    except Exception:
        irr = None

    return {
        "annual_revenue": annual_revenue,
        "retainer_revenue": retainer_rev,
        "project_revenue": project_rev,
        "operating_expenses": operating_expenses,
        "ebitda": ebitda,
        "net_income": net_income,
        "irr": irr,
        "cashflows": cashflows
    }


def example_inputs() -> ConsultingInputs:
    """Provide a sample consulting firm input set for demonstration purposes."""
    partners = StaffLevel(headcount=3, billing_rate=350.0, salary=250_000.0, utilization=0.6, realization=0.9)
    managers = StaffLevel(headcount=6, billing_rate=250.0, salary=150_000.0, utilization=0.7, realization=0.9)
    analysts = StaffLevel(headcount=12, billing_rate=150.0, salary=90_000.0, utilization=0.8, realization=0.85)
    overhead = {
        "rent": 300_000.0,
        "software": 100_000.0,
        "marketing": 200_000.0,
        "travel": 150_000.0,
        "admin_salaries": 400_000.0
    }
    working_capital = {
        "wip_days": 30,
        "ar_days": 45,
        "ap_days": 15
    }
    financing = {
        "equity_investment": 1_000_000.0,
        "debt_amount": 0.0,
        "debt_interest_rate": 0.0,
        "debt_term": 0
    }
    return ConsultingInputs(
        partners=partners,
        managers=managers,
        analysts=analysts,
        retainer_fraction=0.6,
        project_fraction=0.4,
        overhead=overhead,
        working_capital=working_capital,
        financing=financing,
        tax_rate=0.26
    )