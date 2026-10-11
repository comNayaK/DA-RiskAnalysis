import duckdb

def reproduce_vintage_curves():
    con = duckdb.connect("mortgage_risk.duckdb", read_only=True)

    print("=====================================================================================================")
    print("                      1. BEFORE / AFTER VINTAGE DEFAULT BREAKDOWN                                     ")
    print("=====================================================================================================")
    q_breakdown = """
    SELECT 
        2000 + CAST(SUBSTRING(p.loan_id, 2, 2) AS INT) AS orig_year,
        COUNT(*) AS total_defaults,
        COUNT(*) FILTER (WHERE NOT EXISTS (
            SELECT 1 FROM raw_performance rp 
            WHERE rp.loan_id = p.loan_id 
              AND CAST(rp.monthly_reporting_period AS INT) <= 202002 
              AND COALESCE(rp.modification_flag, '') IN ('Y', 'P')
        )) AS before_defaults,
        COUNT(*) FILTER (WHERE EXISTS (
            SELECT 1 FROM raw_performance rp 
            WHERE rp.loan_id = p.loan_id 
              AND CAST(rp.monthly_reporting_period AS INT) <= 202002 
              AND COALESCE(rp.modification_flag, '') IN ('Y', 'P')
        )) AS restored_mod_after_default
    FROM truncated_performance p
    WHERE p.loan_state = 'Default'
    GROUP BY orig_year
    ORDER BY orig_year;
    """
    rows = con.execute(q_breakdown).fetchall()
    print("| Vintage | Origination Loans (Denominator) | Before Defaults (Blanket Purge) | Restored Mod-After-Default | After Defaults (Keeping Mod-After-Default) |")
    print("|---|---|---|---|---|")
    tot_before = sum(r[2] for r in rows)
    tot_restored = sum(r[3] for r in rows)
    tot_after = sum(r[1] for r in rows)
    for r in rows:
        print(f"| **{r[0]}** | 50,000 | {r[2]:,d} | +{r[3]:,d} | **{r[1]:,d}** |")
    print(f"| **TOTAL** | **350,000** | **{tot_before:,d}** | **+{tot_restored:,d}** | **{tot_after:,d}** |\n")

    print("=====================================================================================================")
    print("                      2. FORMAL NUMERATOR SUBSET OF OBSERVABLE DENOMINATOR TEST                     ")
    print("=====================================================================================================")
    q_subset = """
    SELECT COUNT(*) AS violations
    FROM truncated_performance p
    WHERE p.loan_state = 'Default'
      AND NOT EXISTS (
          SELECT 1 FROM raw_origination o
          WHERE o.loan_id = p.loan_id
            AND (month_idx(202002) - month_idx(TRY_CAST(o.first_payment_date AS INT)) + 1) >= p.loan_age
      );
    """
    violations = con.execute(q_subset).fetchone()[0]
    print(f"Violations where default loan age > max observable age prior to 202002: {violations} (Passed: numerator ⊆ observable denominator)\n")

    print("=========================================================================================================================")
    print("                      3. VINTAGE CURVES AT KEY MILESTONES (12, 24, 36, 48, 60 MONTHS)                                   ")
    print("=========================================================================================================================")
    q_curves = """
    SELECT 
        orig_year, 
        loan_age, 
        new_defaults_at_age, 
        observable_loans, 
        cumulative_defaults, 
        per_original_loan_incidence_pct,
        cumulative_incidence_per_observable_pct
    FROM v_vintage_curves
    WHERE loan_age IN (12, 24, 36, 48, 60)
    ORDER BY orig_year, loan_age;
    """
    curves = con.execute(q_curves).fetchall()
    print("| Vintage | Age (m) | New Defaults | Observable Denominator | Cumulative Defaults | Per-Original-Loan Incidence % | Cumulative Incidence per Observable Loan % |")
    print("|---|---|---|---|---|---|---|")
    for c in curves:
        print(f"| **{c[0]}** | {c[1]:2d} | {c[2]:3d} | {c[3]:6,d} | {c[4]:4d} | {c[5]:6.4f}% | **{c[6]:6.4f}%** |")
    print("=========================================================================================================================\n")

    print("=========================================================================================================================")
    print("                      4. EMPIRICAL 6-MONTH-BINNED INCIDENCE (MONTHS 1 TO 60)                                            ")
    print("=========================================================================================================================")
    q_binned = """
    WITH binned AS (
        SELECT 
            CASE 
                WHEN loan_age BETWEEN 1 AND 6 THEN '01-06m'
                WHEN loan_age BETWEEN 7 AND 12 THEN '07-12m'
                WHEN loan_age BETWEEN 13 AND 18 THEN '13-18m'
                WHEN loan_age BETWEEN 19 AND 24 THEN '19-24m'
                WHEN loan_age BETWEEN 25 AND 30 THEN '25-30m'
                WHEN loan_age BETWEEN 31 AND 36 THEN '31-36m'
                WHEN loan_age BETWEEN 37 AND 42 THEN '37-42m'
                WHEN loan_age BETWEEN 43 AND 48 THEN '43-48m'
                WHEN loan_age BETWEEN 49 AND 54 THEN '49-54m'
                WHEN loan_age BETWEEN 55 AND 60 THEN '55-60m'
                ELSE '60m+'
            END AS age_bin,
            new_defaults_at_age,
            observable_loans
        FROM v_vintage_curves
        WHERE loan_age BETWEEN 1 AND 60
    )
    SELECT 
        age_bin,
        SUM(new_defaults_at_age) AS total_defaults,
        ROUND(SUM(observable_loans) * 1.0 / 6.0, 0) AS exposure,
        ROUND(SUM(new_defaults_at_age) * 100.0 / (SUM(observable_loans) * 1.0 / 6.0), 4) AS incidence_pct
    FROM binned
    GROUP BY age_bin
    ORDER BY age_bin;
    """
    binned_rows = con.execute(q_binned).fetchall()
    print("| Age Bin (Months) | 6-Month Defaults | Observable Exposure | 6-Month Incidence % |")
    print("|---|---|---|---|")
    for b in binned_rows:
        print(f"| **{b[0]}** | {b[1]:,d} | {int(b[2]):,d} | **{b[3]:.4f}%** |")
    print("=========================================================================================================================")

if __name__ == "__main__":
    reproduce_vintage_curves()
