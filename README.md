# Your Pro Forma Sucks – Extended Templates

This repository contains extended template definitions and simple financial
models for the **Your Pro Forma Sucks** project.  The goal of these
templates is to provide bank‑ready assumptions and computations across a
range of sectors, starting with **utility‑scale solar** and **professional
services/consulting**.  Each template includes a JSON schema describing
inputs, plus a Python model that performs basic cash‑flow analysis.

## Directory Structure

```
your_proforma_sucks/
├── schemas/
│   └── v1/
│       ├── solar.json          # Schema for solar PV projects
│       └── consulting.json     # Schema for consulting firms
└── server/
    └── models/
        ├── solar_model.py      # Solar financial model
        └── consulting_model.py # Consulting financial model
```

### `schemas/v1/solar.json`

This JSON Schema defines all the inputs required to model a utility‑scale
photovoltaic project.  Key sections include:

- **Site**: AC/DC capacity, DC/AC ratio and performance ratio.
- **Resource**: Capacity factor and degradation rate.
- **CapEx**: Cost breakdown for modules, inverters, balance‑of‑system,
  interconnection, land and development, plus contingency.
- **OpEx**: Fixed O&M ($/kW‑yr), insurance and land lease.
- **Revenues**: PPA price and escalator, merchant share and merchant price.
- **Financing**: Debt fraction, interest, tenor and equity return target.
- **Tax**: Corporate tax rate, MACRS class and ITC percentage.
- **Scenarios**: Array of PPA price multipliers for sensitivity analysis.

### `schemas/v1/consulting.json`

Inputs for a consulting or professional services firm are organized into
sections:

- **Staffing**: Headcount, billing rate, salary, utilization and realization
  for partners, managers and analysts.
- **Revenue Mix**: Split between retainer and project work.
- **Overhead**: Non‑labour operating costs (rent, software, marketing,
  travel, admin salaries).
- **Working Capital**: Days for work in process, accounts receivable and
  accounts payable.
- **Financing**: Equity and debt inputs.
- **Tax**: Corporate tax rate.
- **Scenarios**: Array of utilization multipliers for sensitivity analysis.

### `server/models/solar_model.py`

Contains a dataclass (`SolarInputs`) representing solar assumptions and a
`calculate_cashflows` function which:

1. Converts capacity and capacity factor into an annual energy forecast,
   accounting for degradation.
2. Calculates revenue from PPA and merchant energy, including price
   escalation.
3. Estimates fixed O&M costs.
4. Computes total CapEx, applies ITC and calculates debt/equity split.
5. Builds a simplified cash‑flow table including debt amortization, tax and
   depreciation and returns the equity IRR using NumPy’s internal IRR
   function.

An `example_inputs` helper returns a reasonable set of default inputs for
testing and demonstration.

### `server/models/consulting_model.py`

Defines dataclasses (`StaffLevel` and `ConsultingInputs`) and a
`calculate_income_statement` function that:

1. Computes annual billable revenue per staff level based on headcount,
   utilization and realization.
2. Allocates revenue between retainer and project work.
3. Sums salaries and overhead expenses to derive EBITDA.
4. Applies corporate tax and calculates net income.
5. Constructs a simple cash‑flow series for IRR calculation.

An `example_inputs` helper produces sample data for quick testing.

## Usage

These schemas and models are designed to be integrated into the web app
built by the Lindy app builder.  When adding a new project within the app,
the corresponding schema should be presented via a wizard‑style form.  The
submitted inputs can then be passed into the Python model to compute
cash flows, IRR and other key metrics on the backend.  Outputs can be
displayed in dashboards, exported to Excel or PDF, and used to power AI
commentary and roast features.

Please note that these models are simplified and meant for demonstration
purposes.  Users should review and customize assumptions to match their
specific project or firm.