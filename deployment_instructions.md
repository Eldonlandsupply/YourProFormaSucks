# Deployment Instructions for YourProformaSucks

These instructions outline how to run the MVP contained in this
repository.  They assume you have Python 3.9+ installed along with
pip.  The application is built with FastAPI and uses SQLite for
persistence.

## 1. Installation

Install the required dependencies into a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn pandas xlsxwriter PyMuPDF
```

## 2. Running the server

From the root of the project run:

```bash
uvicorn your_proforma_sucks.app:app --host 0.0.0.0 --port 8000
```

The server will start and expose endpoints for generating pro formas,
exporting them, authenticating users and requesting an AI‑powered
"roast" of a summary.

## 3. Configuring the AI agent

To enable the `/roast` endpoint to call Google's Gemini API you must
set the `GEMINI_API_KEY` environment variable before starting
Uvicorn.  Without this key the endpoint will return a mock response.

```
export GEMINI_API_KEY=your-api-key
```

## 4. Environment variables for Stripe

While the MVP does not include payment processing, you can set
variables for Stripe in anticipation of integrating checkout flows:

```
export STRIPE_API_KEY=sk_test_...
export STRIPE_PRICE_FREE=price_...
export STRIPE_PRICE_TEMPLATE=price_...
export STRIPE_PRICE_SAAS=price_...
export STRIPE_SUCCESS_URL=https://yourproformasucks.com/success
export STRIPE_CANCEL_URL=https://yourproformasucks.com/cancel
```

These values are currently unused but provide a starting point for
connecting the app to Stripe.