import duckdb
import pandas as pd
import numpy as np
import math

def run_prod_backtest():
    con = duckdb.connect("mortgage_risk.duckdb", read_only=True)

    print("=== 1. POP 1 CURRENT SPLIT AT 201812 SNAPSHOT ===")
    # At 201812 snapshot, split Pop 1 Current (191,476 loans) into Clean vs Recent Delinquency
    q_split_18 = """
    WITH curr_18 AS (
        SELECT p.loan_id
        FROM clean_monthly_performance p
        WHERE p.monthly_reporting_period = 201812 AND p.loan_state = 'Current' AND p.zero_balance_code IS NULL
          -- Exclude Pop 2 loans (modified or defaulted <= 201812)
          AND p.loan_id NOT IN (
              SELECT loan_id FROM clean_monthly_performance WHERE monthly_reporting_period <= 201812 AND loan_state IN ('Modified', 'Default')
              UNION
              SELECT loan_id FROM raw_performance WHERE COALESCE(modification_flag, '') IN ('Y', 'P') AND CAST(monthly_reporting_period AS INT) <= 201812
          )
    ),
    hist_18 AS (
        SELECT c.loan_id,
               MAX(CASE WHEN p.loan_state IN ('30_DPD', '60_DPD') THEN 1 ELSE 0 END) as had_delinq
        FROM curr_18 c
        JOIN clean_monthly_performance p ON c.loan_id = p.loan_id
        WHERE p.monthly_reporting_period BETWEEN 201801 AND 201812
        GROUP BY c.loan_id
    ),
    defs_19 AS (
        SELECT DISTINCT loan_id 
        FROM clean_monthly_performance 
        WHERE monthly_reporting_period BETWEEN 201901 AND 201912 AND loan_state = 'Default'
    )
    SELECT 
        h.had_delinq,
        COUNT(h.loan_id) as obs,
        COUNT(d.loan_id) as act_defs,
        COUNT(d.loan_id) * 1.0 / COUNT(h.loan_id) as realized_rate
    FROM hist_18 h
    LEFT JOIN defs_19 d ON h.loan_id = d.loan_id
    GROUP BY h.had_delinq
    """
    df_split_18 = con.execute(q_split_18).df()
    print(df_split_18)

    # Check total Pop 1 Current loans at 201812
    tot_curr = df_split_18['obs'].sum()
    tot_defs = df_split_18['act_defs'].sum()
    print(f"Total Pop 1 Current at 201812: Obs = {tot_curr:,}, Actual Defaults = {tot_defs}")

    # Now let's score the production structure:
    # Clean loans (had_delinq = 0): scored at frozen clean-history rate 0.1560% (or 0.160%)
    # Recently delinquent (had_delinq = 1): scored at frozen recent-delinquency 12m rate (e.g. 2018 observed 3.2236%, or 2015-2018 pooled ~3.45%)
    clean_obs = df_split_18[df_split_18['had_delinq']==0]['obs'].values[0]
    clean_act = df_split_18[df_split_18['had_delinq']==0]['act_defs'].values[0]
    delq_obs = df_split_18[df_split_18['had_delinq']==1]['obs'].values[0]
    delq_act = df_split_18[df_split_18['had_delinq']==1]['act_defs'].values[0]

    p_clean = 0.001560 # 0.156%
    p_delq = 0.032236  # 3.224% from 2018

    exp_clean = clean_obs * p_clean
    var_clean = clean_obs * p_clean * (1 - p_clean)
    z_clean = (clean_act - exp_clean) / math.sqrt(var_clean)

    exp_delq = delq_obs * p_delq
    var_delq = delq_obs * p_delq * (1 - p_delq)
    z_delq = (delq_act - exp_delq) / math.sqrt(var_delq)

    tot_curr_exp = exp_clean + exp_delq
    tot_curr_var = var_clean + var_delq
    tot_curr_z = (tot_defs - tot_curr_exp) / math.sqrt(tot_curr_var)

    print(f"\nProduction Structure Scoring for Pop 1 Current:")
    print(f"  Clean:     Obs={clean_obs:,} PD={p_clean:.4%} Exp={exp_clean:.1f} Act={clean_act} Z={z_clean:+.2f}σ")
    print(f"  Probation: Obs={delq_obs:,} PD={p_delq:.4%} Exp={exp_delq:.1f} Act={delq_act} Z={z_delq:+.2f}σ")
    print(f"  Total Current: Obs={tot_curr:,} Exp={tot_curr_exp:.1f} Act={tot_defs} Z={tot_curr_z:+.2f}σ")

if __name__ == "__main__":
    run_prod_backtest()
