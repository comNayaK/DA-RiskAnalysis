import duckdb
from src.db import get_connection

def main():
    con = get_connection("mortgage_risk.duckdb")
    
    print("=== Stage 1 to Stage 2 Probation Shift in 201912 Snapshot ===")
    
    q = """
    WITH current_loans AS (
        SELECT loan_id, current_actual_upb as upb FROM clean_monthly_performance
        WHERE monthly_reporting_period = 201912 AND loan_state = 'Current'
    ),
    history AS (
        SELECT c.loan_id, c.upb,
               MAX(CASE WHEN p.loan_state IN ('30_DPD', '60_DPD') THEN 1 ELSE 0 END) as recent_delq
        FROM current_loans c
        JOIN clean_monthly_performance p ON c.loan_id = p.loan_id
        WHERE p.monthly_reporting_period BETWEEN 201901 AND 201912
        GROUP BY c.loan_id, c.upb
    )
    SELECT recent_delq, COUNT(loan_id) as count, SUM(upb) as upb
    FROM history
    GROUP BY recent_delq
    """
    df = con.execute(q).df()
    print(df)
    
    clean_upb = df[df['recent_delq']==0]['upb'].values[0]
    delq_upb = df[df['recent_delq']==1]['upb'].values[0]
    
    print("\nECL with 12m Probation Rule (at 14.1% LGD):")
    # Base rates from Ex-Hurricane matrix (Stage 1 recalibrated to 0.178%)
    pd_s1_clean = 0.00178  # We use the recalibrated baseline for the clean portion
    pd_s2 = 0.1224 # 30 DPD Lifetime PD from matrix
    
    ecl_clean = clean_upb * pd_s1_clean * 0.141
    ecl_delq = delq_upb * pd_s2 * 0.141
    
    print(f"Clean (Stage 1): UPB=${clean_upb:,.2f} | ECL=${ecl_clean:,.2f}")
    print(f"Probation (Stage 2): UPB=${delq_upb:,.2f} | ECL=${ecl_delq:,.2f}")
    print(f"Total Current ECL under Probation Rule: ${ecl_clean + ecl_delq:,.2f}")
    
    print("\n=== Fixing Pop 2 Delinquent PDs ===")
    # Pop 2 delinquent UPB in 201912
    q2 = """
    SELECT loan_state, COUNT(loan_id), SUM(current_actual_upb) as upb 
    FROM clean_monthly_performance
    WHERE monthly_reporting_period = 201912 
      AND loan_id IN (SELECT loan_id FROM clean_monthly_performance WHERE loan_state = 'Modified')
    GROUP BY loan_state
    """
    df_pop2 = con.execute(q2).df()
    print(df_pop2)
    # We will compute the new ECL with adjusted Pop 2 PDs. Wait, what are the actual PDs for Pop 2 delinquent?
    # Pop 2 delinquent loans default rate in trailing 24m:
    q3 = """
    WITH p2_loans AS (
        SELECT loan_id FROM clean_monthly_performance WHERE loan_state = 'Modified'
    ),
    cohort AS (
        SELECT p.loan_id, p.loan_state, p.current_actual_upb as upb
        FROM clean_monthly_performance p
        JOIN p2_loans p2 ON p.loan_id = p2.loan_id
        WHERE p.monthly_reporting_period = 201712 AND p.loan_state IN ('30_DPD', '60_DPD')
    ),
    defs AS (
        SELECT c.loan_id, MAX(CASE WHEN p.loan_state = 'Default' THEN 1 ELSE 0 END) as defaulted
        FROM cohort c
        JOIN clean_monthly_performance p ON c.loan_id = p.loan_id
        WHERE p.monthly_reporting_period BETWEEN 201801 AND 201812
        GROUP BY c.loan_id
    )
    SELECT c.loan_state, COUNT(c.loan_id) as obs, SUM(d.defaulted) as defs,
           ROUND(SUM(d.defaulted)*100.0/COUNT(c.loan_id), 4) as pd_pct
    FROM cohort c JOIN defs d ON c.loan_id = d.loan_id
    GROUP BY c.loan_state
    """
    print(con.execute(q3).df())

if __name__ == "__main__":
    main()
