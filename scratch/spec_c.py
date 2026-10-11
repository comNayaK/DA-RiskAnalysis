import duckdb
import pandas as pd
import numpy as np
import math
from src.db import get_connection

con = get_connection("mortgage_risk.duckdb")

# Compute pooled clean-history default rate for snapshots <= 201712:
# Snapshots: 201412 (eval 2015), 201512 (eval 2016), 201612 (eval 2017)
# And 201712 (eval 2018)
print("=== Clean History Default Rates Across Snapshots ===")
tot_clean_obs_pre18 = 0
tot_clean_defs_pre18 = 0

tot_clean_obs_pre17 = 0
tot_clean_defs_pre17 = 0

for snap_yr in [2014, 2015, 2016, 2017]:
    eval_yr = snap_yr + 1
    q_dir = f"""
    WITH curr AS (
        SELECT loan_id FROM clean_monthly_performance 
        WHERE monthly_reporting_period = {snap_yr}12 AND loan_state = 'Current' AND zero_balance_code IS NULL
    ),
    hist AS (
        SELECT c.loan_id, MAX(CASE WHEN p.loan_state IN ('30_DPD', '60_DPD') THEN 1 ELSE 0 END) as had_delinq
        FROM curr c
        JOIN clean_monthly_performance p ON c.loan_id = p.loan_id
        WHERE p.monthly_reporting_period BETWEEN {snap_yr}01 AND {snap_yr}12
        GROUP BY c.loan_id
    ),
    defs AS (
        SELECT DISTINCT loan_id FROM clean_monthly_performance
        WHERE monthly_reporting_period BETWEEN {eval_yr}01 AND {eval_yr}12 AND loan_state = 'Default'
    )
    SELECT h.had_delinq, COUNT(*) as obs, SUM(CASE WHEN d.loan_id IS NOT NULL THEN 1 ELSE 0 END) as defs
    FROM hist h LEFT JOIN defs d ON h.loan_id = d.loan_id
    GROUP BY h.had_delinq
    """
    res = con.execute(q_dir).df()
    clean_obs = res[res['had_delinq']==0]['obs'].values[0] if 0 in res['had_delinq'].values else 0
    clean_defs = res[res['had_delinq']==0]['defs'].values[0] if 0 in res['had_delinq'].values else 0
    
    if snap_yr < 2017:
        tot_clean_obs_pre17 += clean_obs
        tot_clean_defs_pre17 += clean_defs
    tot_clean_obs_pre18 += clean_obs
    tot_clean_defs_pre18 += clean_defs
    
    print(f"Snap {snap_yr}12 -> {eval_yr}: Obs = {clean_obs:,}, Defs = {clean_defs}, PD = {clean_defs/clean_obs:.4%}")

pd_pre17 = tot_clean_defs_pre17 / tot_clean_obs_pre17
pd_pre18 = tot_clean_defs_pre18 / tot_clean_obs_pre18
print(f"\nPooled Snapshots <= 201612 (eval <= 2017): Obs = {tot_clean_obs_pre17:,}, Defs = {tot_clean_defs_pre17}, PD = {pd_pre17:.4%}")
print(f"Pooled Snapshots <= 201712 (eval <= 2018): Obs = {tot_clean_obs_pre18:,}, Defs = {tot_clean_defs_pre18}, PD = {pd_pre18:.4%}")

# Let's run backtest scoring for Specification C (using pooled <= 2017 rate pd_pre17)
# Pop 1 Current: 191,476 loans
exp_c = 191476 * pd_pre17
var_c = 191476 * pd_pre17 * (1 - pd_pre17)
act_c = 340
z_c = (act_c - exp_c) / math.sqrt(var_c)
print(f"\nSpecification C (Pop 1 Current @ {pd_pre17:.4%}): Exp = {exp_c:.1f}, Act = {act_c}, Z = {z_c:+.2f}σ")

# Portfolio Total under Specification C (with Pop 2 and Pop 1 delinquencies as in A)
exp_other = 151.6 + 130.0 + 55.0 + 59.2 + 69.2 + 137.0
var_other = (1255*0.1208*(1-0.1208)) + (220*0.5909*(1-0.5909)) + (636*0.0865*(1-0.0865)) + (115*0.515*(1-0.515)) + (87*0.7949*(1-0.7949)) + (1136*0.1206*(1-0.1206))
act_other = 170 + 136 + 55 + 34 + 58 + 119

tot_exp_c = exp_c + exp_other
tot_var_c = var_c + var_other
tot_act_c = act_c + act_other
z_tot_c = (tot_act_c - tot_exp_c) / math.sqrt(tot_var_c)

print(f"Portfolio Total C: Exp = {tot_exp_c:.1f}, Act = {tot_act_c}, Z = {z_tot_c:+.2f}σ")
