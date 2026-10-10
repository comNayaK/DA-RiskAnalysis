import duckdb
con = duckdb.connect('mortgage_risk.duckdb')
con.execute("CREATE OR REPLACE MACRO month_idx(yyyymm) AS CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 1, 4) AS INT) * 12 + CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 5, 2) AS INT);")

def get_counts(as_of):
    q = f"""
    WITH first_default AS (SELECT loan_id, MIN(monthly_reporting_period) as fd FROM clean_monthly_performance WHERE loan_state='Default' AND monthly_reporting_period <= {as_of} GROUP BY loan_id),
         first_mod AS (SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as fm FROM raw_performance WHERE COALESCE(modification_flag, '') IN ('Y','P') AND CAST(monthly_reporting_period AS INT) <= {as_of} GROUP BY loan_id)
    SELECT p.loan_id, p.loan_state,
           CASE 
               WHEN p.loan_state = 'Default' THEN 3
               WHEN f.fd IS NOT NULL OR m.fm IS NOT NULL THEN 2
               ELSE 1
           END as pop
    FROM ecl_snapshot e
    JOIN clean_monthly_performance p ON e.loan_id = p.loan_id AND p.monthly_reporting_period = {as_of}
    LEFT JOIN first_default f ON p.loan_id = f.loan_id
    LEFT JOIN first_mod m ON p.loan_id = m.loan_id
    """
    df = con.execute(q).df()
    print(f"[{as_of}] ecl_snapshot partition counts:")
    print(df['pop'].value_counts())

    q2 = f"""
    WITH first_default AS (SELECT loan_id, MIN(monthly_reporting_period) as fd FROM clean_monthly_performance WHERE loan_state='Default' AND monthly_reporting_period <= {as_of} GROUP BY loan_id),
         first_mod AS (SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as fm FROM raw_performance WHERE COALESCE(modification_flag, '') IN ('Y','P') AND CAST(monthly_reporting_period AS INT) <= {as_of} GROUP BY loan_id)
    SELECT p.loan_id, p.loan_state,
           CASE 
               WHEN p.loan_state = 'Default' THEN 3
               WHEN f.fd IS NOT NULL OR m.fm IS NOT NULL THEN 2
               ELSE 1
           END as pop
    FROM clean_monthly_performance p
    LEFT JOIN first_default f ON p.loan_id = f.loan_id
    LEFT JOIN first_mod m ON p.loan_id = m.loan_id
    WHERE p.monthly_reporting_period = {as_of} AND p.zero_balance_code IS NULL
    """
    df2 = con.execute(q2).df()
    print(f"[{as_of}] active loans partition counts:")
    print(df2['pop'].value_counts())

get_counts(201812)
get_counts(201912)

