"""Builds synthetic statements (date, description, amount, balance) to test the pipeline end to end."""
import csv, os, random, datetime as dt
os.makedirs("tests/fixtures", exist_ok=True)

def build(path, months, income, rent, emi, spend, start_bal, seed=1, income_noise=0.0, bounce_last=0, new_emi_last=False, drop_last=0.0):
    rnd = random.Random(seed); rows = []; bal = start_bal
    y, m = 2026 - (months // 12 + 1), 1
    start = dt.date(2026, 10, 1)
    for i in range(months):
        mo = (start.month - 1 - (months - 1 - i)) % 12 + 1
        yr = start.year + (start.month - 1 - (months - 1 - i)) // 12
        inc = income * (1 + rnd.uniform(-income_noise, income_noise))
        if i == months - 1: inc *= (1 - drop_last)
        def add(day, desc, amt):
            nonlocal bal; bal += amt; rows.append((dt.date(yr, mo, day).isoformat(), desc, round(amt, 2), round(bal, 2)))
        add(1, "SALARY CREDIT", inc); add(2, "RENT PAYMENT", -rent)
        if emi: add(5, "EMI HDFC LOAN %02d%d" % (mo, yr % 100), -emi)
        if new_emi_last and i == months - 1: add(6, "EMI BAJAJ FINSERV", -3000)
        if bounce_last and i == months - 1:
            for _ in range(bounce_last): add(7 + _, "EMI BOUNCE CHARGE", -500)
        for d in range(8, 28, 4): add(d, "UPI GROCERY", -spend / 5)
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "description", "amount", "balance"]); w.writerows(rows)

if __name__ == "__main__":
    build("tests/fixtures/steady_salaried.csv", 8, 80000, 15000, 8000, 22000, 120000, income_noise=0.02)
    build("tests/fixtures/high_rent.csv", 8, 60000, 28000, 6000, 20000, 20000, income_noise=0.02)
    build("tests/fixtures/gig_worker.csv", 8, 40000, 9000, 4000, 16000, 15000, seed=3, income_noise=0.40)
    build("tests/fixtures/freelancer.csv", 8, 70000, 14000, 5000, 20000, 40000, seed=5, income_noise=0.30)
    build("tests/fixtures/sliding_into_stress.csv", 8, 50000, 14000, 14000, 24000, 30000, seed=7, income_noise=0.05, bounce_last=2, new_emi_last=True, drop_last=0.25)
