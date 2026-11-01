// Runs in the browser: turns the uploaded statement into the 15 summary numbers. Nothing here is sent anywhere.
// Accepted columns (any header spelling below, any order): date, description/narration/particulars,
// amount (signed) OR debit+credit (withdrawal+deposit), balance.
// Accepted dates: 2026-09-01, 01/09/2026, 01-09-2026, 01.09.2026, 01-Sep-2026, 01 Sep 2026.

const HEADER_ALIASES = {
  date: ["date", "txndate", "transactiondate", "valuedate", "postingdate", "trandate"],
  description: ["description", "narration", "particulars", "remarks", "transactiondetails", "details", "transactionremarks"],
  amount: ["amount", "amt", "transactionamount"],
  debit: ["debit", "withdrawal", "withdrawals", "withdrawalamt", "debitamount", "dr", "withdrawalamount"],
  credit: ["credit", "deposit", "deposits", "depositamt", "creditamount", "cr", "depositamount"],
  balance: ["balance", "closingbalance", "runningbalance", "balanceamt", "availablebalance"],
};
const MONTHS = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };

function parseNum(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  let s = String(v).trim();
  if (!s || s === "-") return null;
  let neg = false;
  if (/^\(.*\)$/.test(s)) { neg = true; s = s.slice(1, -1); }
  if (/\bdr\.?$/i.test(s)) { neg = true; s = s.replace(/\s*dr\.?$/i, ""); }
  s = s.replace(/\s*cr\.?$/i, "").replace(/(rs\.?|inr|₹|,|\s)/gi, "");
  if (s.startsWith("-")) { neg = !neg; s = s.slice(1); }
  if (!/^\d*\.?\d+$/.test(s)) return null;
  const x = parseFloat(s);
  return neg ? -x : x;
}

function parseDate(v) {
  if (!v) return null;
  const s = String(v).trim();
  let y, m, d, t;
  if ((t = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/))) { y = +t[1]; m = +t[2]; d = +t[3]; }
  else if ((t = s.match(/^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4}|\d{2})/))) { d = +t[1]; m = +t[2]; y = +t[3]; if (y < 100) y += 2000; }
  else if ((t = s.match(/^(\d{1,2})[\s\-\/]([A-Za-z]{3})[A-Za-z]*[\s\-\/,]+(\d{4}|\d{2})/))) { d = +t[1]; m = MONTHS[t[2].toLowerCase()]; y = +t[3]; if (y < 100) y += 2000; }
  else return null;
  if (!m || m < 1 || m > 12 || d < 1 || d > 31) return null;
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (dt.getUTCMonth() !== m - 1) return null;                       // rejects 31 Feb etc.
  return dt.toISOString().slice(0, 10);
}

// Raw parsed CSV rows -> [{date:"YYYY-MM-DD", description, amount (+credit / -debit), balance}] in time order.
function normalizeRows(raw) {
  if (!Array.isArray(raw) || !raw.length) throw new Error("The file has no data rows.");
  const keys = Object.keys(raw[0] || {});
  const find = names => keys.find(k => names.includes(k.toLowerCase().replace(/[^a-z]/g, "")));
  const col = Object.fromEntries(Object.entries(HEADER_ALIASES).map(([k, v]) => [k, find(v)]));
  if (!col.date) throw new Error("No 'date' column found.");
  if (!col.balance) throw new Error("No 'balance' column found. The running balance is needed to measure your cash cushion.");
  if (!col.amount && !(col.debit || col.credit)) throw new Error("No 'amount' (or 'debit'/'credit') column found.");
  let skipped = 0;
  let rows = [];
  for (const r of raw) {
    const date = parseDate(r[col.date]), balance = parseNum(r[col.balance]);
    let amount = col.amount ? parseNum(r[col.amount]) : null;
    if (amount === null && (col.debit || col.credit)) {
      const cr = col.credit ? parseNum(r[col.credit]) : null, dr = col.debit ? parseNum(r[col.debit]) : null;
      if (cr !== null || dr !== null) amount = (cr || 0) - Math.abs(dr || 0);
    }
    if (!date || balance === null || amount === null) { skipped++; continue; }
    rows.push({ date, description: String(col.description ? r[col.description] ?? "" : ""), amount, balance });
  }
  if (!rows.length) throw new Error("No valid rows: check the date, amount and balance formats.");
  if (rows.length > 1 && rows[0].date > rows[rows.length - 1].date) rows.reverse();   // newest-first statements
  rows = rows.map((r, i) => ({ r, i })).sort((a, b) => a.r.date < b.r.date ? -1 : a.r.date > b.r.date ? 1 : a.i - b.i).map(x => x.r);
  return { rows, skipped };
}

// ---------------------------------------------------------------------------------------------
// PDF / text / image statements.  The file is turned into plain text IN THE BROWSER (pdf.js for PDFs
// with a text layer, Tesseract OCR for scans and photos), then parsed here into the same rows as a CSV.
// Amount signs are NOT guessed from columns: they come from how the running balance moves, and every
// row is checked against the printed amount so misreads are counted and reported.
// ---------------------------------------------------------------------------------------------
const DATE_AT_START = /^\s*(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[\/\-.]\d{1,2}[\/\-.](?:\d{4}|\d{2})|\d{1,2}[\s\-\/][A-Za-z]{3}[A-Za-z]*[\s\-\/,]+(?:\d{4}|\d{2}))(?![\d])/;
const MONEY_STRICT = /\(?-?\d{1,3}(?:,\d{2,3})*\.\d{1,2}\)?(?:\s?(?:Dr|Cr)\b\.?)?|\(?-?\d+\.\d{1,2}\)?(?:\s?(?:Dr|Cr)\b\.?)?/gi;
const MONEY_LOOSE = /\(?-?\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?\)?(?:\s?(?:Dr|Cr)\b\.?)?|\(?-?\d{4,}\)?(?:\s?(?:Dr|Cr)\b\.?)?/gi;
const OPENING = /OPENING\s+BAL|BROUGHT\s+FORWARD|B\/F\b|BALANCE\s+B\/F/i;
const CREDIT_WORDS = ["SALARY", "CREDIT", "DEPOSIT", "INTEREST", "REFUND", "REVERSAL", "CASHBACK", "NEFT CR", "IMPS CR", "BY TRANSFER"];

// pdf.js text items [{str, transform:[a,b,c,d,x,y]}] -> text lines in reading order
function itemsToLines(items) {
  const rows = [];
  for (const it of items) {
    if (!it.str || !it.str.trim()) continue;
    const x = it.transform[4], y = it.transform[5];
    let row = rows.find(r => Math.abs(r.y - y) <= 3);
    if (!row) { row = { y, parts: [] }; rows.push(row); }
    row.parts.push({ x, str: it.str });
  }
  return rows.sort((a, b) => b.y - a.y).map(r => r.parts.sort((a, b) => a.x - b.x).map(p => p.str.trim()).join("  "));
}

function moneyValue(tok) {
  let t = tok.trim(), sign = 1;
  if (/^\(.*\)/.test(t)) sign = -1;
  if (/dr\.?$/i.test(t)) sign = -1;
  const marker = /dr\.?$/i.test(t) ? "Dr" : /cr\.?$/i.test(t) ? "Cr" : null;
  t = t.replace(/\s?(dr|cr)\.?$/i, "").replace(/[()\s,]/g, "");
  if (t.startsWith("-")) { sign = -sign; t = t.slice(1); }
  const v = parseFloat(t);
  return { value: Number.isFinite(v) ? v : null, sign, marker };
}

function parseStatementText(text) {
  const lines = String(text).split(/\r?\n/).map(l => l.replace(/\u00a0/g, " ").trim()).filter(Boolean);
  for (const pattern of [MONEY_STRICT, MONEY_LOOSE]) {
    const res = parseLines(lines, pattern);
    if (res.rows.length >= 2) return res;
  }
  return parseLines(lines, MONEY_STRICT);
}

function parseLines(lines, pattern) {
  const raw = [];                       // {date, description, printed:[numbers], balance, marker}
  let opening = null, skipped = 0, lastRow = null;
  for (const line of lines) {
    const m = line.match(DATE_AT_START);
    const toks = [...line.matchAll(new RegExp(pattern.source, "gi"))];
    if (!m) {
      if (OPENING.test(line) && toks.length) { const v = moneyValue(toks[toks.length - 1][0]); if (opening === null && v.value !== null) opening = v.value; lastRow = null; }
      else if (lastRow && !toks.length && line.length < 80) lastRow.description += " " + line;   // wrapped description
      continue;
    }
    const date = parseDate(m[1]);
    let rest = line.slice(m[0].length);
    const second = rest.match(DATE_AT_START);                       // value date printed after the transaction date
    if (second) rest = rest.slice(second[0].length);
    const restToks = [...rest.matchAll(new RegExp(pattern.source, "gi"))];
    if (!date || restToks.length < 2) {
      if (OPENING.test(rest) && restToks.length) { const v = moneyValue(restToks[restToks.length - 1][0]); if (opening === null && v.value !== null) opening = v.value; }
      else skipped++;
      lastRow = null; continue;
    }
    const vals = restToks.map(t => moneyValue(t[0]));
    const bal = vals[vals.length - 1];
    if (bal.value === null) { skipped++; lastRow = null; continue; }
    const printed = vals.slice(0, -1).filter(v => v.value !== null && v.value > 0);
    const desc = rest.slice(0, restToks[0].index).trim();
    lastRow = { date, description: desc, printed, balance: bal.sign * bal.value, marker: printed.length ? printed[printed.length - 1].marker : null };
    raw.push(lastRow);
  }
  if (raw.length > 1 && raw[0].date > raw[raw.length - 1].date) raw.reverse();      // newest-first
  raw.forEach((r, i) => { r._i = i; });
  raw.sort((a, b) => a.date < b.date ? -1 : a.date > b.date ? 1 : a._i - b._i);
  const rows = []; let prev = opening, matched = 0, mismatched = 0;
  for (const r of raw) {
    const printedAmts = r.printed.map(p => p.value);
    let amount = null;
    if (prev !== null) {
      const delta = Math.round((r.balance - prev) * 100) / 100;
      const hit = printedAmts.find(a => Math.abs(a - Math.abs(delta)) < 0.011);
      if (hit !== undefined) { amount = Math.sign(delta) * hit; matched++; }                 // use the printed amount, sign from the balance movement
      else if (printedAmts.length && delta !== 0) { amount = Math.sign(delta) * Math.max(...printedAmts); mismatched++; }   // a row between was probably missed
      else if (delta !== 0) { amount = delta; mismatched++; }
    } else if (printedAmts.length) {                                                 // first row without an opening balance
      const up = r.marker === "Cr" ? 1 : r.marker === "Dr" ? -1 : CREDIT_WORDS.some(w => r.description.toUpperCase().includes(w)) ? 1 : null;
      if (up !== null) amount = up * Math.max(...printedAmts);
    }
    if (amount === null) { skipped++; prev = r.balance; continue; }
    rows.push({ date: r.date, description: r.description, amount, balance: r.balance });
    prev = r.balance;
  }
  const total = matched + mismatched;
  return { rows, stats: { rows_read: rows.length, skipped, matched, mismatched, reconciled_pct: total ? Math.round(1000 * matched / total) / 10 : 0,
                          first_date: rows.length ? rows[0].date : null, last_date: rows.length ? rows[rows.length - 1].date : null } };
}

function tagRow(desc, amount) {
  const d = desc.toUpperCase();
  if (["BOUNCE", "DISHONOUR", "DISHONOR", "INSUFFICIENT", "ECS RETURN", "NACH RETURN", "CHQ RETURN", "CHEQUE RETURN", "RETURNED UNPAID"].some(k => d.includes(k))) return "bounce";
  if (amount > 0) return ["REFUND", "REVERSAL", "CASHBACK"].some(k => d.includes(k)) ? "refund" : "income";
  if (d.includes("EMI") || d.includes("LOAN")) return "emi";
  if (d.includes("SAVINGS") || d.includes("MUTUAL FUND") || d.includes("SIP")) return "savings";
  if (["RENT", "ELECTRICITY", "INSURANCE", "RECHARGE", "BROADBAND", "POSTPAID", "SOCIETY", "MAINTENANCE", "TUITION", "SCHOOL FEE"].some(k => d.includes(k))) return "fixed";
  return "essential";
}
const payeeKey = s => s.toUpperCase().replace(/[^A-Z]+/g, " ").trim().split(" ").slice(0, 3).join(" ");   // "EMI HDFC LOAN 0923 ref..." and "EMI HDFC LOAN 1023" are the same lender

const sum = a => a.reduce((x, y) => x + y, 0);
const mean = a => a.length ? sum(a) / a.length : 0;
function percentile(a, p) {            // same as numpy.percentile (linear interpolation)
  const s = [...a].sort((x, y) => x - y), pos = (s.length - 1) * p / 100;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  return s[lo] + (s[hi] - s[lo]) * (pos - lo);
}

function extractFeatures(rows) {
  rows = rows.map(r => ({ ...r, amount: +r.amount, balance: +r.balance,
                          tag: tagRow(r.description, +r.amount), month: r.date.slice(0, 7) }));
  const months = [...new Set(rows.map(r => r.month))].sort();
  const monthly = (tag, sign) => months.map(m => sign * sum(rows.filter(r => r.month === m && r.tag === tag).map(r => r.amount)));
  const inc = monthly("income", 1), emi = monthly("emi", -1), fixed = monthly("fixed", -1), ess = monthly("essential", -1);
  const bal = months.map(m => mean(rows.filter(r => r.month === m).map(r => r.balance)));
  const last = (a, n) => a.slice(-n), n = months.length;
  const inc6 = last(inc, 6), essMean = mean(last(ess, 6));
  const maxDate = rows[rows.length - 1].date;
  const cutoff = new Date(Date.parse(maxDate) - 90 * 86400000).toISOString().slice(0, 10);
  const recent = rows.filter(r => r.date > cutoff), earlier = rows.filter(r => r.date <= cutoff);
  const emiNames = rs => new Set(rs.filter(r => r.tag === "emi").map(r => payeeKey(r.description)));
  const earlierNames = emiNames(earlier);
  const newLenders = earlier.length ? [...emiNames(recent)].filter(x => !earlierNames.has(x)).length : 0;
  const daily = {};                                    // last balance of each day in the latest month
  rows.filter(r => r.month === months[n - 1]).forEach(r => { daily[r.date] = r.balance; });
  const weekOfEssentials = essMean * 7 / 30;           // "very low balance" = under one week of essential spending
  const k = Math.min(3, n);
  const ratioK = last(emi, k).map((e, i) => last(inc, k)[i] ? e / last(inc, k)[i] : 0);
  const incPrev = inc.slice(Math.max(0, n - 7), n - 1), incPrevMean = mean(incPrev);
  const balPrev = mean(bal.slice(Math.max(0, n - 4), n - 1));
  const f = {
    median_income: percentile(inc6, 50), p25_income: percentile(inc6, 25),
    income_cv: mean(inc6) ? Math.sqrt(mean(inc6.map(x => (x - mean(inc6)) ** 2))) / mean(inc6) : 0,
    months_of_data: n, existing_emi: Math.max(...last(emi, 3)), fixed_other: mean(last(fixed, 3)),
    essentials: essMean, avg_balance: mean(last(bal, 6)),
    min_balance: Math.min(...rows.filter(r => months.slice(-6).includes(r.month)).map(r => r.balance)),
    low_balance_days: Object.values(daily).filter(b => b < weekOfEssentials).length,
    bounce_count_90d: new Set(recent.filter(r => r.tag === "bounce").map(r => r.date)).size,   // failed-payment days (a return + its penalty row count once)
    emi_ratio_trend: k >= 2 ? (ratioK[k - 1] - ratioK[0]) / (k - 1) : 0,
    balance_change_pct: n >= 2 && balPrev > 0 ? bal[n - 1] / balPrev - 1 : 0,
    income_drop_pct: n >= 2 && incPrevMean > 0 ? 1 - inc[n - 1] / incPrevMean : 0,
    new_emi_90d: newLenders,
  };
  Object.keys(f).forEach(key => { f[key] = Math.round(f[key] * 1e4) / 1e4; });
  return f;
}
if (typeof module !== "undefined") module.exports = { extractFeatures, normalizeRows, parseNum, parseDate, tagRow, parseStatementText, itemsToLines };
