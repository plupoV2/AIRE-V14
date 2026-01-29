# AIRE™ — AI Agent Platform for Commercial Real Estate (PoC)

A minimal, investor-friendly proof-of-concept that:
- Looks like a modern product landing page (top nav + hero)
- Runs an **AI-like property grade** across asset classes (Multifamily, Single Family, Office, Retail, Industrial, Land)
- Produces an **explainable score + letter grade** with a lightweight audit trail (PDF export)

## How the grading works (high level)
This app implements **AIRE Vector Grade™**:
- Blends a **macro prior** (rate environment) with an **asset-type prior** (property-type profile)
- Uses **only the inputs you provide** (weights automatically re-normalize)
- Separates **explainable penalties** (risk flags) from the base score
- Outputs: numeric score, letter grade, recommendation, confidence, and flags

> Note: Naming/structure is designed to support IP discussions. This repo is not legal advice and does not guarantee patentability.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Environment / Streamlit secrets (optional)
Add these in Streamlit secrets (or your environment) to enable data enrichment:
```text
RENTCAST_APIKEY="..."   # comps/AVM (optional)
ESTATED_TOKEN="..."     # last sale (optional)
ATTOM_APIKEY="..."      # last sale (optional)
FRED_API_KEY="..."      # macro pulls (optional)

STRIPE_PAYMENT_LINK_URL="https://buy.stripe.com/..."  # optional
ADMIN_UNLOCK_CODE="choose-a-strong-password"          # optional
```

## What to show investors
1. Open **Product** (landing) → quick narrative
2. Go to **AI Agents** → run grader with partial inputs → instant result
3. Export the PDF → “audit trail” proof-of-concept artifact
