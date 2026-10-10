import duckdb
from src.markov import counts_df_to_array, build_markov_matrices

con = duckdb.connect('mortgage_risk.duckdb')

# 1. Post-cure transition matrix from earlier
q = """
WITH post_cure_perf AS (
    SELECT p.loan_id, p.loan_state, p.monthly_reporting_period
    FROM clean_monthly_performance p
    INNER JOIN (SELECT loan_id, MIN(monthly_reporting_period) as first_default_period 
                FROM clean_monthly_performance WHERE loan_state = 'Default' GROUP BY loan_id) f 
      ON p.loan_id = f.loan_id
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
C_post_cure = counts_df_to_array(counts_df)
Q, R, N, B, P = build_markov_matrices(C_post_cure, C_portfolio=C_post_cure)

# For 12m PD, we compute P^12
import numpy as np
def compute_12month_pd(Q, R):
    # This computes probability of hitting absorbing state 1 (Default) within 12 steps
    P_12 = np.zeros((3, 2))
    Q_k = np.eye(3)
    for _ in range(12):
        P_12 += Q_k @ R
        Q_k = Q_k @ Q
    return P_12[:, 1]

p12 = compute_12month_pd(Q, R)
print(f"Post-Cure 12m PD (Current): {p12[0]:.4f}")
print(f"Post-Cure Lifetime PD (Current): {B[0,1]:.4f}")
print(f"Post-Cure Lifetime PD (30 DPD): {B[1,1]:.4f}")
print(f"Post-Cure Lifetime PD (60 DPD): {B[2,1]:.4f}")

# 2. Recompute ECL
# Current LGD 36m midpoint is 0.0875 (under censor baseline)
lgd = 0.0875

q_cured = f"""
SELECT s.loan_id, s.loan_state, s.snapshot_upb
FROM ecl_snapshot s
WHERE s.loan_state != 'Default'
  AND s.loan_id IN (
      SELECT loan_id FROM clean_monthly_performance 
      WHERE monthly_reporting_period < 201912
        AND loan_state = 'Default'
  )
"""
cured_snapshot = con.execute(q_cured).df()

# Compute ECL using 12m PD for Current, Lifetime for 30/60 DPD
ecl_incremental = 0
for _, row in cured_snapshot.iterrows():
    upb = row['snapshot_upb']
    state = row['loan_state']
    
    if state == 'Current':
        pd_val = p12[0]
    elif state == '30_DPD':
        pd_val = B[1,1]
    elif state == '60_DPD':
        pd_val = B[2,1]
    else:
        continue
        
    ecl_incremental += upb * pd_val * lgd

print(f"\nTotal Cured UPB: ${cured_snapshot['snapshot_upb'].sum():,.2f}")
print(f"New Cured Loans ECL (12m PD for Current, 8.75% LGD): ${ecl_incremental:,.2f}")

# 3. Empirical redefault check at 12/24/36 months
q_emp = """
WITH cure_events AS (
    SELECT p.loan_id, MIN(p.monthly_reporting_period) as cure_period
    FROM clean_monthly_performance p
    INNER JOIN (SELECT loan_id, MIN(monthly_reporting_period) as first_default_period 
                FROM clean_monthly_performance WHERE loan_state = 'Default' GROUP BY loan_id) f 
      ON p.loan_id = f.loan_id
    WHERE p.monthly_reporting_period > f.first_default_period
      AND p.loan_state = 'Current'
    GROUP BY p.loan_id
)
SELECT 
    COUNT(c.loan_id) as total_cured,
    SUM(CASE WHEN d12.loan_id IS NOT NULL THEN 1 ELSE 0 END) as redefault_12m,
    SUM(CASE WHEN d24.loan_id IS NOT NULL THEN 1 ELSE 0 END) as redefault_24m,
    SUM(CASE WHEN d36.loan_id IS NOT NULL THEN 1 ELSE 0 END) as redefault_36m
FROM cure_events c
LEFT JOIN (
    SELECT DISTINCT p.loan_id
    FROM clean_monthly_performance p
    INNER JOIN cure_events c ON p.loan_id = c.loan_id
    WHERE p.loan_state = 'Default' 
      AND p.monthly_reporting_period > c.cure_period
      AND p.monthly_reporting_period <= CAST(CAST(c.cure_period AS INT) + 100 AS VARCHAR) -- approx 12 months (ignores year wrap for simplicity, better to use month_idx)
) d12_approx ON 1=0 -- Ignore, will write proper month_idx join below
"""

q_emp_proper = """
WITH cure_events AS (
    SELECT p.loan_id, MIN(p.monthly_reporting_period) as cure_period
    FROM clean_monthly_performance p
    INNER JOIN (SELECT loan_id, MIN(monthly_reporting_period) as first_default_period 
                FROM clean_monthly_performance WHERE loan_state = 'Default' GROUP BY loan_id) f 
      ON p.loan_id = f.loan_id
    WHERE p.monthly_reporting_period > f.first_default_period
      AND p.loan_state = 'Current'
    GROUP BY p.loan_id
),
redefault_times AS (
    SELECT p.loan_id, MIN(month_idx(p.monthly_reporting_period) - month_idx(c.cure_period)) as months_to_redefault
    FROM clean_monthly_performance p
    INNER JOIN cure_events c ON p.loan_id = c.loan_id
    WHERE p.loan_state = 'Default'
      AND p.monthly_reporting_period > c.cure_period
    GROUP BY p.loan_id
)
SELECT 
    COUNT(c.loan_id) as total_cured_loans,
    SUM(CASE WHEN r.months_to_redefault <= 12 THEN 1 ELSE 0 END) as redefault_12m,
    SUM(CASE WHEN r.months_to_redefault <= 24 THEN 1 ELSE 0 END) as redefault_24m,
    SUM(CASE WHEN r.months_to_redefault <= 36 THEN 1 ELSE 0 END) as redefault_36m
FROM cure_events c
LEFT JOIN redefault_times r ON c.loan_id = r.loan_id
"""
con.execute("""
CREATE OR REPLACE MACRO month_idx(yyyymm) AS 
CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 1, 4) AS INT) * 12 + CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 5, 2) AS INT);
""")

df_emp = con.execute(q_emp_proper).df()
t = df_emp['total_cured_loans'][0]
r12 = df_emp['redefault_12m'][0]
r24 = df_emp['redefault_24m'][0]
r36 = df_emp['redefault_36m'][0]

print(f"\nEmpirical Redefault Rates (out of {t} cured loans):")
print(f"12m: {r12/t*100:.2f}%")
print(f"24m: {r24/t*100:.2f}%")
print(f"36m: {r36/t*100:.2f}%")
