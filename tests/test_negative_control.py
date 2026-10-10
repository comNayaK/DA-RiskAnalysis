import duckdb
from src.population import build_partition

def test_negative_control_leak():
    con = duckdb.connect(':memory:')
    con.execute("CREATE TABLE raw_performance (loan_id VARCHAR, monthly_reporting_period INT, modification_flag VARCHAR)")
    con.execute("CREATE TABLE clean_monthly_performance (loan_id VARCHAR, monthly_reporting_period INT, loan_state VARCHAR, current_actual_upb DOUBLE, zero_balance_code VARCHAR)")
    
    # Insert clean loan up to 201812
    con.execute("INSERT INTO clean_monthly_performance VALUES ('L1', 201812, 'Current', 100000.0, NULL)")
    # Inject future modification
    con.execute("INSERT INTO raw_performance VALUES ('L1', 201903, 'Y')")
    
    # Run as-of logic for 201812 using production function
    df_pop = build_partition(con, 201812)
    
    # Assert loan is NOT in Pop 2 (leak prevented)
    assert len(df_pop) == 1
    assert df_pop['pop'].iloc[0] == 1, "Look-ahead leak: Future modification infected past state!"

def test_mutation_leak():
    # Simulate a mutation by intentionally removing the as-of filter on the CTE
    con = duckdb.connect(':memory:')
    con.execute("CREATE TABLE raw_performance (loan_id VARCHAR, monthly_reporting_period INT, modification_flag VARCHAR)")
    con.execute("CREATE TABLE clean_monthly_performance (loan_id VARCHAR, monthly_reporting_period INT, loan_state VARCHAR, current_actual_upb DOUBLE, zero_balance_code VARCHAR)")
    
    con.execute("INSERT INTO clean_monthly_performance VALUES ('L1', 201812, 'Current', 100000.0, NULL)")
    con.execute("INSERT INTO raw_performance VALUES ('L1', 201903, 'Y')")
    
    q_mutant = f"""
    WITH first_default AS (SELECT loan_id, MIN(monthly_reporting_period) as fd FROM clean_monthly_performance WHERE loan_state='Default' GROUP BY loan_id),
         first_mod AS (SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as fm FROM raw_performance WHERE COALESCE(modification_flag, '') IN ('Y','P') GROUP BY loan_id)
    SELECT p.loan_id, 
           CASE 
               WHEN p.loan_state = 'Default' THEN 3
               WHEN f.fd IS NOT NULL OR m.fm IS NOT NULL THEN 2
               ELSE 1
           END as pop
    FROM clean_monthly_performance p
    LEFT JOIN first_default f ON p.loan_id = f.loan_id
    LEFT JOIN first_mod m ON p.loan_id = m.loan_id
    WHERE p.monthly_reporting_period = 201812 AND p.zero_balance_code IS NULL
    """
    df_mutant = con.execute(q_mutant).df()
    
    # In the mutant, the future mod WILL infect the state, placing the loan in Pop 2
    assert df_mutant['pop'].iloc[0] == 2, "Mutation test failed: Expected a leak when filter is removed."
