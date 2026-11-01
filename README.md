# LendWise — Borrower Lending Copilot

LendWise is a lending decision-support web application designed to
help borrowers understand loan affordability, compare loan offers,
and identify early signs of financial stress.

## Features

- **Loan Affordability:** Estimate a safe monthly EMI and maximum
  loan amount using conservative income and expense assumptions.
- **Loan Comparison:** Compare loan offers based on EMI, fees,
  estimated effective annual cost, and total repayment.
- **Financial Stress Monitor:** Identify potential warning signs
  such as falling balances, income drops, and rising EMI obligations.
- **Privacy-Focused Processing:** Process bank statement CSV data
  in the browser and send summary features to the backend.
- **Privacy Ledger:** View information shared with the application
  and access available deletion controls.

## Accepted statement formats

CSV, text, PDF (text-based or scanned) and photos/screenshots (PNG/JPG). PDFs are read with pdf.js and
scans/images with Tesseract OCR, both inside your browser (the libraries are downloaded from a CDN on
first use; your file is never uploaded). Amount signs come from how the running balance moves, and the
page reports how many rows agree with the balance so misread numbers are visible. OCR accuracy depends
on image quality; always check the "What was read from your file" preview.

## How It Works

1. The user selects a bank statement CSV.
2. The browser extracts financial summary features.
3. The backend uses these features to estimate affordability
   and financial stress.
4. Users compare loan offers and review the results.
5. The application provides visibility into shared information
   and available deletion controls.


## How the risk score is calculated

No hand-picked weights or point values are used.

- **Score:** the simulated chance (%) that your cash goes below zero at least once in the next
  12 months with your current obligations. It uses your own median income, income volatility,
  EMIs, rent/bills, spending and average balance (fixed random seed, so it is repeatable).
- **Band:** Safe up to 5%, Watch up to 15%, At risk above 15% (`risk_balanced` / `risk_stretch`
  in `backend/config.py`, the same limits used for the safe EMI). Failed payments in the last
  90 days can never be "Safe".
- **Key risk drivers:** each factor (existing EMIs, income volatility, thin cash cushion) is
  removed in turn and the simulation re-run; the drop in risk is reported. Spending-above-income
  is plain arithmetic, and adverse facts seen in the statement are listed with their measured values.
- **Next steps:** the size of each change (EMI cut, extra income, cash cushion, spending cut) is
  solved numerically so the simulated risk falls back to the limit.

Not calibrated to real default data (none is available): the 5%/15% limits and the 3-month
cushion target are adjustable assumptions, not measured facts.

Tests: `python -m pytest tests/`, `node tests/check_features.js` and `node tests/check_statement_text.js`.
`python tests/make_statements.py` writes synthetic test statements to `tests/fixtures/` (for testing only; the app has no built-in demo data and works only on the CSV you upload).

## Technology Stack

- Frontend: HTML, CSS, JavaScript
- Backend: Python, FastAPI
- API Server: Uvicorn
- Data Processing: Pandas, NumPy
- Loan Cost Calculation: SciPy
- Testing: Pytest and JavaScript checks

## Project Structure

```text
lending-copilot/
├── backend/
│   ├── affordability.py
│   ├── compare.py
│   ├── features.py
│   ├── llm.py
│   ├── main.py
│   ├── stress.py
│   └── synth.py
├── data/
├── frontend/
│   ├── features.js
│   └── index.html
├── tests/
├── .gitignore
└── README.md
## Getting Started

### Prerequisites

- Python 3.10 or later
- pip

### Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/jhashivani075-blip/LendWise.git
   cd LendWise
pip install -r backend/requirements.txt
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload --port 8000

**Important:** The last step depends on how your frontend is configured. If your frontend calls the backend API, make sure you open it in a way that allows those API requests to work. We can confirm the correct method by checking your code.

### 2. Running Tests

```markdown
## Running Tests

Run the Python tests:

```bash
python -m pytest tests/
node tests/check_js_parity.js

### 3. Privacy and Limitations

Only include claims that your code actually implements.

```markdown
## Privacy and Limitations

LendWise is a decision-support prototype intended to help users
understand loan affordability and compare loan offers.

Its estimates are illustrative and should not be treated as
financial advice or a guarantee of loan approval.

Review the application's data-processing and deletion behavior
before uploading real financial information.
## Future Improvements

- Improve affordability estimates using more financial scenarios.
- Expand financial stress detection.
- Improve loan comparison and cost transparency.
- Add more testing and validation.
- Enhance accessibility and mobile responsiveness.
