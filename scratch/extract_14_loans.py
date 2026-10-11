import duckdb

con = duckdb.connect("mortgage_risk.duckdb", read_only=True)
q = """
WITH raw_mods AS (
    SELECT DISTINCT loan_id 
    FROM raw_performance 
    WHERE CAST(monthly_reporting_period AS INT) <= 202002 
      AND COALESCE(modification_flag, '') IN ('Y', 'P')
),
clean_mods AS (
    SELECT DISTINCT loan_id 
    FROM clean_monthly_performance 
    WHERE loan_state = 'Modified'
),
diff_loans AS (
    SELECT r.loan_id 
    FROM raw_mods r
    WHERE NOT EXISTS (SELECT 1 FROM clean_mods c WHERE c.loan_id = r.loan_id)
),
first_mod AS (
    SELECT 
        r.loan_id,
        MIN(r.monthly_reporting_period) AS first_mod_period
    FROM raw_performance r
    WHERE r.loan_id IN (SELECT loan_id FROM diff_loans)
      AND COALESCE(r.modification_flag, '') IN ('Y', 'P')
    GROUP BY r.loan_id
)
SELECT 
    f.loan_id,
    f.first_mod_period,
    c.loan_state,
    r.modification_flag,
    r.current_delinquency_status,
    COALESCE(r.zero_balance_code, '') AS zero_balance_code
FROM first_mod f
JOIN raw_performance r 
  ON f.loan_id = r.loan_id AND f.first_mod_period = r.monthly_reporting_period
JOIN clean_monthly_performance c 
  ON f.loan_id = c.loan_id AND f.first_mod_period = c.monthly_reporting_period
ORDER BY c.loan_state, f.loan_id;
"""
res = con.execute(q).fetchall()
print(f"Total reconciliation delta loans: {len(res)}\n")
print("| Loan ID | Reporting Period | Loan State | Mod Flag | Delinq Status | Zero Bal Code | Precedence Classification |")
print("|---|---|---|---|---|---|---|")
for r in res:
    zb = r[5] if r[5] else "NULL"
    reason = "Default precedence (Delinq >= 3 or ZB 02/03/09)" if r[2] == "Default" else "Paid Off precedence (ZB 01)"
    print(f"| `{r[0]}` | {r[1]} | **{r[2]}** | `{r[3]}` | `{r[4]}` | `{zb}` | {reason} |")
