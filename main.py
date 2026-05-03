"""
CredexAI Invoice Processing Agent with Provenance

Extracts data from invoices (amounts, dates, vendor info, line items), verifies
extracted data through the CredexAI 5-verifier Consensus Verification API, and
generates provenance certificates for each processed invoice. Designed for
enterprise audit trails.

Architecture:
    - Async pipeline with fire-and-forget job submission
    - In-memory job storage for demo mode
    - Multi-step extraction → cross-field validation → consensus verification
    - Multiple CREDX transactions per invoice (one per verified field group)

Related agents:
    - The Delegation Agent can orchestrate this agent for batch invoice processing
    - The DeFi Arbitrage Agent can track P&L that feeds into invoice reconciliation
    - The SEO Content Agent can generate verified financial summaries from invoice data
"""

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CREDEXAI_API_URL = os.getenv("CREDEXAI_API_URL", "https://api.credexai.live")
CREDEXAI_API_KEY = os.getenv("CREDEXAI_API_KEY", "")
XRPL_NODE_URL = os.getenv("XRPL_NODE_URL", "https://s1.ripple.com:51234")
XRPL_WALLET_SEED = os.getenv("XRPL_WALLET_SEED", "")
PROVENANCE_SIGNING_KEY = os.getenv("PROVENANCE_SIGNING_KEY", "")

if not PROVENANCE_SIGNING_KEY:
    raise ValueError(
        "PROVENANCE_SIGNING_KEY environment variable is required. "
        "Generate one with: openssl rand -hex 32"
    )

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CredexAI Invoice Processing Agent",
    description=(
        "Extracts invoice data, verifies it through the CredexAI 5-verifier "
        "Consensus Verification API, and generates provenance certificates "
        "for enterprise audit trails."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Validate critical configuration at startup
if not CREDEXAI_API_KEY:
    import warnings
    warnings.warn(
        "CREDEXAI_API_KEY is not set. Verification calls will fail. "
        "Get your key at https://credexai.live/dashboard",
        stacklevel=2,
    )

# ---------------------------------------------------------------------------
# In-memory job storage (Demo mode: use Redis/PostgreSQL in production deployments)
# ---------------------------------------------------------------------------

jobs: dict = {}

# ---------------------------------------------------------------------------
# Enums & Schemas
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    VALIDATING = "validating"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"


class LineItem(BaseModel):
    """A single line item from an invoice."""

    description: str = Field(..., min_length=1, max_length=500)
    quantity: float = Field(..., ge=0)
    unit_price: float = Field(..., ge=0)
    total: float = Field(..., ge=0)
    tax_rate: Optional[float] = Field(None, ge=0, le=100)


class InvoiceSubmission(BaseModel):
    """Request to process an invoice."""

    invoice_text: Optional[str] = Field(
        None, max_length=50000, description="Raw invoice text content"
    )
    invoice_url: Optional[str] = Field(
        None, max_length=2000, description="URL to invoice document (PDF/image)"
    )
    vendor_name: Optional[str] = Field(
        None, max_length=200, description="Known vendor name for cross-validation"
    )
    expected_currency: str = Field(
        default="USD", min_length=3, max_length=3, description="Expected currency code"
    )
    require_line_items: bool = Field(
        default=True, description="Whether to extract individual line items"
    )


class ExtractedInvoiceData(BaseModel):
    """Structured data extracted from an invoice."""

    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_address: Optional[str] = None
    vendor_tax_id: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_address: Optional[str] = None
    currency: str = "USD"
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    total_amount: Optional[float] = None
    line_items: list[LineItem] = []
    payment_terms: Optional[str] = None
    notes: Optional[str] = None


class VerificationDetail(BaseModel):
    """Verification result for a specific field group."""

    field_group: str
    fields_verified: list[str]
    verification_status: str
    confidence_score: float
    verification_tx_hash: str
    issues: list[str] = []


class InvoiceResponse(BaseModel):
    """Response for an invoice processing job."""

    job_id: str
    status: JobStatus
    submitted_at: str
    completed_at: Optional[str] = None
    extracted_data: Optional[ExtractedInvoiceData] = None
    verification_details: list[VerificationDetail] = []
    overall_confidence: float = 0.0
    total_credx_spent: int = 0
    transaction_hashes: list[str] = []
    provenance_certificate: Optional[dict] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# XRPL Transaction Helper
# ---------------------------------------------------------------------------


def generate_xrpl_tx_hash(memo: str) -> str:
    """
    Generate an XRPL transaction hash.

    Demo mode: When XRPL_WALLET_SEED is not configured, returns an obviously
    fake hash prefixed with SIM_NO_XRPL_WALLET_ to indicate simulation mode.
    """
    if not XRPL_WALLET_SEED:
        short_id = uuid.uuid4().hex[:8]
        return f"SIM_NO_XRPL_WALLET_{short_id}"
    # Demo mode: In a real deployment, this would sign and submit via xrpl-py
    tx_blob = hashlib.sha256(f"{memo}:{uuid.uuid4().hex}".encode()).hexdigest().upper()
    return tx_blob


# ---------------------------------------------------------------------------
# Invoice Data Extraction
# ---------------------------------------------------------------------------


async def extract_invoice_data(submission: InvoiceSubmission) -> ExtractedInvoiceData:
    """
    Extract structured data from invoice text or document.

    Demo mode: Returns simulated extraction results. In a real deployment,
    this would use OCR (Tesseract/AWS Textract) for images/PDFs and GPT-4.1-mini
    for structured data extraction from text.
    """
    # Demo mode: Simulated extraction based on input
    vendor = submission.vendor_name or "Acme Cloud Services Inc."

    extracted = ExtractedInvoiceData(
        invoice_number="INV-2026-00847",
        invoice_date="2026-04-15",
        due_date="2026-05-15",
        vendor_name=vendor,
        vendor_address="123 Technology Drive, San Francisco, CA 94105",
        vendor_tax_id="US-EIN-94-3201678",
        buyer_name="CredexAI Labs",
        buyer_address="456 Innovation Blvd, Austin, TX 78701",
        currency=submission.expected_currency,
        subtotal=4250.00,
        tax_amount=382.50,
        total_amount=4632.50,
        payment_terms="Net 30",
        notes="Thank you for your business.",
    )

    if submission.require_line_items:
        extracted.line_items = [
            LineItem(
                description="Cloud Infrastructure (GPU Instances) — April 2026",
                quantity=1,
                unit_price=2500.00,
                total=2500.00,
                tax_rate=9.0,
            ),
            LineItem(
                description="API Gateway — 1.2M requests",
                quantity=1200000,
                unit_price=0.001,
                total=1200.00,
                tax_rate=9.0,
            ),
            LineItem(
                description="Data Storage — 500GB",
                quantity=500,
                unit_price=1.10,
                total=550.00,
                tax_rate=9.0,
            ),
        ]

    return extracted


# ---------------------------------------------------------------------------
# Cross-Field Validation
# ---------------------------------------------------------------------------


def validate_extracted_data(data: ExtractedInvoiceData) -> list[str]:
    """
    Perform cross-field validation on extracted invoice data.

    Checks mathematical consistency (line items sum to subtotal, tax calculations,
    subtotal + tax = total) and flags discrepancies.
    """
    issues = []

    # Validate line items sum to subtotal
    if data.line_items and data.subtotal is not None:
        line_items_total = sum(item.total for item in data.line_items)
        if abs(line_items_total - data.subtotal) > 0.01:
            issues.append(
                f"Line items total ({line_items_total:.2f}) does not match "
                f"subtotal ({data.subtotal:.2f})"
            )

    # Validate subtotal + tax = total
    if data.subtotal is not None and data.tax_amount is not None and data.total_amount is not None:
        expected_total = data.subtotal + data.tax_amount
        if abs(expected_total - data.total_amount) > 0.01:
            issues.append(
                f"Subtotal ({data.subtotal:.2f}) + tax ({data.tax_amount:.2f}) = "
                f"{expected_total:.2f}, but total is {data.total_amount:.2f}"
            )

    # Validate dates
    if data.invoice_date and data.due_date:
        try:
            inv_date = datetime.fromisoformat(data.invoice_date)
            due_date = datetime.fromisoformat(data.due_date)
            if due_date < inv_date:
                issues.append("Due date is before invoice date")
        except ValueError:
            issues.append("Invalid date format detected")

    return issues


# ---------------------------------------------------------------------------
# CredexAI Consensus Verification (5 independent GPT-4.1-mini verifiers)
# ---------------------------------------------------------------------------


async def verify_field_group(field_group: str, fields: dict, context: dict) -> dict:
    """
    Submit a field group to the CredexAI 5-verifier Consensus Verification
    API. Each verification uses 5 independent GPT-4.1-mini verifiers and
    costs 1 CREDX transaction.

    Field groups:
        - header: invoice number, dates, payment terms
        - vendor: vendor name, address, tax ID
        - amounts: subtotal, tax, total, line items
        - buyer: buyer name, address
    """
    # Skip verification of placeholder text or empty fields
    non_empty_fields = {k: v for k, v in fields.items() if v is not None and v != ""}
    if not non_empty_fields:
        return {
            "status": "FAILED",
            "confidence_score": 0.0,
            "verification_tx_hash": "",
            "error": "No non-empty fields to verify",
        }

    verification_payload = {
        "claim": (
            f"Invoice field group '{field_group}' contains the following "
            f"extracted values: {json.dumps(non_empty_fields)}"
        ),
        "context": {
            "domain": "invoice_processing",
            "field_group": field_group,
            "invoice_context": context,
        },
        "verification_type": "data_extraction_consensus",
    }

    # Generate CREDX payment transaction for this verification
    verification_tx_hash = generate_xrpl_tx_hash(
        f"credx_invoice_verify:{field_group}:{uuid.uuid4().hex[:8]}"
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{CREDEXAI_API_URL}/v1/verify",
                json=verification_payload,
                headers={"Authorization": f"Bearer {CREDEXAI_API_KEY}"},
            )
            if response.status_code == 200:
                result = response.json()
                return {
                    "status": "verified" if result.get("consensus", False) else "FAILED",
                    "confidence_score": result.get("confidence_score", 0.0),
                    "verification_tx_hash": verification_tx_hash,
                }
            else:
                return {
                    "status": "FAILED",
                    "confidence_score": 0.0,
                    "verification_tx_hash": verification_tx_hash,
                    "error": f"API returned {response.status_code}",
                }
    except Exception as e:
        return {
            "status": "FAILED",
            "confidence_score": 0.0,
            "verification_tx_hash": verification_tx_hash,
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Provenance Certificate
# ---------------------------------------------------------------------------


def generate_provenance_certificate(
    job_id: str,
    extracted_data: ExtractedInvoiceData,
    verification_details: list,
    tx_hashes: list,
) -> dict:
    """Generate a signed provenance certificate for the processed invoice."""
    # Create a deterministic hash of the extracted data
    data_hash = hashlib.sha256(
        json.dumps(extracted_data.model_dump(), sort_keys=True, default=str).encode()
    ).hexdigest()

    certificate_data = {
        "certificate_id": f"prov-inv-{uuid.uuid4().hex[:12]}",
        "job_id": job_id,
        "agent": "invoice_processing_agent",
        "platform": "credexai.live",
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "invoice_number": extracted_data.invoice_number,
        "data_hash": data_hash,
        "verification_method": "5-verifier consensus (5 independent GPT-4.1-mini verifiers)",
        "field_groups_verified": len(verification_details),
        "overall_confidence": (
            sum(v.get("confidence_score", 0) if isinstance(v, dict) else v.confidence_score
                for v in verification_details) / max(len(verification_details), 1)
        ),
        "transaction_hashes": tx_hashes,
        "audit_trail": {
            "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
            "verification_count": len(verification_details),
            "data_integrity_hash": data_hash,
        },
    }
    # Sign the certificate
    payload_bytes = json.dumps(certificate_data, sort_keys=True).encode()
    signature = hashlib.sha256(
        payload_bytes + PROVENANCE_SIGNING_KEY.encode()
    ).hexdigest()
    certificate_data["signature"] = signature
    return certificate_data


# ---------------------------------------------------------------------------
# Background Pipeline
# ---------------------------------------------------------------------------


async def run_invoice_pipeline(job_id: str, submission: InvoiceSubmission):
    """
    Async pipeline for invoice processing:
    1. Extract structured data from invoice
    2. Cross-field validation (mathematical consistency)
    3. Verify each field group via CredexAI 5-verifier consensus (1 CREDX each)
    4. Generate provenance certificate for audit trail
    """
    job = jobs[job_id]
    all_tx_hashes: list[str] = []
    credx_spent = 0

    try:
        # Phase 1: Extract invoice data
        job["status"] = JobStatus.EXTRACTING
        extracted_data = await extract_invoice_data(submission)
        job["extracted_data"] = extracted_data.model_dump()

        # Phase 2: Cross-field validation
        job["status"] = JobStatus.VALIDATING
        validation_issues = validate_extracted_data(extracted_data)

        # Phase 3: Verify field groups (1 CREDX per group)
        job["status"] = JobStatus.VERIFYING
        verification_details = []

        # Define field groups for verification
        field_groups = {
            "header": {
                "invoice_number": extracted_data.invoice_number,
                "invoice_date": extracted_data.invoice_date,
                "due_date": extracted_data.due_date,
                "payment_terms": extracted_data.payment_terms,
            },
            "vendor": {
                "vendor_name": extracted_data.vendor_name,
                "vendor_address": extracted_data.vendor_address,
                "vendor_tax_id": extracted_data.vendor_tax_id,
            },
            "buyer": {
                "buyer_name": extracted_data.buyer_name,
                "buyer_address": extracted_data.buyer_address,
            },
            "amounts": {
                "subtotal": extracted_data.subtotal,
                "tax_amount": extracted_data.tax_amount,
                "total_amount": extracted_data.total_amount,
                "currency": extracted_data.currency,
                "line_items_count": len(extracted_data.line_items),
            },
        }

        # Add line items as a separate verification group if present
        if extracted_data.line_items:
            field_groups["line_items"] = {
                "items": [item.model_dump() for item in extracted_data.line_items],
                "computed_total": sum(item.total for item in extracted_data.line_items),
            }

        context = {
            "invoice_number": extracted_data.invoice_number,
            "vendor": extracted_data.vendor_name,
            "total": extracted_data.total_amount,
        }

        for group_name, fields in field_groups.items():
            result = await verify_field_group(group_name, fields, context)
            credx_spent += 1

            if result["verification_tx_hash"]:
                all_tx_hashes.append(result["verification_tx_hash"])

            detail = VerificationDetail(
                field_group=group_name,
                fields_verified=list(fields.keys()) if isinstance(fields, dict) else [],
                verification_status=result["status"],
                confidence_score=result.get("confidence_score", 0.0),
                verification_tx_hash=result["verification_tx_hash"],
                issues=[i for i in validation_issues if group_name in i.lower()] if validation_issues else [],
            )
            verification_details.append(detail)

        # Phase 4: Generate provenance certificate
        overall_confidence = (
            sum(d.confidence_score for d in verification_details)
            / max(len(verification_details), 1)
        )

        provenance_cert = generate_provenance_certificate(
            job_id, extracted_data, verification_details, all_tx_hashes
        )

        job["status"] = JobStatus.COMPLETED
        job["completed_at"] = datetime.now(timezone.utc).isoformat()
        job["verification_details"] = [d.model_dump() for d in verification_details]
        job["overall_confidence"] = overall_confidence
        job["total_credx_spent"] = credx_spent
        job["transaction_hashes"] = all_tx_hashes
        job["provenance_certificate"] = provenance_cert

    except Exception as e:
        job["status"] = JobStatus.FAILED
        job["error"] = str(e)
        job["completed_at"] = datetime.now(timezone.utc).isoformat()
        job["transaction_hashes"] = all_tx_hashes


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------


@app.post("/process", response_model=dict, status_code=202)
async def submit_invoice(
    submission: InvoiceSubmission, background_tasks: BackgroundTasks
):
    """
    Submit an invoice for processing. The pipeline runs asynchronously —
    poll the /invoice/{job_id} endpoint for results.

    Each field group is verified through the CredexAI 5-verifier Consensus
    Verification API (1 CREDX per field group, typically 4–5 per invoice).
    """
    if not submission.invoice_text and not submission.invoice_url:
        raise HTTPException(
            status_code=422,
            detail="Either invoice_text or invoice_url must be provided",
        )

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "job_id": job_id,
        "status": JobStatus.PENDING,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "extracted_data": None,
        "verification_details": [],
        "overall_confidence": 0.0,
        "total_credx_spent": 0,
        "transaction_hashes": [],
        "provenance_certificate": None,
        "error": None,
    }
    background_tasks.add_task(run_invoice_pipeline, job_id, submission)
    return {"job_id": job_id, "status": "pending", "poll_url": f"/invoice/{job_id}"}


@app.get("/invoice/{job_id}", response_model=InvoiceResponse)
async def get_invoice_result(job_id: str):
    """Retrieve the status and results of an invoice processing job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return InvoiceResponse(**jobs[job_id])


@app.get("/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    return {
        "status": "healthy",
        "agent": "invoice_processing_agent",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/")
async def root():
    """Agent information and capabilities."""
    return {
        "agent": "CredexAI Invoice Processing Agent",
        "version": "1.0.0",
        "platform": "credexai.live",
        "description": (
            "Extracts invoice data, verifies it through the CredexAI 5-verifier "
            "Consensus Verification API, and generates provenance certificates "
            "for enterprise audit trails."
        ),
        "endpoints": {
            "POST /process": "Submit invoice for processing",
            "GET /invoice/{job_id}": "Get processing results",
            "GET /health": "Health check",
        },
        "verification": "5 independent GPT-4.1-mini verifiers per field group",
        "cost": "1 CREDX per field group verification (typically 4-5 per invoice)",
    }
