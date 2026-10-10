import duckdb
import pandas as pd

con = duckdb.connect('mortgage_risk.duckdb')
con.execute("""
CREATE OR REPLACE MACRO month_idx(yyyymm) AS 
CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 1, 4) AS INT) * 12 + CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 5, 2) AS INT);
""")

# Build universal base for LGD and Event tracking
from src.layers import build_layer1_clean_performance, build_ecl_snapshot
build_layer1_clean_performance(con, mod_policy='keep')

# 1. Identify cure and mod events
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
WHERE NOT EXISTS (SELECT 1 FROM cure_events c WHERE c.loan_id = m.loan_id)
"""
con.execute(q_events)

# 2. Hazard Curve by months_since_event (t)
q_hazard = """
WITH survived_t AS (
    SELECT 
        e.loan_id, 
        e.event_date,
        t.t_months
    FROM event_tracking e
    CROSS JOIN (SELECT UNNEST(GENERATE_SERIES(0, 60)) AS t_months) t
    WHERE month_idx(202002) - month_idx(e.event_date) >= t.t_months + 12
      -- Check survival to t
      AND NOT EXISTS (
          SELECT 1 FROM clean_monthly_performance p 
          WHERE p.loan_id = e.loan_id 
            AND p.loan_state = 'Default' 
            AND month_idx(p.monthly_reporting_period) > month_idx(e.event_date)
            AND month_idx(p.monthly_reporting_period) <= month_idx(e.event_date) + t.t_months
      )
),
defaulted_next_12 AS (
    SELECT 
        s.loan_id, s.t_months
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
    s.t_months,
    COUNT(s.loan_id) as survived_count,
    COUNT(d.loan_id) as default_count,
    COUNT(d.loan_id) * 1.0 / NULLIF(COUNT(s.loan_id), 0) as hazard_12m
FROM survived_t s
LEFT JOIN defaulted_next_12 d ON s.loan_id = d.loan_id AND s.t_months = d.t_months
GROUP BY s.t_months
ORDER BY s.t_months
"""
df_hazard = con.execute(q_hazard).df()
print("Empirical Hazard Curve (12m PD by months since event):")
print(df_hazard.head(24))

# 3. Snapshot Populations & ECL
# Get empirical LGD
from src.lgd import build_lgd_views, compute_lgd_bounds
build_lgd_views(con)
l36, u36, m36 = compute_lgd_bounds(con)
print(f"\nUniversal Empirical LGD: {m36:.4f}")
lgd = m36

build_ecl_snapshot(con)

# Get base matrix PDs
from src.layers import build_layer2_truncated_performance, build_layer3_transitions
build_layer1_clean_performance(con, mod_policy='purge') # Rebuild purge for matrix
build_layer2_truncated_performance(con)
build_layer3_transitions(con)
from src.markov import compute_fico_segmented_ecl
snapshot, pds, c_port = compute_fico_segmented_ecl(con, lgd)

# Attach event dates to snapshot
con.execute("""
CREATE OR REPLACE TABLE snap_eval AS
SELECT 
    s.*,
    e.event_date,
    month_idx(201912) - month_idx(e.event_date) as months_since_event
FROM ecl_snapshot s
LEFT JOIN event_tracking e ON s.loan_id = e.loan_id
""")

snap_df = con.execute("SELECT * FROM snap_eval").df()
hazard_dict = dict(zip(df_hazard['t_months'], df_hazard['hazard_12m']))
default_hazard = df_hazard['hazard_12m'].mean() if len(df_hazard) > 0 else 0

total_ecl = 0
for idx, row in snap_df.iterrows():
    if row['loan_state'] == 'Default':
        pd_val = 1.0
        pop = 'Pop3_Default'
    elif pd.notnull(row['event_date']) and row['months_since_event'] >= 0:
        # Pop 2: Post-event
        t = int(row['months_since_event'])
        if row['loan_state'] == 'Current':
            pd_val = hazard_dict.get(t, hazard_dict.get(60, 0))
        elif row['loan_state'] == '30_DPD':
            pd_val = hazard_dict.get(t, hazard_dict.get(60, 0)) * 2 # Crude staging scale or empirical
        else:
            pd_val = hazard_dict.get(t, hazard_dict.get(60, 0)) * 4
        pd_val = min(pd_val, 1.0)
        pop = 'Pop2_PostEvent'
    else:
        # Pop 1: Base
        fico = row['fico_band']
        state = row['loan_state']
        if fico in pds:
            if state == 'Current': pd_val = pds[fico]['pd_12m']
            elif state == '30_DPD': pd_val = pds[fico]['pd_lifetime_30dpd']
            elif state == '60_DPD': pd_val = pds[fico]['pd_lifetime_60dpd']
            else: pd_val = pds[fico]['pd_12m']
        else:
            pd_val = pds['Unknown']['pd_12m']
        pop = 'Pop1_Base'
        
    ecl = row['snapshot_upb'] * pd_val * lgd
    snap_df.at[idx, 'applied_pd'] = pd_val
    snap_df.at[idx, 'pop'] = pop
    snap_df.at[idx, 'ecl'] = ecl
    total_ecl += ecl

print("\n--- Snapshot Populations ---")
print(snap_df.groupby('pop').agg({'loan_id':'count', 'snapshot_upb':'sum', 'ecl':'sum'}))
print(f"\nFinal Point Estimate ECL: ${total_ecl:,.2f}")
