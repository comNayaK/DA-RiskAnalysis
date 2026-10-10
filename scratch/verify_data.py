import duckdb
from src.db import get_connection

def main():
    con = get_connection("mortgage_risk.duckdb")
    
    print("--- 1. Orig Year Counts ---")
    df_years = con.execute("SELECT orig_year, COUNT(DISTINCT loan_id) as n_loans FROM loan_level_transitions GROUP BY orig_year ORDER BY orig_year").df()
    print(df_years.to_string(index=False))
    
    print("\n--- 2. Modification Counts Reconciliation ---")
    mod_censor = con.execute("SELECT COUNT(DISTINCT loan_id) FROM clean_monthly_performance WHERE loan_state = 'Modified'").fetchone()[0]
    # LGD run might have used a different table or raw_performance?
    mod_ever = con.execute("SELECT COUNT(DISTINCT loan_id) FROM raw_performance WHERE COALESCE(modification_flag, '') IN ('Y', 'P')").fetchone()[0]
    print(f"Loans with 'Modified' state in clean_monthly_performance (censored): {mod_censor}")
    print(f"Loans with modification_flag in raw_performance (ever): {mod_ever}")
    
    print("\n--- 5. Stage 1 Hypothesis Test (Clean vs Recent Delinquency) ---")
    # Current loans at 201712
    # Group A: Clean 12m history
    # Group B: Recent delinquency
    query = """
    WITH current_loans AS (
        SELECT loan_id FROM clean_monthly_performance
        WHERE monthly_reporting_period = 201712 AND loan_state = 'Current'
    ),
    history AS (
        SELECT c.loan_id, 
               MAX(CASE WHEN p.loan_state IN ('30_DPD', '60_DPD') THEN 1 ELSE 0 END) as recent_delq
        FROM current_loans c
        JOIN clean_monthly_performance p ON c.loan_id = p.loan_id
        WHERE p.monthly_reporting_period BETWEEN 201701 AND 201712
        GROUP BY c.loan_id
    ),
    defaults_2018 AS (
        SELECT c.loan_id, 
               MAX(CASE WHEN p.loan_state = 'Default' THEN 1 ELSE 0 END) as defaulted
        FROM current_loans c
        JOIN clean_monthly_performance p ON c.loan_id = p.loan_id
        WHERE p.monthly_reporting_period BETWEEN 201801 AND 201812
        GROUP BY c.loan_id
    )
    SELECT h.recent_delq, COUNT(h.loan_id) as obs, SUM(d.defaulted) as defs
    FROM history h
    LEFT JOIN defaults_2018 d ON h.loan_id = d.loan_id
    GROUP BY h.recent_delq
    """
    df_hyp = con.execute(query).df()
    print(df_hyp)

if __name__ == "__main__":
    main()
