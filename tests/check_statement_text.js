// Run from the project root:  node tests/check_statement_text.js
// Checks that PDF/OCR-style statement text gives the same summary numbers as the CSV.
const fs=require("fs"), path=require("path"), assert=require("assert");
const F=require(path.join(__dirname,"..","frontend","features.js"));
function csv(t){const L=t.trim().split(/\r?\n/);const h=L[0].split(",");return L.slice(1).map(l=>{const c=l.split(",");return Object.fromEntries(h.map((k,i)=>[k,c[i]]));});}
const inr=n=>n.toLocaleString("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2});
for (const name of ["steady_salaried","gig_worker","sliding_into_stress"]) {
  const base=F.normalizeRows(csv(fs.readFileSync(path.join(__dirname,"fixtures",`${name}.csv`),"utf8"))).rows;
  const want=F.extractFeatures(base);
  const open=base[0].balance-base[0].amount;
  // layout A: one amount column, Indian formatting, value date, wrapped description, page noise
  let A=["MY BANK LTD  Statement of Account  Page 1 of 3","Date  Narration  Withdrawal  Deposit  Balance","Opening Balance  "+inr(open)];
  base.forEach((r,i)=>{const d=r.date.split("-").reverse().join("/"); A.push(`${d} ${d} ${r.description}  ${inr(Math.abs(r.amount))}  ${inr(r.balance)}`); if(i%7==0)A.push("REF 0099 CONT"); if(i%20==0)A.push("Page 2 of 3  Statement continues");});
  let got=F.parseStatementText(A.join("\n"));
  assert.strictEqual(got.rows.length, base.length, name+" rows A");
  assert.deepStrictEqual(F.extractFeatures(got.rows), want, name+" features A");
  assert.strictEqual(got.stats.reconciled_pct,100);
  // layout B: newest first, no opening balance, Dr/Cr markers
  let B=[]; base.forEach(r=>{const d=r.date.split("-").reverse().join("-"); B.push(`${d}  ${r.description}  ${inr(Math.abs(r.amount))} ${r.amount<0?"Dr":"Cr"}  ${inr(r.balance)} Cr`);}); B.reverse();
  got=F.parseStatementText(B.join("\n"));
  assert.ok(got.rows.length>=base.length-1, name+" rows B "+got.rows.length);
  console.log(name,"ok", got.stats);
}
// missed-row detection: drop one line, reconciliation must drop below 100
const base=F.normalizeRows(csv(fs.readFileSync(path.join(__dirname,"fixtures","steady_salaried.csv"),"utf8"))).rows;
let L=["Opening Balance "+inr(base[0].balance-base[0].amount)]; base.forEach((r,i)=>{ if(i===10) return; const d=r.date.split("/").join("-").split("-").reverse().join("/"); L.push(`${d} ${r.description} ${inr(Math.abs(r.amount))} ${inr(r.balance)}`);});
const g=F.parseStatementText(L.join("\n")); assert.ok(g.stats.mismatched>=1 && g.stats.reconciled_pct<100); console.log("missed row flagged:",g.stats);
// pdf.js line rebuild
const items=[{str:"05/10/2026",transform:[1,0,0,1,10,700]},{str:"8,000.00",transform:[1,0,0,1,300,701]},{str:"EMI HDFC",transform:[1,0,0,1,80,700]},{str:"SALARY",transform:[1,0,0,1,80,720]},{str:"01/10/2026",transform:[1,0,0,1,10,720]}];
assert.deepStrictEqual(F.itemsToLines(items),["01/10/2026  SALARY","05/10/2026  EMI HDFC  8,000.00"]);
console.log("itemsToLines ok");
