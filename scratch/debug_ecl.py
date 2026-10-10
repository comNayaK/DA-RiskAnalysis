import duckdb
import pandas as pd
from src.layers import build_layer1_clean_performance, build_ecl_snapshot
from src.config import BACKTEST_TRAIN_CUTOFF

con = duckdb.connect('mortgage_risk.duckdb')
con.execute("CREATE OR REPLACE MACRO month_idx(yyyymm) AS CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 1, 4) AS INT) * 12 + CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 5, 2) AS INT);")

build_ecl_snapshot(con, snapshot_period=201912)
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
print("DF ECL length:", len(df_ecl))
print("DF ECL UPB sum:", df_ecl['snapshot_upb'].sum())
print("DF ECL loan_state counts:\n", df_ecl['loan_state'].value_counts())
