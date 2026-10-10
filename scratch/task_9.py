import duckdb
from src.db import get_connection

def main():
    con = get_connection("mortgage_risk.duckdb")
    LGD = 0.137
    
    q_upb = """
    WITH p2_loans AS (SELECT loan_id FROM clean_monthly_performance WHERE monthly_reporting_period = 201912 AND loan_state = 'Modified')
    SELECT 
        SUM(CASE WHEN loan_state = 'Current' AND loan_id NOT IN (SELECT loan_id FROM p2_loans) THEN current_actual_upb ELSE 0 END) as pop1_s1,
        SUM(CASE WHEN loan_state = '30_DPD' AND loan_id NOT IN (SELECT loan_id FROM p2_loans) THEN current_actual_upb ELSE 0 END) as pop1_30,
        SUM(CASE WHEN loan_state = '60_DPD' AND loan_id NOT IN (SELECT loan_id FROM p2_loans) THEN current_actual_upb ELSE 0 END) as pop1_60,
        SUM(CASE WHEN loan_state = 'Default' THEN current_actual_upb ELSE 0 END) as pop3
    FROM clean_monthly_performance WHERE monthly_reporting_period = 201912
    """
    upbs = con.execute(q_upb).fetchone()
    pop1_s1 = upbs[0]
    pop1_30 = upbs[1]
    pop1_60 = upbs[2]
    pop3 = upbs[3]
    
    q_p2 = """
    WITH p2_loans AS (SELECT loan_id FROM clean_monthly_performance WHERE monthly_reporting_period = 201912 AND loan_state = 'Modified')
    SELECT r.current_delinquency_status as raw_delq, SUM(CAST(r.current_actual_upb AS DOUBLE)) as upb
    FROM raw_performance r JOIN p2_loans p2 ON r.loan_id = p2.loan_id
    WHERE r.monthly_reporting_period = '201912' GROUP BY r.current_delinquency_status
    """
    df_p2 = con.execute(q_p2).df()
    pop2_00 = df_p2[df_p2['raw_delq']=='00']['upb'].sum() if '00' in df_p2['raw_delq'].values else 0
    pop2_01 = df_p2[df_p2['raw_delq']=='01']['upb'].sum() if '01' in df_p2['raw_delq'].values else 0
    pop2_02 = df_p2[df_p2['raw_delq']=='02']['upb'].sum() if '02' in df_p2['raw_delq'].values else 0
    
    pd_s1 = 0.00218
    pd_s2_30 = 0.1224
    pd_s2_60 = 0.5259
    pd_p2_01 = 0.515
    pd_p2_02 = 0.7949
    
    e1 = pop1_s1 * pd_s1 * LGD
    e2 = pop1_30 * pd_s2_30 * LGD
    e3 = pop1_60 * pd_s2_60 * LGD
    e4 = pop2_00 * pd_s2_30 * LGD
    e5 = pop2_01 * pd_p2_01 * LGD
    e6 = pop2_02 * pd_p2_02 * LGD
    e7 = pop3 * 1.0 * LGD
    
    total = e1 + e2 + e3 + e4 + e5 + e6 + e7
    
    print(f"Total ECL (13.7% LGD, No probation): ${total:,.0f}")
    
    # Probation impact
    q_prob = """
    WITH current_loans AS (SELECT loan_id, current_actual_upb as upb FROM clean_monthly_performance WHERE monthly_reporting_period = 201912 AND loan_state = 'Current' AND loan_id NOT IN (SELECT loan_id FROM clean_monthly_performance WHERE monthly_reporting_period = 201912 AND loan_state = 'Modified')),
    history AS (SELECT c.loan_id, c.upb, MAX(CASE WHEN p.loan_state IN ('30_DPD', '60_DPD') THEN 1 ELSE 0 END) as recent_delq FROM current_loans c JOIN clean_monthly_performance p ON c.loan_id = p.loan_id WHERE p.monthly_reporting_period BETWEEN 201901 AND 201912 GROUP BY c.loan_id, c.upb)
    SELECT recent_delq, SUM(upb) as upb, COUNT(loan_id) as cnt FROM history GROUP BY recent_delq
    """
    prob_df = con.execute(q_prob).df()
    prob_upb_delq = prob_df[prob_df['recent_delq']==1]['upb'].values[0]
    prob_upb_clean = prob_df[prob_df['recent_delq']==0]['upb'].values[0]
    
    e1_prob = (prob_upb_clean * 0.00178 * LGD) + (prob_upb_delq * pd_s2_30 * LGD)
    total_prob = e1_prob + e2 + e3 + e4 + e5 + e6 + e7
    print(f"Total ECL WITH Probation: ${total_prob:,.0f}")
    
    # Overlap Query verification
    q_overlap = """
    WITH current_loans AS (SELECT loan_id FROM clean_monthly_performance WHERE monthly_reporting_period = 201912 AND loan_state = 'Current'),
    history AS (SELECT c.loan_id, MAX(CASE WHEN p.loan_state IN ('30_DPD', '60_DPD') THEN 1 ELSE 0 END) as recent_delq FROM current_loans c JOIN clean_monthly_performance p ON c.loan_id = p.loan_id WHERE p.monthly_reporting_period BETWEEN 201901 AND 201912 GROUP BY c.loan_id HAVING MAX(CASE WHEN p.loan_state IN ('30_DPD', '60_DPD') THEN 1 ELSE 0 END) = 1)
    SELECT COUNT(*) FROM history h JOIN clean_monthly_performance p2 ON h.loan_id = p2.loan_id WHERE p2.monthly_reporting_period = 201912 AND p2.loan_state = 'Modified'
    """
    print(f"Overlap: {con.execute(q_overlap).fetchone()[0]}")

if __name__ == "__main__":
    main()
