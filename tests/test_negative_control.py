import duckdb
import pandas as pd
import numpy as np

def get_pop2_events(con, as_of_date, raw_table="raw_performance", clean_table="clean_monthly_performance"):
    q = f"""
    WITH first_default AS (SELECT loan_id, MIN(monthly_reporting_period) as fd FROM {clean_table} WHERE loan_state='Default' AND monthly_reporting_period <= {as_of_date} GROUP BY loan_id),
         first_mod AS (SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as fm FROM {raw_table} WHERE COALESCE(modification_flag, '') IN ('Y','P') AND CAST(monthly_reporting_period AS INT) <= {as_of_date} GROUP BY loan_id)
    SELECT p.loan_id
    FROM {clean_table} p
    LEFT JOIN first_default f ON p.loan_id = f.loan_id
    LEFT JOIN first_mod m ON p.loan_id = m.loan_id
    WHERE p.monthly_reporting_period = {as_of_date} AND (f.fd IS NOT NULL OR m.fm IS NOT NULL)
    """
    return con.execute(q).df()

def test_negative_control_leak():
    con = duckdb.connect(':memory:')
    con.execute("CREATE TABLE test_raw (loan_id VARCHAR, monthly_reporting_period INT, modification_flag VARCHAR)")
    con.execute("CREATE TABLE test_clean (loan_id VARCHAR, monthly_reporting_period INT, loan_state VARCHAR)")
    
    # Insert clean loan up to 201812
    con.execute("INSERT INTO test_clean VALUES ('L1', 201812, 'Current')")
    # Inject future modification
    con.execute("INSERT INTO test_raw VALUES ('L1', 201903, 'Y')")
    
    # Run as-of logic for 201812
    df_pop2 = get_pop2_events(con, 201812, "test_raw", "test_clean")
    
    # Assert loan is NOT in Pop 2 (leak prevented)
    assert len(df_pop2) == 0, "Look-ahead leak: Future modification infected past state!"
    
    # Run as-of logic for 201912
    # Ensure there is a snapshot in 201912 for the loan to be found
    con.execute("INSERT INTO test_clean VALUES ('L1', 201912, 'Current')")
    df_pop2_future = get_pop2_events(con, 201912, "test_raw", "test_clean")
    
    # Assert loan IS in Pop 2 for 201912
    assert len(df_pop2_future) == 1, "Expected modification not found when using valid future date."

if __name__ == "__main__":
    test_negative_control_leak()
    print("All tests passed.")
