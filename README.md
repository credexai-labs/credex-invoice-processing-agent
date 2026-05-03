# CredexAI Invoice Processing Agent with Provenance

Extracts structured data from invoices (amounts, dates, vendor info, line items), verifies extracted data through the CredexAI 5-verifier Consensus Verification API, and generates provenance certificates for each processed invoice. Designed for enterprise audit trails where data integrity and verification provenance are critical.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  Invoice Processing Agent                        │
├─────────────────────────────────────────────────────────────────┤
│  POST /process                                                  │
│    ├── 1. Extract structured data (OCR/LLM)                     │
│    ├── 2. Cross-field validation (math consistency)             │
│    ├── 3. Verify each field group via CredexAI 5-verifier API   │
│    └── 4. Issue provenance certificate with data hash           │
├─────────────────────────────────────────────────────────────────┤
│  CREDX Transactions:                                            │
│    • 1 CREDX per field group verification                       │
│    • Typical invoice: 4–5 CREDX (header, vendor, buyer,         │
│      amounts, line_items)                                       │
│    • All tx hashes stored in provenance audit trail             │
└─────────────────────────────────────────────────────────────────┘
```

## API Reference

### `POST /process`

Submit an invoice for processing. Returns immediately with a job ID for polling.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `invoice_text` | string | One of text/url | Raw invoice text content (max 50,000 chars) |
| `invoice_url` | string | One of text/url | URL to invoice document (PDF/image) |
| `vendor_name` | string | No | Known vendor name for cross-validation |
| `expected_currency` | string | No | Expected currency code (default: USD) |
| `require_line_items` | boolean | No | Extract individual line items (default: true) |

**Response (202 Accepted):**

```json
{
  "job_id": "uuid",
  "status": "pending",
  "poll_url": "/invoice/{job_id}"
}
```

### `GET /invoice/{job_id}`

Retrieve invoice processing results.

**Response:**

```json
{
  "job_id": "uuid",
  "status": "completed",
  "extracted_data": {
    "invoice_number": "INV-2026-00847",
    "invoice_date": "2026-04-15",
    "due_date": "2026-05-15",
    "vendor_name": "Acme Cloud Services Inc.",
    "total_amount": 4632.50,
    "line_items": [...]
  },
  "verification_details": [
    {
      "field_group": "header",
      "fields_verified": ["invoice_number", "invoice_date", "due_date", "payment_terms"],
      "verification_status": "verified",
      "confidence_score": 0.94,
      "verification_tx_hash": "SIM_NO_XRPL_WALLET_a1b2c3d4"
    },
    ...
  ],
  "overall_confidence": 0.91,
  "total_credx_spent": 5,
  "transaction_hashes": ["SIM_NO_XRPL_WALLET_...", ...],
  "provenance_certificate": {
    "certificate_id": "prov-inv-abc123def456",
    "data_hash": "sha256...",
    "signature": "sha256...",
    ...
  }
}
```

### `GET /health`

Health check for container orchestration.

## Environment Setup

```bash
cp .env.example .env
# Edit .env with your configuration

# Required:
# - PROVENANCE_SIGNING_KEY: Generate with `openssl rand -hex 32`
# - CREDEX_API_KEY: From https://credexai.live/dashboard

# Optional:
# - XRPL_WALLET_SEED: Leave empty for simulation mode
```

## Running Locally

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8009 --reload
```

## Docker

```bash
docker build -t credexai-invoice-processing .
docker run -p 8009:8009 --env-file .env credexai-invoice-processing
```

## Verification Field Groups

Each invoice is verified in logical field groups, with one CREDX transaction per group:

| Group | Fields | Purpose |
|-------|--------|---------|
| `header` | invoice_number, invoice_date, due_date, payment_terms | Document identity |
| `vendor` | vendor_name, vendor_address, vendor_tax_id | Counterparty validation |
| `buyer` | buyer_name, buyer_address | Recipient validation |
| `amounts` | subtotal, tax_amount, total_amount, currency | Financial accuracy |
| `line_items` | All line item descriptions, quantities, prices | Itemized verification |

## Cross-Field Validation

Before consensus verification, the agent performs mathematical consistency checks:

- Line items sum matches subtotal
- Subtotal + tax equals total amount
- Due date is after invoice date
- Tax rates are within reasonable bounds

Validation issues are included in the verification details for transparency.

## Provenance Certificate

Each processed invoice receives a signed provenance certificate containing:

- SHA-256 hash of the extracted data (for integrity verification)
- All CREDX transaction hashes (complete audit trail)
- Verification method and confidence scores
- Timestamp and certificate signature

The certificate can be independently verified by recomputing the data hash and checking the HMAC signature against the configured signing key.

## Transaction Model

Each invoice generates multiple CREDX transactions:

- Typically 4–5 transactions per invoice (one per field group)
- All transaction hashes are stored in the provenance certificate
- Transaction volume scales linearly with invoice complexity

## Integration with Other Agents

- **Delegation Agent**: Can orchestrate this agent for batch invoice processing across multiple vendors
- **DeFi Arbitrage Agent**: P&L from arbitrage operations can be reconciled through invoice processing
- **SEO Content Agent**: Can generate verified financial summaries from processed invoice data

## Simulation Mode

When `XRPL_WALLET_SEED` is not configured, the agent operates in simulation mode:
- Transaction hashes are prefixed with `SIM_NO_XRPL_WALLET_` to clearly indicate they are not real
- Invoice extraction uses template-based output
- No real transactions are submitted to the XRPL

## License

MIT — see [LICENSE](./LICENSE)
