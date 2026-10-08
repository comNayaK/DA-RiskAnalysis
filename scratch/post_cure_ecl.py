import duckdb
import pandas as pd
import numpy as np
from src.markov import counts_df_to_array, build_markov_matrices
from src.config import LGD_24M_COHORT_CUTOFF, ECL_SNAPSHOT_PERIOD

con = duckdb.connect('mortgage_risk.duckdb')

# 1. Get post-cure transition matrix
# To do this safely with month arithmetic, we can just join t1 and t2 where t2.monthly_reporting_period is the immediate next reporting period.
q = """
WITH post_cure_perf AS (
    SELECT p.loan_id, p.loan_state, p.monthly_reporting_period
    FROM clean_monthly_performance p
    INNER JOIN v_first_default f ON p.loan_id = f.loan_id
    WHERE p.monthly_reporting_period > f.first_default_period
),
ranked_perf AS (
    SELECT loan_id, loan_state, 
           ROW_NUMBER() OVER (PARTITION BY loan_id ORDER BY monthly_reporting_period) as rn
    FROM post_cure_perf
),
post_cure_transitions AS (
    SELECT 
        t1.loan_state AS state_t,
        t2.loan_state AS state_t_plus_1
    FROM ranked_perf t1
    INNER JOIN ranked_perf t2 
      ON t1.loan_id = t2.loan_id 
     AND t2.rn = t1.rn + 1
)
SELECT state_t, state_t_plus_1, COUNT(*) as n
FROM post_cure_transitions
WHERE state_t IN ('Current', '30_DPD', '60_DPD')
  AND state_t_plus_1 IN ('Current', '30_DPD', '60_DPD', 'Default', 'Paid_Off')
GROUP BY state_t, state_t_plus_1
"""

counts_df = con.execute(q).df()
print("--- Post-Cure Transition Counts ---")
print(counts_df)

C_post_cure = counts_df_to_array(counts_df)
Q, R, N, B, P = build_markov_matrices(C_post_cure, C_portfolio=C_post_cure)

print("\n--- Post-Cure Lifetime PDs ---")
print(f"Current: {B[0,1]:.4f}")
print(f"30_DPD : {B[1,1]:.4f}")
print(f"60_DPD : {B[2,1]:.4f}")

# 2. Get LGD 36m headline
lgd_36 = 0.1368  # From our output

# 3. Get the 753 cured loans from the snapshot
q_cured = f"""
SELECT s.loan_id, s.loan_state, s.snapshot_upb
FROM ecl_snapshot s
WHERE s.loan_state != 'Default'
  AND s.loan_id IN (
      SELECT loan_id FROM clean_monthly_performance 
      WHERE monthly_reporting_period < {ECL_SNAPSHOT_PERIOD}
        AND loan_state = 'Default'
  )
"""
cured_snapshot = con.execute(q_cured).df()

# 4. Compute their new ECL
ecl = 0
for _, row in cured_snapshot.iterrows():
    upb = row['snapshot_upb']
    state = row['loan_state']
    
    if state == 'Current':
        pd_val = B[0,1]
    elif state == '30_DPD':
        pd_val = B[1,1]
    elif state == '60_DPD':
        pd_val = B[2,1]
    else:
        continue
        
    ecl += upb * pd_val * lgd_36

print(f"\n--- Cured Loans Snapshot Info ---")
print(f"Total Cured Loans: {len(cured_snapshot)}")
print(f"Total Cured UPB: ${cured_snapshot['snapshot_upb'].sum():,.2f}")
print(f"New Cured Loans ECL (using post-cure matrix): ${ecl:,.2f}")
