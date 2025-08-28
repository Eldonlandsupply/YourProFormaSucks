"""
Solar project financial model.

This module contains helper functions to compute basic financial outputs for a
utility‑scale solar PV project based on the assumption schema defined in
`schemas/v1/solar.json`. It is not intended to replace a full
project‑finance model, but rather to provide reasonable first‑order
calculations that can be surfaced in the web app.

The core entry point is ``calculate_cashflows`` which accepts a dictionary of
inputs matching the schema and returns a dictionary with annual cash flows,
IRR and other KPIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Any
import numpy as np


@dataclass
class SolarInputs:
    ac_mw: float
    dc_mw: float
    capacity_factor: float
    degradation: float
    fixed_om_per_kw: float
    insurance_per_kw: float
    ppa_price: float
    ppa_escalator: float
    merchant_percentage: float
    merchant_price: float
    debt_fraction: float
    debt_interest_rate: float
    debt_tenor_years: int
    equity_return_target: float
    tax_rate: float
    itc_percent: float
    module_cost_per_kw: float
    inverter_cost_per_kw: float
    bos_cost_per_kw: float
    interconnect_cost: float
    land_cost: float
    development_cost: float
    contingency_percent: float


def calculate_cashflows(inputs: SolarInputs, years: int = 30) -> Dict[str, Any]:
    """Calculate annual cash flows for a solar project.

    Args:
        inputs: SolarInputs dataclass with required fields.
        years: Project life in years (default 30).

    Returns:
        Dictionary containing cashflow table and summary metrics.
    """
    # Capacity and production
    ac_kw = inputs.ac_mw * 1_000
    annual_production_mwh = []
    for year in range(years):
        # degrade energy each year
        effective_cf = inputs.capacity_factor * ((1 - inputs.degradation) ** year)
        energy = ac_kw * effective_cf * 8760 / 1000  # MWh
        annual_production_mwh.append(energy)

    # Revenue
    annual_revenue = []
    ppa_price = inputs.ppa_price
    for year, energy in enumerate(annual_production_mwh):
        ppa_energy = energy * (1 - inputs.merchant_percentage)
        merchant_energy = energy * inputs.merchant_percentage
        revenue = (ppa_energy * ppa_price) + (merchant_energy * inputs.merchant_price)
        annual_revenue.append(revenue)
        ppa_price *= 1 + inputs.ppa_escalator  # Escalate PPA each year

    # O&M
    annual_om_cost = ac_kw * (inputs.fixed_om_per_kw + inputs.insurance_per_kw) / 1000  # kW to MW
    opex = [annual_om_cost for _ in range(years)]

    # CapEx
    base_capex_per_kw = inputs.module_cost_per_kw + inputs.inverter_cost_per_kw + inputs.bos_cost_per_kw
    total_capex = (inputs.dc_mw * 1_000 * base_capex_per_kw) + inputs.interconnect_cost + inputs.land_cost + inputs.development_cost
    total_capex *= 1 + inputs.contingency_percent
    # Apply ITC (reduce capex by ITC percent of eligible basis)
    itc_value = total_capex * inputs.itc_percent
    net_capex = total_capex - itc_value

    # Financing: simple assumption – debt draws at COD and interest paid annually on outstanding balance.
    debt_amount = net_capex * inputs.debt_fraction
    equity_amount = net_capex - debt_amount
    # Debt amortization – simple mortgage style payment with equal annual payments over tenor
    if inputs.debt_fraction > 0:
        rate = inputs.debt_interest_rate
        n = inputs.debt_tenor_years
        annuity_factor = (rate * (1 + rate) ** n) / ((1 + rate) ** n - 1)
        annual_debt_payment = debt_amount * annuity_factor
    else:
        annual_debt_payment = 0.0

    # Cashflows: year 0 negative equity investment followed by yearly equity cashflows
    cashflows: List[float] = [-equity_amount]
    debt_balance = debt_amount
    for year in range(years):
        # Revenue minus O&M
        ebitda = annual_revenue[year] - opex[year]
        # Depreciation – simplified straight line over 5 years on net capex
        depreciation = net_capex / 5 if year < 5 else 0.0
        # Interest expense on outstanding debt
        interest = debt_balance * inputs.debt_interest_rate
        # Principal payment if within tenor
        principal = annual_debt_payment - interest if year < inputs.debt_tenor_years else 0.0
        # Adjust debt balance
        debt_balance = max(0.0, debt_balance - principal)
        taxable_income = max(0.0, ebitda - depreciation - (annual_debt_payment - interest))
        tax = taxable_income * inputs.tax_rate
        net_income = ebitda - tax - (annual_debt_payment - interest)
        cashflow_to_equity = net_income
        cashflows.append(cashflow_to_equity)
    # Calculate equity IRR using numpy's irr function
    try:
        irr = float(np.irr(cashflows))  # may return np.nan
    except Exception:
        irr = None
    return {
        "cashflows": cashflows,
        "irr": irr,
        "capex": net_capex,
        "debt_amount": debt_amount,
        "equity_amount": equity_amount
    }


def example_inputs() -> SolarInputs:
    """Return a set of reasonable default inputs for demonstration."""
    return SolarInputs(
        ac_mw=100,
        dc_mw=130,
        capacity_factor=0.25,
        degradation=0.005,
        fixed_om_per_kw=23.0,
        insurance_per_kw=2.0,
        ppa_price=30.0,
        ppa_escalator=0.02,
        merchant_percentage=0.1,
        merchant_price=40.0,
        debt_fraction=0.6,
        debt_interest_rate=0.05,
        debt_tenor_years=18,
        equity_return_target=0.12,
        tax_rate=0.26,
        itc_percent=0.30,
        module_cost_per_kw=350.0,
        inverter_cost_per_kw=60.0,
        bos_cost_per_kw=200.0,
        interconnect_cost=5_000_000,
        land_cost=1_500_000,
        development_cost=3_000_000,
        contingency_percent=0.08
    )