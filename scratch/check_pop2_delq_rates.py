import duckdb
from src.db import get_connection

con = get_connection("mortgage_risk.duckdb")

q_pop2_delq = """
WITH p2_loans AS (
    SELECT DISTINCT loan_id FROM clean_monthly_performance WHERE loan_state = 'Modified'
),
events AS (
    SELECT 
        CAST(SUBSTRING(r.monthly_reporting_period, 1, 4) AS INT) as snap_year,
        r.current_delinquency_status as raw_delq,
        r.loan_id
    FROM raw_performance r
    JOIN p2_loans p2 ON r.loan_id = p2.loan_id
    WHERE r.current_delinquency_status IN ('01', '02')
      AND SUBSTRING(r.monthly_reporting_period, 5, 2) = '12'
      AND CAST(SUBSTRING(r.monthly_reporting_period, 1, 4) AS INT) BETWEEN 2014 AND 2018
),
defs AS (
    SELECT p.loan_id, CAST(SUBSTRING(CAST(p.monthly_reporting_period AS VARCHAR), 1, 4) AS INT) as def_year
    FROM clean_monthly_performance p
    WHERE p.loan_state = 'Default'
)
SELECT 
    e.snap_year + 1 as eval_year,
    e.raw_delq,
    COUNT(DISTINCT e.loan_id) as obs,
    COUNT(DISTINCT CASE WHEN d.loan_id IS NOT NULL AND d.def_year = e.snap_year + 1 THEN e.loan_id END) as defs
FROM events e
LEFT JOIN defs d ON e.loan_id = d.loan_id
GROUP BY 1, 2
ORDER BY 1, 2
"""
df_p2 = con.execute(q_pop2_delq).df()
print("Pop 2 Delinquent 12m Default Rates by Evaluation Year:")
print(df_p2)

# Summarize <= 201812 vs 2015-2019
obs_30_pre19 = df_p2[(df_p2['raw_delq']=='01') & (df_p2['eval_year'] <= 2018)]['obs'].sum()
defs_30_pre19 = df_p2[(df_p2['raw_delq']=='01') & (df_p2['eval_year'] <= 2018)]['defs'].sum()
obs_60_pre19 = df_p2[(df_p2['raw_delq']=='02') & (df_p2['eval_year'] <= 2018)]['obs'].sum()
defs_60_pre19 = df_p2[(df_p2['raw_delq']=='02') & (df_p2['eval_year'] <= 2018)]['defs'].sum()

print(f"\nPooled <= 201812 (Eval 2015-2018):")
print(f"  30 DPD ('01'): {defs_30_pre19} / {obs_30_pre19} = {defs_30_pre19/obs_30_pre19:.2%}")
print(f"  60 DPD ('02'): {defs_60_pre19} / {obs_60_pre19} = {defs_60_pre19/obs_60_pre19:.2%}")

obs_30_all = df_p2[df_p2['raw_delq']=='01']['obs'].sum()
defs_30_all = df_p2[df_p2['raw_delq']=='01']['defs'].sum()
obs_60_all = df_p2[df_p2['raw_delq']=='02']['obs'].sum()
defs_60_all = df_p2[df_p2['raw_delq']=='02']['defs'].sum()

print(f"\nPooled 2015-2019:")
print(f"  30 DPD ('01'): {defs_30_all} / {obs_30_all} = {defs_30_all/obs_30_all:.2%}")
print(f"  60 DPD ('02'): {defs_60_all} / {obs_60_all} = {defs_60_all/obs_60_all:.2%}")

r19_30 = df_p2[(df_p2['raw_delq']=='01') & (df_p2['eval_year'] == 2019)]
r19_60 = df_p2[(df_p2['raw_delq']=='02') & (df_p2['eval_year'] == 2019)]
print(f"\n2019 Realized Rates:")
print(f"  30 DPD ('01'): {r19_30['defs'].values[0]} / {r19_30['obs'].values[0]} = {r19_30['defs'].values[0]/r19_30['obs'].values[0]:.2%}")
print(f"  60 DPD ('02'): {r19_60['defs'].values[0]} / {r19_60['obs'].values[0]} = {r19_60['defs'].values[0]/r19_60['obs'].values[0]:.2%}")
