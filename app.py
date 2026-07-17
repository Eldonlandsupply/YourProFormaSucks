"""
Main FastAPI application for Your Proforma Sucks.

This module exposes a minimal set of endpoints that together form a
workable MVP for the YourProformaSucks.com service.  The goal of
this application is to give entrepreneurs a simple way to generate
financial projections ("pro formas"), export them to common formats,
store and recall them, and solicit AI‑driven feedback via the
``/roast`` endpoint.  It also serves a few simple HTML pages (the
marketing landing page, a dashboard and a basic auth page) so the
service can be deployed as a self‑contained web app without
depending on a separate frontend.

The code here is intentionally lightweight; database functions are
abstracted into ``database.py``, and the AI helper for roasting
models lives in ``agent.py``.  You can extend or replace those
modules without having to touch most of the routing logic defined
below.  For example, to add new endpoints or integrate with Stripe
checkout, you could drop the appropriate business logic into a
function and call it from within the route handler.

Usage:

    uvicorn your_proforma_sucks.app:app --host 0.0.0.0 --port 8000

"""

import io
import os
import re
from contextlib import asynccontextmanager
from typing import Optional

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

import agent
import database

###############################################################################
# Models
###############################################################################

class ProFormaInput(BaseModel):
    """Input schema for generating a new pro forma.

    Fields here should match the parameters your business logic uses to
    create a projection.  For the MVP we assume a very simple model
    driven by a monthly revenue figure, an expected growth rate,
    customer acquisition cost (CAC) and gross margin percentage.  Feel
    free to add additional parameters (e.g. churn rate, burn rate,
    funding injections) as your needs evolve.
    """

    monthly_revenue: float = Field(ge=0)
    growth_rate: float = Field(default=0.05, ge=-1, le=1)
    cac: float = Field(default=100.0, ge=0)
    gross_margin: float = Field(default=0.75, ge=0, le=1)

class RoastRequest(BaseModel):
    """Request body for the /roast endpoint."""
    summary: Optional[str] = None
    model_id: Optional[str] = None

class RegistrationRequest(BaseModel):
    """Request body for user registration."""
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    """Request body for login, including credentials from legacy releases."""
    username: str
    password: str


_BEARER_AUTHORIZATION = re.compile(r"(?i:bearer) ([A-Za-z0-9_-]{43})")


def require_user(
    authorization: Optional[list[str]] = Header(default=None),
) -> str:
    """Resolve a Bearer token to a user or reject the request."""
    if authorization is None or len(authorization) != 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    match = _BEARER_AUTHORIZATION.fullmatch(authorization[0])
    if match is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    username = database.resolve_session(match.group(1))
    if username is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")
    return username

###############################################################################
# Utility functions
###############################################################################

def create_projection(inputs: ProFormaInput) -> pd.DataFrame:
    """Create a very simple projection DataFrame from user inputs.

    The projection covers 12 months, applying a constant growth rate to
    the monthly revenue.  Gross margin is applied to compute gross
    profit, and CAC is aggregated separately for demonstration
    purposes.  In a real model you'd have more sophisticated logic.
    """
    months = list(range(1, 13))
    revenue = []
    current = inputs.monthly_revenue
    for _ in months:
        revenue.append(current)
        current *= 1 + inputs.growth_rate
    gross_profit = [rev * inputs.gross_margin for rev in revenue]
    cac_total = [inputs.cac] * len(months)
    df = pd.DataFrame({
        "month": months,
        "revenue": revenue,
        "gross_profit": gross_profit,
        "cac": cac_total,
    })
    return df

def ensure_templates_loaded() -> None:
    """Ensure that the templates folder exists and contains basic files.

    If the expected HTML files don't exist (for example, when running
    locally from a fresh checkout), we create minimal placeholder
    versions so that the /marketing, /auth and /dashboard pages don't
    raise 404 errors.  These placeholders can be replaced with real
    designs as soon as they are available.
    """
    tpl_dir = os.path.join(os.path.dirname(__file__), "templates")
    os.makedirs(tpl_dir, exist_ok=True)
    placeholders = {
        "marketing.html": "<h1>Welcome to YourProformaSucks</h1>\n<p>This is a placeholder marketing page.</p>",
        "auth.html": "<h1>Login or Register</h1>\n<p>This is a placeholder authentication page.</p>",
        "dashboard.html": "<h1>Your Dashboard</h1>\n<p>This is a placeholder dashboard page.</p>"
    }
    for name, content in placeholders.items():
        path = os.path.join(tpl_dir, name)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)

###############################################################################
# Route handlers
###############################################################################

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialise local resources for the application lifecycle."""
    database.init_db()
    ensure_templates_loaded()
    yield


app = FastAPI(title="Your Proforma Sucks API", version="0.1.0", lifespan=lifespan)


@app.get("/marketing", response_class=HTMLResponse)
async def marketing_page() -> str:
    """Serve the marketing landing page."""
    tpl_path = os.path.join(os.path.dirname(__file__), "templates", "marketing.html")
    with open(tpl_path, "r", encoding="utf-8") as fh:
        return fh.read()


@app.get("/auth", response_class=HTMLResponse)
async def auth_page() -> str:
    """Serve the login/registration page."""
    tpl_path = os.path.join(os.path.dirname(__file__), "templates", "auth.html")
    with open(tpl_path, "r", encoding="utf-8") as fh:
        return fh.read()


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(user: Optional[str] = None) -> str:
    """Serve the user dashboard page.

    In a real application you'd authenticate the request and use the
    ``user`` parameter or session information to display saved models.
    For the MVP we simply return a static page.
    """
    tpl_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    with open(tpl_path, "r", encoding="utf-8") as fh:
        return fh.read()


@app.post("/register")
async def register(request: RegistrationRequest) -> JSONResponse:
    """Register a new user in the database."""
    success = database.create_user(request.username, request.password)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already exists")
    return JSONResponse({"message": "User registered successfully"})


@app.post("/login")
async def login(request: LoginRequest) -> JSONResponse:
    """Authenticate a user and return a short-lived opaque session token."""
    if not database.authenticate_user(request.username, request.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = database.create_session(request.username)
    return JSONResponse({"token": token})


@app.post("/generate")
async def generate_proforma(inputs: ProFormaInput, user: str = Depends(require_user)) -> JSONResponse:
    """Generate a simple pro forma and persist it.

    Returns a model identifier that can be used to fetch the model
    later or request a roast.  The DataFrame is stored in the
    database as a binary blob (in CSV format) for simplicity.
    """
    df = create_projection(inputs)
    model_id = database.save_model(user, df)
    return JSONResponse({"model_id": model_id, "message": "Model generated successfully"})


@app.get("/export/xlsx/{model_id}")
async def export_xlsx(model_id: str, user: str = Depends(require_user)) -> StreamingResponse:
    """Export a saved model to XLSX and return it as a download."""
    df = database.load_model(model_id, user)
    if df is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    # Write DataFrame to Excel in memory
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="ProForma")
    out.seek(0)
    filename = f"proforma_{model_id}.xlsx"
    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/export/pdf/{model_id}")
async def export_pdf(model_id: str, user: str = Depends(require_user)) -> StreamingResponse:
    """Export a saved model to PDF and return it as a download.

    For the MVP we generate a very simple PDF by converting the
    DataFrame to an HTML table and then to PDF using PyMuPDF.  This
    produces a flat document without charts or styling.  You can
    enhance this function later to use reportlab or WeasyPrint for
    richer output.
    """
    df = database.load_model(model_id, user)
    if df is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    import fitz  # PyMuPDF
    # Create a simple HTML representation
    html_table = df.to_html(index=False)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    text = f"<h1>Pro Forma {model_id}</h1>" + html_table
    page.insert_html(text)
    pdf_bytes = doc.write()
    doc.close()
    filename = f"proforma_{model_id}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/roast")
async def roast(request: RoastRequest, user: str = Depends(require_user)) -> JSONResponse:
    """Send a pro forma or summary to the AI agent and return the critique."""
    summary = request.summary
    if request.model_id:
        df = database.load_model(request.model_id, user)
        if df is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
        # Derive a textual summary from the DataFrame (very naive)
        total_revenue = df["revenue"].sum()
        summary = summary or f"A 12‑month projection with total revenue of ${total_revenue:,.0f}."
    if not summary:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Summary or model_id required")
    critique = agent.roast(summary)
    return JSONResponse({"critique": critique})


@app.post("/partner-request")
async def partner_request(name: str, email: str, message: str) -> JSONResponse:
    """Store an accelerator/agency/VC inquiry in the database."""
    database.save_partner_request(name, email, message)
    return JSONResponse({"message": "Partner request submitted"})
