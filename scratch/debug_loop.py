import duckdb
import pandas as pd
from src.layers import build_layer1_clean_performance, build_ecl_snapshot

con = duckdb.connect('mortgage_risk.duckdb')
con.execute("CREATE OR REPLACE MACRO month_idx(yyyymm) AS CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 1, 4) AS INT) * 12 + CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 5, 2) AS INT);")

q_ecl = """
WITH snap_events AS (
    SELECT loan_id, MAX(event_date) as last_event_date,
           MAX(CASE WHEN event_date = (SELECT MAX(event_date) FROM event_tracking WHERE loan_id = e.loan_id AND event_date <= 201912) THEN event_type END) as last_event_type
    FROM event_tracking e
    WHERE event_date <= 201912
    GROUP BY loan_id
)
SELECT 
    s.loan_id, s.loan_state, s.snapshot_upb,
    se.last_event_type as event_type, 
    month_idx(201912) - month_idx(se.last_event_date) as months_since_event
FROM ecl_snapshot s
LEFT JOIN snap_events se ON s.loan_id = se.loan_id
"""
df_ecl = con.execute(q_ecl).df()
print("Total rows:", len(df_ecl))
pop_list = []
for idx, row in df_ecl.iterrows():
    if row['loan_state'] == 'Default':
        pop = 'Pop3_Default'
    elif pd.notnull(row['event_type']) and row['months_since_event'] >= 0:
        pop = 'Pop2_Self_Cured' if row['event_type'] == 'Self_Cured' else 'Pop2_Mod'
    else:
        pop = f"Pop1_{row['loan_state']}"
    pop_list.append(pop)

df_ecl['pop'] = pop_list
print(df_ecl['pop'].value_counts())
