import duckdb

def main():
    con = duckdb.connect("mortgage_risk.duckdb")
    # Pop 2 UPB
    upb = con.execute("SELECT SUM(current_actual_upb) FROM clean_monthly_performance WHERE monthly_reporting_period = 201912 AND loan_state = 'Modified'").fetchone()[0]
    print(f"Pop 2 UPB from clean: {upb:,.2f}")
    
    # Probation ex-hurricane
    q = """
    WITH current_loans AS (
        SELECT p.loan_id 
        FROM clean_monthly_performance p
        JOIN raw_origination r ON p.loan_id = r.loan_id
        WHERE p.monthly_reporting_period = 201512 AND p.loan_state = 'Current' 
        AND p.loan_id NOT IN (SELECT loan_id FROM clean_monthly_performance WHERE monthly_reporting_period = 201512 AND loan_state = 'Modified')
        AND NOT (r.property_state IN ('FL', 'TX', 'PR'))
    ),
    history AS (
        SELECT c.loan_id, MAX(CASE WHEN p.loan_state IN ('30_DPD', '60_DPD') THEN 1 ELSE 0 END) as recent_delq 
        FROM current_loans c 
        JOIN clean_monthly_performance p ON c.loan_id = p.loan_id 
        WHERE p.monthly_reporting_period BETWEEN 201501 AND 201512 
        GROUP BY c.loan_id 
        HAVING MAX(CASE WHEN p.loan_state IN ('30_DPD', '60_DPD') THEN 1 ELSE 0 END) = 1
    ),
    defaults AS (
        SELECT h.loan_id, MAX(CASE WHEN p.loan_state = 'Default' THEN 1 ELSE 0 END) as defaulted
        FROM history h
        JOIN clean_monthly_performance p ON h.loan_id = p.loan_id
        WHERE p.monthly_reporting_period BETWEEN 201601 AND 201912
        GROUP BY h.loan_id
    )
    SELECT COUNT(h.loan_id) as obs, SUM(d.defaulted) as defs
    FROM history h LEFT JOIN defaults d ON h.loan_id = d.loan_id
    """
    df = con.execute(q).df()
    print(f"Ex-Hurricane Probation PD: {df['defs'].values[0] / df['obs'].values[0] * 100:.2f}%")

if __name__ == "__main__":
    main()
