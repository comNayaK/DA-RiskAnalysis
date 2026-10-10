import duckdb
import numpy as np

con = duckdb.connect('mortgage_risk.duckdb')
from src.layers import build_layer1_clean_performance, build_layer2_truncated_performance, build_layer3_transitions
from src.markov import counts_df_to_array, build_markov_matrices, compute_12month_pd
from src.config import BACKTEST_TRAIN_CUTOFF

def run_bt(policy):
    print(f"\n--- Backtest: {policy} ---")
    build_layer1_clean_performance(con, mod_policy=policy)
    build_layer2_truncated_performance(con)
    build_layer3_transitions(con)
    
    df_port = con.execute(f"SELECT state_t, state_t_plus_1, COUNT(*) as n FROM loan_level_transitions WHERE monthly_reporting_period <= {BACKTEST_TRAIN_CUTOFF} GROUP BY 1,2").df()
    C_p = counts_df_to_array(df_port)
    Q_p, R_p, _, _, _ = build_markov_matrices(C_p)
    pd_12 = compute_12month_pd(Q_p, R_p)
    
    sc = con.execute("SELECT COUNT(*) FROM oos_snapshot_201812").fetchone()[0]
    act = con.execute("SELECT COUNT(DISTINCT s.loan_id) FROM oos_snapshot_201812 s INNER JOIN clean_monthly_performance p ON s.loan_id = p.loan_id WHERE p.monthly_reporting_period BETWEEN 201901 AND 201912 AND p.loan_state = 'Default'").fetchone()[0]
    
    exp = sc * pd_12
    z = (act - exp) / np.sqrt(exp)
    print(f"Expected: {exp:.1f}, Actual: {act}")
    print(f"Z-Score: {z:.2f}")

run_bt('purge')
run_bt('censor')
