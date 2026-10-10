import duckdb
import numpy as np

con = duckdb.connect('mortgage_risk.duckdb')

# 1. Reproduce Purge baseline LGD & ECL
from src.layers import build_layer1_clean_performance, build_layer2_truncated_performance, build_layer3_transitions, build_ecl_snapshot
from src.lgd import build_lgd_views, compute_lgd_bounds

# Build layers
build_layer1_clean_performance(con)
build_layer2_truncated_performance(con)
build_lgd_views(con)
l36, u36, m36 = compute_lgd_bounds(con)
print(f"Purge Baseline LGD 36m Midpoint: {m36:.4f}")

# 2. Re-default empirical hazard for cured loans with FULL follow-up
con.execute("""
CREATE OR REPLACE MACRO month_idx(yyyymm) AS 
CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 1, 4) AS INT) * 12 + CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 5, 2) AS INT);
""")

q_emp_decay = """
WITH cure_events AS (
    SELECT p.loan_id, MIN(p.monthly_reporting_period) as cure_period
    FROM clean_monthly_performance p
    INNER JOIN (SELECT loan_id, MIN(monthly_reporting_period) as first_default_period 
                FROM clean_monthly_performance WHERE loan_state = 'Default' AND first_mod_period IS NULL GROUP BY loan_id) f 
      ON p.loan_id = f.loan_id
    WHERE p.monthly_reporting_period > f.first_default_period
      AND p.loan_state = 'Current'
    GROUP BY p.loan_id
),
valid_cures AS (
    -- Only include loans whose cure period allows for full 36m follow-up before 202002
    SELECT * FROM cure_events 
    WHERE month_idx(202002) - month_idx(cure_period) >= 36
),
redefault_times AS (
    SELECT p.loan_id, MIN(month_idx(p.monthly_reporting_period) - month_idx(c.cure_period)) as months_to_redefault
    FROM clean_monthly_performance p
    INNER JOIN valid_cures c ON p.loan_id = c.loan_id
    WHERE p.loan_state = 'Default'
      AND p.monthly_reporting_period > c.cure_period
    GROUP BY p.loan_id
)
SELECT 
    COUNT(c.loan_id) as total_cured_loans,
    SUM(CASE WHEN r.months_to_redefault <= 12 THEN 1 ELSE 0 END) as redefault_12m,
    SUM(CASE WHEN r.months_to_redefault <= 24 THEN 1 ELSE 0 END) as redefault_24m,
    SUM(CASE WHEN r.months_to_redefault <= 36 THEN 1 ELSE 0 END) as redefault_36m
FROM valid_cures c
LEFT JOIN redefault_times r ON c.loan_id = r.loan_id
"""
df_emp = con.execute(q_emp_decay).df()
print("Empirical Redefault (Full 36m follow-up):")
print(df_emp)

# Snapshot Reconcile
q_snap = """
SELECT 
    COUNT(*) as snap_count,
    SUM(snapshot_upb) as total_upb
FROM ecl_snapshot
"""
df_snap = con.execute(q_snap).df()
print(f"Snapshot Total: {df_snap['snap_count'][0]} / ${df_snap['total_upb'][0]:,.2f}")

q_mod_snap = """
SELECT 
    SUM(CASE WHEN m.mod_period = 201912 THEN 1 ELSE 0 END) as mod_exact_201912,
    SUM(CASE WHEN m.mod_period > 201912 THEN 1 ELSE 0 END) as mod_after_201912
FROM ecl_snapshot s
LEFT JOIN (
    SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as mod_period
    FROM raw_performance WHERE COALESCE(modification_flag, '') IN ('Y', 'P') GROUP BY loan_id
) m ON s.loan_id = m.loan_id
"""
df_mod_snap = con.execute(q_mod_snap).df()
print(f"Mods exactly in 201912: {df_mod_snap['mod_exact_201912'][0]}")
print(f"Mods strictly after 201912: {df_mod_snap['mod_after_201912'][0]}")

# Excluded loans already modified before 201912
q_excluded = """
WITH mod_dates AS (
    SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as mod_period
    FROM raw_performance WHERE COALESCE(modification_flag, '') IN ('Y', 'P') GROUP BY loan_id
)
SELECT COUNT(*) as excluded_count, SUM(TRY_CAST(current_actual_upb AS DOUBLE)) as excluded_upb
FROM raw_performance r
INNER JOIN mod_dates m ON r.loan_id = m.loan_id
WHERE r.monthly_reporting_period = 201912
  AND m.mod_period <= 201912
  AND r.zero_balance_code IS NULL
"""
df_exc = con.execute(q_excluded).df()
print(f"Already Modified Excluded from Snapshot: {df_exc['excluded_count'][0]} / ${df_exc['excluded_upb'][0]:,.2f}")
