import duckdb
con = duckdb.connect('mortgage_risk.duckdb')
con.execute("CREATE OR REPLACE MACRO month_idx(yyyymm) AS CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 1, 4) AS INT) * 12 + CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 5, 2) AS INT);")
q_pop2 = """
    WITH first_default AS (SELECT loan_id, MIN(monthly_reporting_period) as fd FROM clean_monthly_performance WHERE loan_state='Default' AND monthly_reporting_period <= 201912 GROUP BY loan_id),
         first_mod AS (SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as fm FROM raw_performance WHERE COALESCE(modification_flag, '') IN ('Y','P') AND CAST(monthly_reporting_period AS INT) <= 201912 GROUP BY loan_id),
    events AS (
        SELECT p.loan_id, MIN(p.monthly_reporting_period) as event_date, 'Self_Cured' as event_type
        FROM clean_monthly_performance p INNER JOIN first_default f ON p.loan_id=f.loan_id
        WHERE p.monthly_reporting_period > f.fd AND p.loan_state='Current' AND p.monthly_reporting_period <= 201912
          AND NOT EXISTS(SELECT 1 FROM first_mod m WHERE m.loan_id=p.loan_id AND m.fm<=p.monthly_reporting_period)
        GROUP BY p.loan_id
        UNION ALL
        SELECT m.loan_id, m.fm as event_date, CASE WHEN f.fd IS NOT NULL AND f.fd<m.fm THEN 'Mod_After_Default' ELSE 'Mod_Without_Default' END
        FROM first_mod m LEFT JOIN first_default f ON m.loan_id=f.loan_id
    )
    SELECT e.loan_id, e.event_type
    FROM events e
    INNER JOIN clean_monthly_performance p ON p.loan_id = e.loan_id AND p.monthly_reporting_period = 201912
    WHERE p.loan_state IN ('Modified', 'Current', '30_DPD', '60_DPD') AND p.zero_balance_code IS NULL
"""
df_pop2 = con.execute(q_pop2).df()
print("Pop 2 Events Count:", len(df_pop2))

q_part = """
    WITH first_default AS (SELECT loan_id, MIN(monthly_reporting_period) as fd FROM clean_monthly_performance WHERE loan_state='Default' AND monthly_reporting_period <= 201912 GROUP BY loan_id),
         first_mod AS (SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as fm FROM raw_performance WHERE COALESCE(modification_flag, '') IN ('Y','P') AND CAST(monthly_reporting_period AS INT) <= 201912 GROUP BY loan_id)
    SELECT p.loan_id, p.loan_state
    FROM clean_monthly_performance p
    LEFT JOIN first_default f ON p.loan_id = f.loan_id
    LEFT JOIN first_mod m ON p.loan_id = m.loan_id
    WHERE p.monthly_reporting_period = 201912 AND p.zero_balance_code IS NULL
      AND (f.fd IS NOT NULL OR m.fm IS NOT NULL) AND p.loan_state != 'Default'
"""
df_part = con.execute(q_part).df()
print("Partition Pop 2 Count:", len(df_part))

# Find the ones missing from df_part but present in df_pop2
diff = set(df_pop2['loan_id']) - set(df_part['loan_id'])
print("Missing in Partition, but in Events:", len(diff))

diff_2 = set(df_part['loan_id']) - set(df_pop2['loan_id'])
print("In Partition, but not in Events:", len(diff_2))

