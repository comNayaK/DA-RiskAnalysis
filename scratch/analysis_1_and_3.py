import duckdb
from src.db import get_connection

def main():
    con = get_connection("mortgage_risk.duckdb")
    
    # 1. Mod-defaulted loans split
    print("=== 1. Mod-defaulted loans split ===")
    query = """
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
    SELECT 
        CASE WHEN m.first_mod <= 202002 THEN '<= 202002' ELSE '> 202002' END as mod_timing,
        CASE 
            WHEN m.first_mod < d.first_default THEN 'Before Default'
            WHEN m.first_mod = d.first_default THEN 'Same Time'
            ELSE 'After Default'
        END as mod_vs_def,
        COUNT(DISTINCT d.loan_id) as count
    FROM default_loans d
    JOIN mod_loans m ON d.loan_id = m.loan_id
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = con.execute(query).df()
    print(df.to_string(index=False))
    
    print("\nRe-evaluating total modified-defaulted (the 2096 vs 1956):")
    total_mod_def = con.execute("SELECT COUNT(DISTINCT d.loan_id) FROM (SELECT loan_id, MIN(monthly_reporting_period) as first_default FROM clean_monthly_performance WHERE loan_state = 'Default' GROUP BY loan_id) d JOIN (SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as first_mod FROM raw_performance WHERE modification_flag IN ('Y', 'P') GROUP BY loan_id) m ON d.loan_id = m.loan_id").fetchone()[0]
    print(f"Total modified-defaulted in dataset: {total_mod_def}")
    
    # We also need the "6023" figure. Total defaulted loans?
    total_def = con.execute("SELECT COUNT(DISTINCT loan_id) FROM clean_monthly_performance WHERE loan_state = 'Default'").fetchone()[0]
    print(f"Total defaulted loans: {total_def}")
    
    # 34.8% share = 2096 / 6023. We will recompute the tail based on the accurate split.
    
    # 3. Clean vs Recent Delinquency 2015-2019
    print("\n=== 3. Clean vs Recent Delinquency 2015-2019 ===")
    for year in range(2015, 2020):
        prev_year = year - 1
        q = f"""
        WITH current_loans AS (
            SELECT loan_id, current_actual_upb as upb FROM clean_monthly_performance
            WHERE monthly_reporting_period = {prev_year}12 AND loan_state = 'Current'
        ),
        history AS (
            SELECT c.loan_id, c.upb,
                   MAX(CASE WHEN p.loan_state IN ('30_DPD', '60_DPD') THEN 1 ELSE 0 END) as recent_delq
            FROM current_loans c
            JOIN clean_monthly_performance p ON c.loan_id = p.loan_id
            WHERE p.monthly_reporting_period BETWEEN {prev_year}01 AND {prev_year}12
            GROUP BY c.loan_id, c.upb
        ),
        defaults_next AS (
            SELECT c.loan_id, 
                   MAX(CASE WHEN p.loan_state = 'Default' THEN 1 ELSE 0 END) as defaulted
            FROM current_loans c
            JOIN clean_monthly_performance p ON c.loan_id = p.loan_id
            WHERE p.monthly_reporting_period BETWEEN {year}01 AND {year}12
            GROUP BY c.loan_id
        )
        SELECT {year} as eval_year, h.recent_delq, COUNT(h.loan_id) as obs, SUM(d.defaulted) as defs, 
               ROUND(SUM(d.defaulted)*100.0/COUNT(h.loan_id), 4) as pd_pct
        FROM history h
        LEFT JOIN defaults_next d ON h.loan_id = d.loan_id
        GROUP BY h.recent_delq
        """
        res = con.execute(q).df()
        for _, row in res.iterrows():
            grp = "Recent Delq" if row['recent_delq'] == 1 else "Clean 12m"
            print(f"Year {int(row['eval_year'])} | {grp:12s} | Obs: {int(row['obs']):7d} | Defs: {int(row['defs']):5d} | PD: {row['pd_pct']:.3f}%")

if __name__ == "__main__":
    main()
