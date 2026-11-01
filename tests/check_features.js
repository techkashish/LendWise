// Run from the project root:  node tests/check_features.js
const assert = require("assert");
const { extractFeatures, normalizeRows, parseNum, parseDate } = require("../frontend/features.js");

assert.strictEqual(parseNum("1,23,456.50"), 123456.5);
assert.strictEqual(parseNum("(2,000)"), -2000);
assert.strictEqual(parseNum("5,000.00 Dr"), -5000);
assert.strictEqual(parseDate("05/10/2026"), "2026-10-05");
assert.strictEqual(parseDate("05-Oct-2026"), "2026-10-05");
assert.strictEqual(parseDate("31/02/2026"), null);

// debit/credit columns, Indian number format, newest-first
const { rows } = normalizeRows([
  { "Txn Date": "05/10/2026", Narration: "EMI HDFC", "Withdrawal Amt.": "8,000.00", "Deposit Amt.": "", "Closing Balance": "1,00,000.00" },
  { "Txn Date": "01/10/2026", Narration: "SALARY", "Withdrawal Amt.": "", "Deposit Amt.": "80,000.00", "Closing Balance": "1,08,000.00" },
]);
assert.deepStrictEqual(rows.map(r => [r.date, r.amount, r.balance]), [["2026-10-01", 80000, 108000], ["2026-10-05", -8000, 100000]]);
assert.throws(() => normalizeRows([{ date: "2026-01-01", description: "x", amount: 1 }]), /balance/);

// a one-month statement must not produce NaN anywhere
const f = extractFeatures(rows);
Object.entries(f).forEach(([k, v]) => assert.ok(Number.isFinite(v), k + " is not finite"));
assert.strictEqual(f.median_income, 80000);
assert.strictEqual(f.existing_emi, 8000);

// the same lender with a changing reference number is NOT a new lender
const mk = (d, desc, amt, bal) => ({ date: d, description: desc, amount: amt, balance: bal });
const g = extractFeatures([
  mk("2026-05-01", "SALARY", 50000, 90000), mk("2026-05-05", "EMI HDFC 0526", -5000, 85000),
  mk("2026-09-01", "SALARY", 50000, 130000), mk("2026-09-05", "EMI HDFC 0926", -5000, 125000),
]);
assert.strictEqual(g.new_emi_90d, 0);
// two rows on the same day (a return and its penalty) are one failed-payment event
const h = extractFeatures([
  mk("2026-09-01", "SALARY", 50000, 60000), mk("2026-09-05", "ECS RETURN", 5000, 65000), mk("2026-09-05", "BOUNCE CHARGE", -500, 64500),
]);
assert.strictEqual(h.bounce_count_90d, 1);
console.log("features.js checks passed");
