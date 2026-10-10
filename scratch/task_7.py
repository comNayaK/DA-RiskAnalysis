import duckdb
from src.db import get_connection

def main():
    con = get_connection("mortgage_risk.duckdb")
    out_lines = []
    
    # --- Task 1: Recompute Mod Share from 36m LGD cohort ---
    q1 = """
    WITH lgd_cohort AS (
        SELECT loan_id, MIN(monthly_reporting_period) as first_default 
        FROM clean_monthly_performance 
        WHERE loan_state = 'Default' 
        GROUP BY loan_id
        HAVING MIN(monthly_reporting_period) <= 201612
    ),
    mod_loans AS (
        SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as first_mod 
        FROM raw_performance 
        WHERE modification_flag IN ('Y', 'P') 
        GROUP BY loan_id
        HAVING MIN(CAST(monthly_reporting_period AS INT)) <= 202002
    )
    SELECT 
        COUNT(c.loan_id) as total_defaults,
        COUNT(m.loan_id) as modified_defaults,
        ROUND(COUNT(m.loan_id)*100.0/COUNT(c.loan_id), 2) as mod_share
    FROM lgd_cohort c
    LEFT JOIN mod_loans m ON c.loan_id = m.loan_id
    """
    df1 = con.execute(q1).df()
    total_def_36m = df1['total_defaults'].values[0]
    mod_def_36m = df1['modified_defaults'].values[0]
    mod_share = df1['mod_share'].values[0]
    out_lines.append(f"--- 1. 36m LGD Cohort Mod Share ---")
    out_lines.append(f"Total Defaults (<=201612): {total_def_36m}")
    out_lines.append(f"Modified Defaults (mod <=202002): {mod_def_36m}")
    out_lines.append(f"Modified Share: {mod_share}%")
    
    # Tail computation. Assuming UPB = Mod_Defaults * Avg_UPB or similar. Let's use exactly 30% if that's the result, or calculate it.
    # Total Mod UPB was $201,229,039 in 201912.
    # P(Liq | Re-default) = 60%, Severity = 31.3% (from earlier script).
    tail_amount = 201229039.43 * (mod_share / 100.0) * 0.60 * 0.313
    tail_pct = tail_amount / 28708141480.57 * 100
    out_lines.append(f"Tail Amount (UPB * {mod_share/100:.3f} * 0.6 * 0.313): ${tail_amount:,.2f}")
    
    # We will pick ONE LGD basis. Censor Lower (11.5%) + Tail is best.
    lgd_basis = 0.115 + (mod_share / 100.0 * 0.6 * 0.313) # Note: tail is additive to base PD*LGD, but in ECL we used a blended LGD.
    # Let's clarify: The tail amount is an absolute dollar add-on. If we use Censor Lower (11.5%), the base ECL is computed, then tail added.
    
    # --- Task 2: Probation Rule Overlap and PD ---
    # The applied PD for recently delinquent loans in the probation rule was 12.24% (Stage 2 Lifetime PD).
    # Justify against 3.2-3.9% direct 12m PD: 12.24% is a lifetime PD, which integrates ~3-4 years of WAL. 1-(1-0.035)^3.5 = ~11.7%. Fits.
    q2 = """
    WITH current_loans AS (
        SELECT loan_id FROM clean_monthly_performance
        WHERE monthly_reporting_period = 201912 AND loan_state = 'Current'
    ),
    history AS (
        SELECT c.loan_id, 
               MAX(CASE WHEN p.loan_state IN ('30_DPD', '60_DPD') THEN 1 ELSE 0 END) as recent_delq
        FROM current_loans c
        JOIN clean_monthly_performance p ON c.loan_id = p.loan_id
        WHERE p.monthly_reporting_period BETWEEN 201901 AND 201912
        GROUP BY c.loan_id
    )
    SELECT h.recent_delq, 
           COUNT(h.loan_id) as count,
           SUM(CASE WHEN r.modification_flag IN ('Y', 'P') THEN 1 ELSE 0 END) as mod_overlap
    FROM history h
    LEFT JOIN raw_performance r ON h.loan_id = r.loan_id AND r.monthly_reporting_period = '201912'
    GROUP BY h.recent_delq
    """
    df2 = con.execute(q2).df()
    out_lines.append(f"\n--- 2. Probation Rule Overlap with Pop 2 ---")
    out_lines.append(df2.to_string(index=False))
    
    # --- Task 3: Pop 2 Delinquent Backtest (12m) ---
    q3 = """
    WITH p2_loans AS (
        SELECT DISTINCT loan_id FROM clean_monthly_performance WHERE loan_state = 'Modified'
    ),
    cohort AS (
        SELECT r.loan_id, r.current_delinquency_status as raw_delq
        FROM raw_performance r
        JOIN p2_loans p2 ON r.loan_id = p2.loan_id
        WHERE r.monthly_reporting_period = '201712' AND r.current_delinquency_status IN ('01', '02')
    ),
    defs AS (
        SELECT c.loan_id, MAX(CASE WHEN p.loan_state = 'Default' THEN 1 ELSE 0 END) as defaulted
        FROM cohort c
        JOIN clean_monthly_performance p ON c.loan_id = p.loan_id
        WHERE p.monthly_reporting_period BETWEEN 201801 AND 201812
        GROUP BY c.loan_id
    )
    SELECT c.raw_delq, COUNT(c.loan_id) as obs, SUM(d.defaulted) as defs,
           ROUND(SUM(d.defaulted)*100.0/COUNT(c.loan_id), 4) as pd_12m
    FROM cohort c JOIN defs d ON c.loan_id = d.loan_id
    GROUP BY c.raw_delq
    """
    df3 = con.execute(q3).df()
    out_lines.append(f"\n--- 3. Pop 2 Delinquent 12m Backtest (vs 29.6% and 66.7%) ---")
    out_lines.append(df3.to_string(index=False))
    
    # --- Task 4: Ex-hurricane Clean vs Recent Delq ---
    out_lines.append(f"\n--- 4. Clean vs Recent Delq 2015-2019 (Ex-Hurricane) ---")
    for year in range(2015, 2020):
        prev_year = year - 1
        q4 = f"""
        WITH current_loans AS (
            SELECT p.loan_id FROM clean_monthly_performance p
            JOIN raw_origination r ON p.loan_id = r.loan_id
            WHERE p.monthly_reporting_period = {prev_year}12 AND p.loan_state = 'Current'
            AND NOT ({year} = 2017 AND r.property_state IN ('FL', 'TX', 'PR'))
        ),
        history AS (
            SELECT c.loan_id, 
                   MAX(CASE WHEN p.loan_state IN ('30_DPD', '60_DPD') THEN 1 ELSE 0 END) as recent_delq
            FROM current_loans c
            JOIN clean_monthly_performance p ON c.loan_id = p.loan_id
            WHERE p.monthly_reporting_period BETWEEN {prev_year}01 AND {prev_year}12
            GROUP BY c.loan_id
        ),
        defaults_next AS (
            SELECT c.loan_id, 
                   MAX(CASE WHEN p.loan_state = 'Default' THEN 1 ELSE 0 END) as defaulted
            FROM current_loans c
            JOIN clean_monthly_performance p ON c.loan_id = p.loan_id
            WHERE p.monthly_reporting_period BETWEEN {year}01 AND {year}12
            GROUP BY c.loan_id
        )
        SELECT {year} as eval_year, h.recent_delq, COUNT(h.loan_id) as obs, SUM(d.defaulted) as defs, 
               ROUND(SUM(d.defaulted)*100.0/COUNT(h.loan_id), 4) as pd_pct
        FROM history h
        LEFT JOIN defaults_next d ON h.loan_id = d.loan_id
        GROUP BY h.recent_delq
        """
        res = con.execute(q4).df()
        for _, row in res.iterrows():
            grp = "Recent Delq" if row['recent_delq'] == 1 else "Clean 12m"
            out_lines.append(f"Year {int(row['eval_year'])} | {grp:12s} | Obs: {int(row['obs']):7d} | Defs: {int(row['defs']):5d} | PD: {row['pd_pct']:.3f}%")

    with open('output/final_numbers.txt', 'w') as f:
        f.write('\n'.join(out_lines))
    print('\n'.join(out_lines))

if __name__ == "__main__":
    main()
