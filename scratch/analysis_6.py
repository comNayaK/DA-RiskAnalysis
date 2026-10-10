import duckdb
from src.db import get_connection

def main():
    con = get_connection("mortgage_risk.duckdb")
    
    # 1. Total UPB by Stage in 201912 (excluding Pop 3 which is 100% default)
    # Stage 1: Pop 1 Current
    # Stage 2: Pop 1 30/60 DPD + Pop 2 Current + Pop 2 30/60 DPD
    q1 = """
    WITH p2_loans AS (
        SELECT loan_id FROM clean_monthly_performance WHERE monthly_reporting_period = 201912 AND loan_state = 'Modified'
    )
    SELECT 'Pop1_Stage1' as segment, SUM(current_actual_upb) as upb FROM clean_monthly_performance 
    WHERE monthly_reporting_period = 201912 AND loan_state = 'Current' AND loan_id NOT IN (SELECT loan_id FROM p2_loans)
    UNION ALL
    SELECT 'Pop1_Stage2' as segment, SUM(current_actual_upb) as upb FROM clean_monthly_performance 
    WHERE monthly_reporting_period = 201912 AND loan_state IN ('30_DPD', '60_DPD') AND loan_id NOT IN (SELECT loan_id FROM p2_loans)
    """
    df1 = con.execute(q1).df()
    
    pop1_s1_upb = df1[df1['segment']=='Pop1_Stage1']['upb'].values[0]
    pop1_s2_upb = df1[df1['segment']=='Pop1_Stage2']['upb'].values[0]
    
    # Pop 2 UPB splits
    q2 = """
    WITH p2_loans AS (
        SELECT loan_id FROM clean_monthly_performance WHERE monthly_reporting_period = 201912 AND loan_state = 'Modified'
    )
    SELECT r.current_delinquency_status as raw_delq, SUM(CAST(r.current_actual_upb AS DOUBLE)) as upb
    FROM raw_performance r
    JOIN p2_loans p2 ON r.loan_id = p2.loan_id
    WHERE r.monthly_reporting_period = '201912'
    GROUP BY r.current_delinquency_status
    """
    df2 = con.execute(q2).df()
    pop2_00 = df2[df2['raw_delq']=='00']['upb'].sum() if '00' in df2['raw_delq'].values else 0
    pop2_01 = df2[df2['raw_delq']=='01']['upb'].sum() if '01' in df2['raw_delq'].values else 0
    pop2_02 = df2[df2['raw_delq']=='02']['upb'].sum() if '02' in df2['raw_delq'].values else 0
    
    # Stage 3
    pop3_upb = con.execute("SELECT SUM(current_actual_upb) FROM clean_monthly_performance WHERE monthly_reporting_period = 201912 AND loan_state = 'Default'").fetchone()[0]
    
    print(f"Pop 1 Stage 1 UPB: ${pop1_s1_upb:,.2f}")
    print(f"Pop 1 Stage 2 UPB: ${pop1_s2_upb:,.2f}")
    print(f"Pop 2 '00' UPB:    ${pop2_00:,.2f}")
    print(f"Pop 2 '01' UPB:    ${pop2_01:,.2f}")
    print(f"Pop 2 '02' UPB:    ${pop2_02:,.2f}")
    print(f"Pop 3 (Default):   ${pop3_upb:,.2f}")
    
    # PDs
    pd_s1_headline = 0.00218
    pd_s1_sens = 0.00178
    pd_s2 = 0.1224  # Assuming blended Stage 2 Pop 1 is dominated by 30 DPD. Or use exact:
    pd_pop1_30 = 0.1224
    pd_pop1_60 = 0.5259
    # Let's get exact pop 1 30/60 splits
    q3 = "SELECT loan_state, SUM(current_actual_upb) as upb FROM clean_monthly_performance WHERE monthly_reporting_period = 201912 AND loan_state IN ('30_DPD', '60_DPD') AND loan_id NOT IN (SELECT loan_id FROM clean_monthly_performance WHERE monthly_reporting_period = 201912 AND loan_state = 'Modified') GROUP BY loan_state"
    df3 = con.execute(q3).df()
    pop1_30 = df3[df3['loan_state']=='30_DPD']['upb'].values[0] if '30_DPD' in df3['loan_state'].values else 0
    pop1_60 = df3[df3['loan_state']=='60_DPD']['upb'].values[0] if '60_DPD' in df3['loan_state'].values else 0
    
    ecl_pop1_s2 = (pop1_30 * pd_pop1_30 + pop1_60 * pd_pop1_60) * 0.141
    
    pd_pop2_00 = 0.1224 # Probation rule treats as Stage 2 base
    pd_pop2_01 = 0.7338
    pd_pop2_02 = 0.8450
    
    ecl_pop2 = (pop2_00 * pd_pop2_00 + pop2_01 * pd_pop2_01 + pop2_02 * pd_pop2_02) * 0.141
    ecl_pop3 = pop3_upb * 1.0 * 0.141
    
    # Total ECL Headline (0.218%)
    ecl_headline = (pop1_s1_upb * pd_s1_headline * 0.141) + ecl_pop1_s2 + ecl_pop2 + ecl_pop3
    # Total ECL Sensitivity (0.178%)
    ecl_sens = (pop1_s1_upb * pd_s1_sens * 0.141) + ecl_pop1_s2 + ecl_pop2 + ecl_pop3
    
    print(f"\nHeadline ECL (0.218% Stage 1, Pop 2 Fixed): ${ecl_headline:,.2f}")
    print(f"Sensitivity ECL (0.178% Stage 1): ${ecl_sens:,.2f}")

if __name__ == "__main__":
    main()
