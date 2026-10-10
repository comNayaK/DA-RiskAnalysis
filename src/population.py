import duckdb

def build_partition(con: duckdb.DuckDBPyConnection, as_of_date: int):
    """
    Builds the Pop 1 / Pop 2 / Pop 3 partition for a given as_of_date.
    Pop 3: Currently Defaulted (in the snapshot)
    Pop 2: Previously Defaulted or Modified (but currently performing)
    Pop 1: Never Defaulted or Modified (currently performing)
    """
    q = f"""
    WITH first_default AS (
        SELECT loan_id, MIN(monthly_reporting_period) as fd 
        FROM clean_monthly_performance 
        WHERE loan_state='Default' AND monthly_reporting_period <= {as_of_date} 
        GROUP BY loan_id
    ),
    first_mod AS (
        SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as fm 
        FROM raw_performance 
        WHERE COALESCE(modification_flag, '') IN ('Y','P') AND CAST(monthly_reporting_period AS INT) <= {as_of_date} 
        GROUP BY loan_id
    )
    SELECT p.loan_id, p.loan_state, p.current_actual_upb as upb,
           CASE 
               WHEN p.loan_state = 'Default' THEN 3
               WHEN f.fd IS NOT NULL OR m.fm IS NOT NULL THEN 2
               ELSE 1
           END as pop
    FROM clean_monthly_performance p
    LEFT JOIN first_default f ON p.loan_id = f.loan_id
    LEFT JOIN first_mod m ON p.loan_id = m.loan_id
    WHERE p.monthly_reporting_period = {as_of_date} AND p.zero_balance_code IS NULL
    """
    return con.execute(q).df()
