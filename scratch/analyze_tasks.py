import duckdb
import numpy as np
import pandas as pd
import sys
import os

# Add src to path if needed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.markov import counts_df_to_array, build_markov_matrices, compute_12month_pd
from src.config import BACKTEST_TRAIN_CUTOFF, BACKTEST_SNAPSHOT

def run_analysis():
    con = duckdb.connect('mortgage_risk.duckdb')
    
    print("=" * 80)
    print("Task 1: Backtest Leakage")
    # Base matrix with <= 201812
    oos_portfolio_df = con.execute(f"""
        SELECT state_t, state_t_plus_1, COUNT(*) AS n
        FROM loan_level_transitions
        WHERE monthly_reporting_period <= {BACKTEST_TRAIN_CUTOFF}
        GROUP BY 1, 2
    """).df()
    C_oos_port = counts_df_to_array(oos_portfolio_df)
    Q_oos, R_oos, _, _, _ = build_markov_matrices(C_oos_port)
    pd_12m_base = compute_12month_pd(Q_oos, R_oos)
    
    snap_count = con.execute("SELECT COUNT(*) FROM oos_snapshot_201812").fetchone()[0]
    expected_defaults = snap_count * pd_12m_base
    
    actual_defaults = con.execute(f"""
        SELECT COUNT(DISTINCT s.loan_id) 
        FROM oos_snapshot_201812 s 
        INNER JOIN clean_monthly_performance p ON s.loan_id = p.loan_id 
        WHERE p.monthly_reporting_period BETWEEN 201901 AND 201912 
        AND p.loan_state = 'Default'
    """).fetchone()[0]
    
    z_score = (actual_defaults - expected_defaults) / np.sqrt(expected_defaults)
    print(f"Base matrix 12m PD (<=201812 only): {pd_12m_base:.6f}")
    print(f"Expected Defaults: {expected_defaults:.2f}")
    print(f"Actual Defaults: {actual_defaults}")
    print(f"Poisson Z-Score: {z_score:.2f}")


    print("=" * 80)
    print("Task 2: Dollar-weighted P(liq)")
    # We need to get UPB at the FIRST DEFAULT row, not the last row
    # The view v_first_default gives the first_default_period. We can join to get the UPB at that time.
    con.execute("""
        CREATE OR REPLACE TEMP VIEW v_first_default_upb AS
        SELECT f.loan_id, f.first_default_period, p.current_actual_upb as default_upb
        FROM v_first_default f
        INNER JOIN clean_monthly_performance p 
        ON f.loan_id = p.loan_id AND f.first_default_period = p.monthly_reporting_period
    """)
    
    # We join this with the 24m outcomes
    dollar_res = con.execute("""
        SELECT 
            SUM(CASE WHEN o.outcome_24m IN ('Liquidated', 'Still_In_Default') THEN u.default_upb ELSE 0 END) as dol_upper,
            SUM(CASE WHEN o.outcome_24m NOT IN ('Admin_Removed') THEN u.default_upb ELSE 0 END) as total_dol
        FROM v_default_outcomes_24m o
        LEFT JOIN v_first_default_upb u ON o.loan_id = u.loan_id
    """).fetchone()
    
    if dollar_res[1] > 0:
        print(f"Dollar-weighted P(liq) Upper Bound: {dollar_res[0]/dollar_res[1]:.4f}")
    else:
        print("Error calculating Dollar-weighted P(liq)")

    
    print("=" * 80)
    print("Task 3: Count-weighted P(liq)")
    # Reconcile the 67.93% figure
    outcomes_24m = con.execute("SELECT outcome_24m, COUNT(*) as cnt FROM v_default_outcomes_24m GROUP BY 1 ORDER BY cnt DESC").df()
    print("Outcomes 24m breakdown:")
    print(outcomes_24m)
    
    # The validation script had:
    # count_upper = SUM(CASE WHEN zero_balance_code IN ('02','03','09') OR loan_state = 'Default' THEN 1 ELSE 0 END)
    # total_count = SUM(1)
    # WHERE zero_balance_code NOT IN ('06','15','16','96') OR zero_balance_code IS NULL
    
    # Let's see what the old script was doing:
    old_script_query = con.execute("""
        WITH window_rows AS (
            SELECT p.loan_id, p.loan_state, p.zero_balance_code, p.monthly_reporting_period, f.first_default_period, p.current_actual_upb
            FROM clean_monthly_performance p INNER JOIN v_first_default f ON p.loan_id = f.loan_id
            WHERE f.first_default_period <= 201712 AND p.monthly_reporting_period >= f.first_default_period AND month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) <= 24
        ),
        v_last_row_24 AS (
            SELECT * FROM window_rows QUALIFY ROW_NUMBER() OVER (PARTITION BY loan_id ORDER BY monthly_reporting_period DESC) = 1
        )
        SELECT 
            SUM(CASE WHEN zero_balance_code IN ('02','03','09') OR loan_state = 'Default' THEN 1 ELSE 0 END) as count_upper,
            SUM(1) as total_count
        FROM v_last_row_24 WHERE zero_balance_code NOT IN ('06','15','16','96') OR zero_balance_code IS NULL
    """).fetchone()
    print(f"Old script count_upper: {old_script_query[0]}, total_count: {old_script_query[1]}, ratio: {old_script_query[0]/old_script_query[1] if old_script_query[1] else 0:.4f}")
    
    # My manual calculation from outcomes: Liquidated=661, Still_In_Default=247, Paid_Off=551, Cured_Active=540, Admin_Removed=58. Total=2057
    # Without Admin_Removed: 661 + 247 + 551 + 540 = 1999.
    # Liquidated + Still_In_Default = 661 + 247 = 908.
    # 908 / 1999 = 45.42%. Why was it 67.93% before? 
    # Let's inspect the exact query difference. The old script used:
    # WHERE zero_balance_code NOT IN ('06','15','16','96') OR zero_balance_code IS NULL
    # This might have filtered out more than just Admin_Removed. For example, paid off ('01') has zero_balance_code = '01'. Is it excluded by the WHERE clause? 
    # `zero_balance_code = '01'` makes `zero_balance_code IS NULL` FALSE, and it's NOT IN ('06','15','16','96'). So it is INCLUDED.
    # Wait, what if loan_state is different? Let's check `v_last_row_24` directly.
    print("Wait, let's look at zero_balance_code distribution in v_last_row_24")
    zbc_dist = con.execute("""
        WITH window_rows AS (
            SELECT p.loan_id, p.loan_state, p.zero_balance_code, p.monthly_reporting_period, f.first_default_period
            FROM clean_monthly_performance p INNER JOIN v_first_default f ON p.loan_id = f.loan_id
            WHERE f.first_default_period <= 201712 AND p.monthly_reporting_period >= f.first_default_period AND month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) <= 24
        ),
        v_last_row_24 AS (
            SELECT * FROM window_rows QUALIFY ROW_NUMBER() OVER (PARTITION BY loan_id ORDER BY monthly_reporting_period DESC) = 1
        )
        SELECT zero_balance_code, loan_state, count(*) as cnt
        FROM v_last_row_24
        GROUP BY 1, 2 ORDER BY cnt DESC
    """).df()
    print(zbc_dist)
    
    print("=" * 80)
    print("Task 4: LGD Horizon 24m vs 36m")
    # LGD 24m
    counts_24 = outcomes_24m.set_index('outcome_24m')['cnt']
    tot_24 = counts_24.sum()
    admin_24 = counts_24.get('Admin_Removed', 0)
    den_24 = tot_24 - admin_24
    liq_24 = counts_24.get('Liquidated', 0)
    def_24 = counts_24.get('Still_In_Default', 0)
    p_liq_l_24 = liq_24 / tot_24 if tot_24 else 0
    p_liq_u_24 = (liq_24 + def_24) / den_24 if den_24 else 0
    sev_24 = con.execute("SELECT empirical_loss_severity FROM v_lgd_severity_24m").fetchone()[0] or 0
    print(f"24m P(liq) bounds: [{p_liq_l_24:.4f}, {p_liq_u_24:.4f}], Severity: {sev_24:.4f}")
    print(f"24m LGD Range: [{p_liq_l_24*sev_24:.4f}, {p_liq_u_24*sev_24:.4f}]")
    
    # LGD 36m
    outcomes_36m = con.execute("SELECT outcome_36m, COUNT(*) as cnt FROM v_default_outcomes_36m GROUP BY 1 ORDER BY cnt DESC").df()
    counts_36 = outcomes_36m.set_index('outcome_36m')['cnt']
    tot_36 = counts_36.sum()
    admin_36 = counts_36.get('Admin_Removed', 0)
    den_36 = tot_36 - admin_36
    liq_36 = counts_36.get('Liquidated', 0)
    def_36 = counts_36.get('Still_In_Default', 0)
    p_liq_l_36 = liq_36 / tot_36 if tot_36 else 0
    p_liq_u_36 = (liq_36 + def_36) / den_36 if den_36 else 0
    sev_36 = con.execute("SELECT empirical_loss_severity FROM v_lgd_severity_36m").fetchone()[0] or 0
    print(f"36m P(liq) bounds: [{p_liq_l_36:.4f}, {p_liq_u_36:.4f}], Severity: {sev_36:.4f}")
    print(f"36m LGD Range: [{p_liq_l_36*sev_36:.4f}, {p_liq_u_36*sev_36:.4f}]")
    
    print("=" * 80)
    print("Task 6: Backtest Snapshot")
    snap_states = con.execute("""
        SELECT loan_state, COUNT(*) 
        FROM oos_snapshot_201812 s
        INNER JOIN clean_monthly_performance p ON s.loan_id = p.loan_id 
        WHERE p.monthly_reporting_period = 201812
        GROUP BY 1
    """).df()
    print("Backtest snapshot loan_state distribution:")
    print(snap_states)
    
if __name__ == '__main__':
    run_analysis()
