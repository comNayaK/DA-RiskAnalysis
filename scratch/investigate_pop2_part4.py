import duckdb
con = duckdb.connect('mortgage_risk.duckdb')

def pop2_states(as_of):
    q = f"""
    WITH first_default AS (SELECT loan_id, MIN(monthly_reporting_period) as fd FROM clean_monthly_performance WHERE loan_state='Default' AND monthly_reporting_period <= {as_of} GROUP BY loan_id),
         first_mod AS (SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as fm FROM raw_performance WHERE COALESCE(modification_flag, '') IN ('Y','P') AND CAST(monthly_reporting_period AS INT) <= {as_of} GROUP BY loan_id)
    SELECT p.loan_id, p.loan_state
    FROM clean_monthly_performance p
    LEFT JOIN first_default f ON p.loan_id = f.loan_id
    LEFT JOIN first_mod m ON p.loan_id = m.loan_id
    WHERE p.monthly_reporting_period = {as_of} AND p.zero_balance_code IS NULL
      AND (f.fd IS NOT NULL OR m.fm IS NOT NULL) AND p.loan_state != 'Default'
    """
    df = con.execute(q).df()
    print(f"[{as_of}] Pop 2 by state:")
    print(df['loan_state'].value_counts())
    print("Total:", len(df))

pop2_states(201812)
pop2_states(201912)
