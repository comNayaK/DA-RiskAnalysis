import duckdb
from src.db import get_connection

def main():
    con = get_connection("mortgage_risk.duckdb")
    
    q1 = """
    WITH p2_loans AS (
        SELECT loan_id FROM clean_monthly_performance WHERE monthly_reporting_period = 201912 AND loan_state = 'Modified'
    )
    SELECT 'Pop1_Stage1' as segment, SUM(current_actual_upb) as upb FROM clean_monthly_performance 
    WHERE monthly_reporting_period = 201912 AND loan_state = 'Current' AND loan_id NOT IN (SELECT loan_id FROM p2_loans)
    """
    pop1_s1_upb = con.execute(q1).fetchone()[1]
    
    q3 = "SELECT loan_state, SUM(current_actual_upb) as upb FROM clean_monthly_performance WHERE monthly_reporting_period = 201912 AND loan_state IN ('30_DPD', '60_DPD') AND loan_id NOT IN (SELECT loan_id FROM clean_monthly_performance WHERE monthly_reporting_period = 201912 AND loan_state = 'Modified') GROUP BY loan_state"
    df3 = con.execute(q3).df()
    pop1_30 = df3[df3['loan_state']=='30_DPD']['upb'].values[0] if '30_DPD' in df3['loan_state'].values else 0
    pop1_60 = df3[df3['loan_state']=='60_DPD']['upb'].values[0] if '60_DPD' in df3['loan_state'].values else 0
    
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
    
    pop3_upb = con.execute("SELECT SUM(current_actual_upb) FROM clean_monthly_performance WHERE monthly_reporting_period = 201912 AND loan_state = 'Default'").fetchone()[0]

    LGD = 0.115
    TAIL = 11050033.90
    
    ecl_pop1_s1 = pop1_s1_upb * 0.00218 * LGD
    ecl_pop1_s2_30 = pop1_30 * 0.1224 * LGD
    ecl_pop1_s2_60 = pop1_60 * 0.5259 * LGD
    
    ecl_pop2_00 = pop2_00 * 0.1224 * LGD
    ecl_pop2_01 = pop2_01 * 0.7338 * LGD
    ecl_pop2_02 = pop2_02 * 0.8450 * LGD
    
    ecl_pop3 = pop3_upb * 1.0 * LGD
    
    total = ecl_pop1_s1 + ecl_pop1_s2_30 + ecl_pop1_s2_60 + ecl_pop2_00 + ecl_pop2_01 + ecl_pop2_02 + ecl_pop3 + TAIL
    
    print(f"| Segment | UPB | Lifetime PD | LGD Base | ECL |")
    print(f"|---|---|---|---|---|")
    print(f"| Pop 1 Stage 1 | ${pop1_s1_upb:,.0f} | 0.218% | 11.5% | ${ecl_pop1_s1:,.0f} |")
    print(f"| Pop 1 Stage 2 (30 DPD) | ${pop1_30:,.0f} | 12.24% | 11.5% | ${ecl_pop1_s2_30:,.0f} |")
    print(f"| Pop 1 Stage 2 (60 DPD) | ${pop1_60:,.0f} | 52.59% | 11.5% | ${ecl_pop1_s2_60:,.0f} |")
    print(f"| Pop 2 Current | ${pop2_00:,.0f} | 12.24% | 11.5% | ${ecl_pop2_00:,.0f} |")
    print(f"| Pop 2 30 DPD | ${pop2_01:,.0f} | 73.38% | 11.5% | ${ecl_pop2_01:,.0f} |")
    print(f"| Pop 2 60 DPD | ${pop2_02:,.0f} | 84.50% | 11.5% | ${ecl_pop2_02:,.0f} |")
    print(f"| Pop 3 (Default) | ${pop3_upb:,.0f} | 100.0% | 11.5% | ${ecl_pop3:,.0f} |")
    print(f"| Mod Re-default Tail | - | - | - | ${TAIL:,.0f} |")
    print(f"| **Total** | **$28,708,141,480** | | | **${total:,.0f}** |")

if __name__ == "__main__":
    main()
