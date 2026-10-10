import duckdb
from src.db import get_connection

def main():
    con = get_connection("mortgage_risk.duckdb")
    
    q1 = """
    SELECT COUNT(DISTINCT loan_id) 
    FROM clean_monthly_performance 
    WHERE loan_state = 'Modified'
    """
    
    q2 = """
    SELECT COUNT(DISTINCT p.loan_id)
    FROM raw_performance p
    WHERE p.modification_flag IN ('Y', 'P')
    """
    
    print("Distinct loans with 'Modified' in clean:", con.execute(q1).fetchone()[0])
    print("Distinct loans with mod_flag in raw:", con.execute(q2).fetchone()[0])
    
    q3 = """
    WITH default_loans AS (
        SELECT loan_id, MIN(monthly_reporting_period) as first_default 
        FROM clean_monthly_performance 
        WHERE loan_state = 'Default' 
        GROUP BY loan_id
    ),
    mod_loans AS (
        SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as first_mod 
        FROM raw_performance 
        WHERE modification_flag IN ('Y', 'P') 
        GROUP BY loan_id
    )
    SELECT COUNT(*) 
    FROM default_loans d
    JOIN mod_loans m ON d.loan_id = m.loan_id
    WHERE m.first_mod <= d.first_default
    """
    print("Modified-before-default loans:", con.execute(q3).fetchone()[0])

if __name__ == "__main__":
    main()
