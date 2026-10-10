import duckdb
import pandas as pd
import numpy as np

con = duckdb.connect('mortgage_risk.duckdb')
con.execute("""
CREATE OR REPLACE MACRO month_idx(yyyymm) AS 
CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 1, 4) AS INT) * 12 + CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 5, 2) AS INT);
""")

from src.layers import build_layer1_clean_performance, build_layer2_truncated_performance, build_layer3_transitions, build_ecl_snapshot
from src.markov import counts_df_to_array, build_markov_matrices, compute_12month_pd
from src.config import BACKTEST_TRAIN_CUTOFF, PRE_COVID_CUTOFF

# 1. Base Matrix (Pop 1) using CENSOR logic (to not drop defaults prior to modification)
print("Building Base Matrix (Censor logic)...")
build_layer1_clean_performance(con, mod_policy='censor')
build_layer2_truncated_performance(con, mod_policy='censor')
build_layer3_transitions(con)

df_port_train = con.execute(f"SELECT state_t, state_t_plus_1, COUNT(*) as n FROM loan_level_transitions WHERE monthly_reporting_period <= {BACKTEST_TRAIN_CUTOFF} GROUP BY 1,2").df()
C_train = counts_df_to_array(df_port_train)
Q_train, R_train, _, _, _ = build_markov_matrices(C_train)
base_pd_12m = compute_12month_pd(Q_train, R_train)
print(f"Base Matrix 12m PD (Current): {base_pd_12m:.4f}")

# 2. Build Event Tracking for Pop 2 (using Universal keep logic to see everything)
print("Building Event Tracking (Keep logic)...")
build_layer1_clean_performance(con, mod_policy='keep')

q_events = """
CREATE OR REPLACE TABLE event_tracking AS
WITH first_default AS (
    SELECT loan_id, MIN(monthly_reporting_period) as fd
    FROM clean_monthly_performance WHERE loan_state = 'Default' GROUP BY loan_id
),
first_mod AS (
    SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as fm
    FROM raw_performance WHERE COALESCE(modification_flag, '') IN ('Y', 'P') GROUP BY loan_id
),
cure_events AS (
    SELECT p.loan_id, MIN(p.monthly_reporting_period) as event_date, 'Cure' as event_type
    FROM clean_monthly_performance p
    INNER JOIN first_default f ON p.loan_id = f.loan_id
    WHERE p.monthly_reporting_period > f.fd AND p.loan_state = 'Current'
    GROUP BY p.loan_id
),
mod_events AS (
    SELECT loan_id, fm as event_date, 'Mod' as event_type
    FROM first_mod
)
SELECT * FROM cure_events
UNION ALL
SELECT * FROM mod_events m
WHERE NOT EXISTS (SELECT 1 FROM cure_events c WHERE c.loan_id = m.loan_id AND c.event_date <= m.event_date)
"""
con.execute(q_events)

# Compute Hazard by event_type and t_months
q_hazard = """
WITH survived_t AS (
    SELECT 
        e.loan_id, e.event_date, e.event_type, t.t_months
    FROM event_tracking e
    CROSS JOIN (SELECT UNNEST(GENERATE_SERIES(0, 72)) AS t_months) t
    WHERE month_idx(202002) - month_idx(e.event_date) >= t.t_months + 12
      AND NOT EXISTS (
          SELECT 1 FROM clean_monthly_performance p 
          WHERE p.loan_id = e.loan_id 
            AND p.loan_state = 'Default' 
            AND month_idx(p.monthly_reporting_period) > month_idx(e.event_date)
            AND month_idx(p.monthly_reporting_period) <= month_idx(e.event_date) + t.t_months
      )
),
defaulted_next_12 AS (
    SELECT s.loan_id, s.event_type, s.t_months
    FROM survived_t s
    WHERE EXISTS (
        SELECT 1 FROM clean_monthly_performance p
        WHERE p.loan_id = s.loan_id
          AND p.loan_state = 'Default'
          AND month_idx(p.monthly_reporting_period) > month_idx(s.event_date) + s.t_months
          AND month_idx(p.monthly_reporting_period) <= month_idx(s.event_date) + s.t_months + 12
    )
)
SELECT 
    s.event_type, s.t_months,
    COUNT(s.loan_id) as survived_count,
    COUNT(d.loan_id) as default_count,
    COUNT(d.loan_id) * 1.0 / NULLIF(COUNT(s.loan_id), 0) as hazard_12m
FROM survived_t s
LEFT JOIN defaulted_next_12 d ON s.loan_id = d.loan_id AND s.t_months = d.t_months
GROUP BY s.event_type, s.t_months
ORDER BY s.event_type, s.t_months
"""
df_haz = con.execute(q_hazard).df()
haz_cure = dict(zip(df_haz[df_haz['event_type']=='Cure']['t_months'], df_haz[df_haz['event_type']=='Cure']['hazard_12m']))
haz_mod = dict(zip(df_haz[df_haz['event_type']=='Mod']['t_months'], df_haz[df_haz['event_type']=='Mod']['hazard_12m']))

print("\nHazard Cure (t=0,12,24):", haz_cure.get(0), haz_cure.get(12), haz_cure.get(24))
print("Hazard Mod (t=0,12,24):", haz_mod.get(0), haz_mod.get(12), haz_mod.get(24))

def get_pop_and_pd(row, snap_date):
    if row['loan_state'] == 'Default':
        return 'Pop3_Default', 1.0
    if pd.notnull(row['event_date']) and row['months_since_event'] >= 0:
        t = int(row['months_since_event'])
        h_dict = haz_cure if row['event_type'] == 'Cure' else haz_mod
        base_pd = h_dict.get(t, h_dict.get(72, 0))
        if pd.isna(base_pd): base_pd = 0
        if row['loan_state'] == 'Current': return f"Pop2_{row['event_type']}", base_pd
        elif row['loan_state'] == '30_DPD': return f"Pop2_{row['event_type']}", min(1.0, base_pd * 2)
        else: return f"Pop2_{row['event_type']}", min(1.0, base_pd * 4)
    return 'Pop1_Base', base_pd_12m

# 3. Backtest on 201812 Snapshot
print("\nRunning Backtest on 201812 Snapshot...")
q_oos = """
SELECT 
    s.loan_id, p.loan_state, e.event_type, e.event_date,
    month_idx(201812) - month_idx(e.event_date) as months_since_event,
    (SELECT COUNT(*) FROM clean_monthly_performance d 
     WHERE d.loan_id = s.loan_id AND d.loan_state = 'Default' 
       AND d.monthly_reporting_period BETWEEN 201901 AND 201912) > 0 as actual_default
FROM oos_snapshot_201812 s
INNER JOIN clean_monthly_performance p ON s.loan_id = p.loan_id AND p.monthly_reporting_period = 201812
LEFT JOIN event_tracking e ON s.loan_id = e.loan_id AND e.event_date <= 201812
"""
df_oos = con.execute(q_oos).df()

results = []
for idx, row in df_oos.iterrows():
    pop, exp_pd = get_pop_and_pd(row, 201812)
    df_oos.at[idx, 'pop'] = pop
    df_oos.at[idx, 'exp_pd'] = exp_pd

for p_name in sorted(df_oos['pop'].unique()):
    sub = df_oos[df_oos['pop'] == p_name]
    cnt = len(sub)
    exp = sub['exp_pd'].sum()
    act = sub['actual_default'].sum()
    z = (act - exp) / np.sqrt(exp) if exp > 0 else 0
    print(f"{p_name}: N={cnt}, Exp={exp:.1f}, Act={act}, Z={z:.2f}")

# 4. LGD bounds and scenario table
print("\nComputing LGDs...")
build_layer1_clean_performance(con, mod_policy='keep') # ensure universal
from src.lgd import build_lgd_views, compute_lgd_bounds
build_lgd_views(con)
l36, u36, m36 = compute_lgd_bounds(con)
print(f"Universal LGD 36m Range: [{l36:.4f}, {u36:.4f}]")
