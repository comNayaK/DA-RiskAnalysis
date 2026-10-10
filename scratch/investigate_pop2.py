import duckdb
con = duckdb.connect('mortgage_risk.duckdb')

q7 = """
    WITH first_default AS (SELECT loan_id, MIN(monthly_reporting_period) as fd FROM clean_monthly_performance WHERE loan_state='Default' AND monthly_reporting_period <= 201912 GROUP BY loan_id),
         first_mod AS (SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as fm FROM raw_performance WHERE COALESCE(modification_flag, '') IN ('Y','P') AND CAST(monthly_reporting_period AS INT) <= 201912 GROUP BY loan_id)
    SELECT p.loan_id, p.loan_state, e.snapshot_upb as upb,
           CASE 
               WHEN p.loan_state = 'Default' THEN 3
               WHEN f.fd IS NOT NULL OR m.fm IS NOT NULL THEN 2
               ELSE 1
           END as pop
    FROM ecl_snapshot e
    JOIN clean_monthly_performance p ON e.loan_id = p.loan_id AND p.monthly_reporting_period = 201912
    LEFT JOIN first_default f ON p.loan_id = f.loan_id
    LEFT JOIN first_mod m ON p.loan_id = m.loan_id
"""
df7 = con.execute(q7).df()
print("Script 7 counts:")
print(df7['pop'].value_counts())

q9 = """
    WITH first_default AS (SELECT loan_id, MIN(monthly_reporting_period) as fd FROM clean_monthly_performance WHERE loan_state='Default' AND monthly_reporting_period <= 201912 GROUP BY loan_id),
         first_mod AS (SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as fm FROM raw_performance WHERE COALESCE(modification_flag, '') IN ('Y','P') AND CAST(monthly_reporting_period AS INT) <= 201912 GROUP BY loan_id)
    SELECT p.loan_id, p.loan_state, p.current_actual_upb as upb,
           CASE 
               WHEN p.loan_state = 'Default' THEN 3
               WHEN f.fd IS NOT NULL OR m.fm IS NOT NULL THEN 2
               ELSE 1
           END as pop
    FROM clean_monthly_performance p
    LEFT JOIN first_default f ON p.loan_id = f.loan_id
    LEFT JOIN first_mod m ON p.loan_id = m.loan_id
    WHERE p.monthly_reporting_period = 201912 AND p.zero_balance_code IS NULL
"""
df9 = con.execute(q9).df()
print("Script 9 counts:")
print(df9['pop'].value_counts())

q_diff = """
WITH s7 AS (
""" + q7 + """
), s9 AS (
""" + q9 + """
)
SELECT s7.pop as pop7, s9.pop as pop9, s7.loan_state as state7, s9.loan_state as state9, COUNT(*) as cnt
FROM s7 JOIN s9 ON s7.loan_id = s9.loan_id
WHERE s7.pop != s9.pop
GROUP BY 1, 2, 3, 4
"""
print("Differences:")
print(con.execute(q_diff).df())
