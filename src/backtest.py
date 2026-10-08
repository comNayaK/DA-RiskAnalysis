"""
Section 8: Out-of-Sample Backtest Module
Estimates Markov parameters strictly on data <= 201812, predicts 2019 defaults,
and compares with actual realized defaults in 2019.
"""
import duckdb
import numpy as np
from src.config import BACKTEST_TRAIN_CUTOFF, BACKTEST_SNAPSHOT, BACKTEST_EVAL_YEAR
from src.markov import counts_df_to_array, build_markov_matrices, compute_12month_pd

def run_oos_backtest(con: duckdb.DuckDBPyConnection):
    """
    Executes true out-of-sample forward-looking model validation.
    """
    print("\n========================================================")
    print("   Section 8: Out-of-Sample Model Backtest (2018 -> 2019)")
    print("========================================================")

    # 1. Estimate transition matrix strictly on historical data <= 201812
    con.execute(f"""
    CREATE OR REPLACE VIEW v_oos_transitions AS
    SELECT state_t, state_t_plus_1, COUNT(*) AS n
    FROM loan_level_transitions
    WHERE monthly_reporting_period <= {BACKTEST_TRAIN_CUTOFF}
    GROUP BY state_t, state_t_plus_1;
    """)
    oos_counts_df = con.execute("SELECT * FROM v_oos_transitions").df()
    C_oos = counts_df_to_array(oos_counts_df)
    Q_oos, R_oos, _, _, _ = build_markov_matrices(C_oos)
    pd_12m_oos = compute_12month_pd(Q_oos, R_oos)
    print(f"[OOS Model] Estimated 12-Month PD from <= {BACKTEST_TRAIN_CUTOFF} data: {pd_12m_oos:.6f}")

    # 2. Extract snapshot of performing Stage 1 (Current) loans at 201812
    con.execute(f"""
    CREATE OR REPLACE TABLE oos_snapshot_201812 AS
    SELECT loan_id, current_actual_upb
    FROM clean_monthly_performance
    WHERE monthly_reporting_period = {BACKTEST_SNAPSHOT}
      AND loan_state = 'Current'
      AND zero_balance_code IS NULL;
    """)
    snap_count = con.execute("SELECT COUNT(*) FROM oos_snapshot_201812").fetchone()[0]
    expected_defaults = snap_count * pd_12m_oos
    print(f"[OOS Snapshot] Stage 1 (Current) loans at {BACKTEST_SNAPSHOT}: {snap_count:,}")
    print(f"[OOS Prediction] Expected 2019 Defaults: {expected_defaults:.2f} ({expected_defaults / snap_count * 100:.3f}%)")

    # 3. Query realized 2019 defaults from clean untruncated layer
    actual_defaults = con.execute(f"""
    SELECT COUNT(DISTINCT s.loan_id)
    FROM oos_snapshot_201812 s
    INNER JOIN clean_monthly_performance p ON s.loan_id = p.loan_id
    WHERE p.monthly_reporting_period BETWEEN 201901 AND 201912
      AND p.loan_state = 'Default';
    """).fetchone()[0]
    actual_rate = (actual_defaults / snap_count * 100) if snap_count > 0 else 0
    print(f"[OOS Realized] Actual 2019 Defaults: {actual_defaults:,} ({actual_rate:.3f}%)")

    diff = expected_defaults - actual_defaults
    error_pct = (diff / actual_defaults * 100) if actual_defaults > 0 else 0
    print(f"[OOS Backtest Result] Absolute Diff: {diff:+.2f} loans | Prediction Error: {error_pct:+.2f}%")
    
    # Binomial Z-Score Traffic Light Test
    import math
    variance = snap_count * pd_12m_oos * (1 - pd_12m_oos)
    z_score = (actual_defaults - expected_defaults) / math.sqrt(variance) if variance > 0 else 0
    if abs(z_score) <= 1.96:
        status = "🟢 GREEN (Pass)"
    elif abs(z_score) <= 2.58:
        status = "🟡 AMBER (Borderline)"
    else:
        status = "🔴 RED (Fail)"
    print(f"[OOS Traffic Light] Z-Score: {z_score:+.2f} | Status: {status}")
    
    return expected_defaults, actual_defaults
