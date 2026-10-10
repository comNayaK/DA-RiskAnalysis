import duckdb
import pandas as pd
import numpy as np
import math
import sys
sys.path.append('.')

def wilson(k, n, confidence=0.95):
    if n == 0:
        return 0.0, 0.0, 0.0
    z = 1.96
    p = k / n
    denominator = 1 + z**2/n
    center = (p + z**2 / (2*n)) / denominator
    half_width = z * math.sqrt(p*(1-p)/n + z**2/(4*n**2)) / denominator
    return p, max(0, center - half_width), min(1, center + half_width)

def run_tests():
    con = duckdb.connect('mortgage_risk.duckdb')
    con.execute("CREATE OR REPLACE MACRO month_idx(yyyymm) AS CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 1, 4) AS INT) * 12 + CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 5, 2) AS INT);")
    
    print("=== (1) Ingestion Gates & Vintage Counts ===")
    df_vint = con.execute("""
    SELECT CAST(SUBSTRING(loan_id, 2, 2) AS INT) + 2000 as vintage, COUNT(*) as loan_count
    FROM raw_origination
    GROUP BY vintage ORDER BY vintage
    """).df()
    print(df_vint.to_string(index=False))
    
    print("\n=== (2) Out-of-Time Backtest ===")
    con.execute("""
    CREATE OR REPLACE VIEW v_oos_train AS
    SELECT state_t, state_t_plus_1, COUNT(*) AS n
    FROM loan_level_transitions
    WHERE monthly_reporting_period <= 201812
      AND CAST(SUBSTRING(loan_id, 2, 2) AS INT) + 2000 <= 2015
    GROUP BY state_t, state_t_plus_1;
    """)
    oos_counts_df = con.execute("SELECT * FROM v_oos_train").df()
    
    states_order = ['Current', '30_DPD', '60_DPD', 'Default', 'Paid_Off', 'Admin_Removal', 'Modified']
    state_to_idx = {s: i for i, s in enumerate(states_order)}
    C_train = np.zeros((len(states_order), len(states_order)))
    for _, r in oos_counts_df.iterrows():
        if r['state_t'] in state_to_idx and r['state_t_plus_1'] in state_to_idx:
            C_train[state_to_idx[r['state_t']], state_to_idx[r['state_t_plus_1']]] += r['n']
    
    Q_train = np.zeros((3, 3))
    R_train = np.zeros((3, 4))
    for i in range(3):
        row_sum = C_train[i].sum()
        if row_sum > 0:
            for j in range(3):
                Q_train[i, j] = C_train[i, j] / row_sum
            for j, a_idx in enumerate([3, 4, 5, 6]):
                R_train[i, j] = C_train[i, a_idx] / row_sum
                
    P_12 = np.zeros((3, 4))
    for t in range(12):
        P_12 += np.linalg.matrix_power(Q_train, t) @ R_train
    pd_12m_oos = P_12[0, 0]
    
    print(f"Matrix 12m PD trained on <=2015 vintages (perf <=201812): {pd_12m_oos:.6f}")
    
    con.execute("""
    CREATE OR REPLACE TABLE oos_snap_2016_plus AS
    SELECT loan_id
    FROM clean_monthly_performance
    WHERE monthly_reporting_period = 201812
      AND loan_state = 'Current'
      AND zero_balance_code IS NULL
      AND CAST(SUBSTRING(loan_id, 2, 2) AS INT) + 2000 >= 2016;
    """)
    snap_count = con.execute("SELECT COUNT(*) FROM oos_snap_2016_plus").fetchone()[0]
    actual_defaults = con.execute("""
    SELECT COUNT(DISTINCT s.loan_id)
    FROM oos_snap_2016_plus s
    INNER JOIN clean_monthly_performance p ON s.loan_id = p.loan_id
    WHERE p.monthly_reporting_period BETWEEN 201901 AND 201912
      AND p.loan_state = 'Default';
    """).fetchone()[0]
    exp = snap_count * pd_12m_oos
    print(f"Test on 2016+ vintages (Snapshot 201812, Perf 2019):")
    print(f"Loans: {snap_count}, Expected: {exp:.1f}, Actual: {actual_defaults}")
    if snap_count > 0:
        z = (actual_defaults - exp) / math.sqrt(snap_count * pd_12m_oos * (1 - pd_12m_oos))
        print(f"Z-Score: {z:.2f}")

    print("\n=== (3) Age Test in Same Calendar Year (2019 Defaults from 201812 Snapshot) ===")
    q_age = """
    SELECT 
        CAST(SUBSTRING(s.loan_id, 2, 2) AS INT) + 2000 as vintage,
        CASE 
            WHEN p_snap.loan_age < 12 THEN '0-11'
            WHEN p_snap.loan_age < 24 THEN '12-23'
            WHEN p_snap.loan_age < 36 THEN '24-35'
            WHEN p_snap.loan_age < 48 THEN '36-47'
            ELSE '48+' 
        END as age_bucket,
        COUNT(DISTINCT s.loan_id) as obs_count,
        SUM(CASE WHEN d.loan_id IS NOT NULL THEN 1 ELSE 0 END) as default_count
    FROM clean_monthly_performance p_snap
    INNER JOIN (SELECT DISTINCT loan_id FROM raw_origination) s ON p_snap.loan_id = s.loan_id
    LEFT JOIN (
        SELECT DISTINCT loan_id 
        FROM clean_monthly_performance 
        WHERE monthly_reporting_period BETWEEN 201901 AND 201912 AND loan_state = 'Default'
    ) d ON p_snap.loan_id = d.loan_id
    WHERE p_snap.monthly_reporting_period = 201812
      AND p_snap.loan_state = 'Current'
      AND p_snap.zero_balance_code IS NULL
    GROUP BY vintage, age_bucket
    ORDER BY vintage
    """
    df_age = con.execute(q_age).df()
    for idx, row in df_age.iterrows():
        p, l, u = wilson(row['default_count'], row['obs_count'])
        df_age.at[idx, 'pd_12m'] = f"{p:.4%} [{l:.4%}, {u:.4%}]"
    print(df_age[['vintage', 'age_bucket', 'obs_count', 'default_count', 'pd_12m']].to_string(index=False))

    print("\n=== (4) Fallback Count (n < 100) ===")
    print("Fallback applies in FICO stratification when loan counts in a state transition row are < 100.")
    # Calculate fallbacks
    q_fico = "SELECT fico_band, state_t, SUM(n) as row_sum FROM v_transition_matrix_fico GROUP BY fico_band, state_t"
    df_fico = con.execute(q_fico).df()
    fallbacks = df_fico[df_fico['row_sum'] < 100]
    print(f"Fallback triggered {len(fallbacks)} times out of {len(df_fico)} stratifications.")
    if len(fallbacks) > 0:
        print(fallbacks.to_string(index=False))

    print("\n=== (5) Full Scenario Grid and Outputs ===")
    import scratch.scenario_grid
    import scratch.final_report_script
    print("--- See output of final_report_script.py and scenario_grid.py below ---")

if __name__ == '__main__':
    run_tests()
