import duckdb
import numpy as np
import pandas as pd
from src.db import get_connection
from src.markov import build_transition_views, compute_fico_segmented_ecl, build_markov_matrices, compute_12month_pd
from src.diagnostics import build_fast_loan_tensor, bootstrap_portfolio_ecl, wilson_interval
from src.lgd import compute_lgd_bounds

def main():
    con = get_connection("mortgage_risk.duckdb")
    
    # Get total loans modified
    mod_count = con.execute("SELECT COUNT(DISTINCT loan_id) FROM clean_monthly_performance WHERE loan_state = 'Modified'").fetchone()[0]
    print(f"Loans censored due to modification: {mod_count}")
    
    # Monotonicity CIs for 60 DPD -> Default
    print("\n--- Monotonicity CIs for 60 DPD -> Default ---")
    df_trans = con.execute("""
        SELECT fico_band, state_t, state_t_plus_1, COUNT(*) as n
        FROM loan_level_transitions
        WHERE state_t = '60_DPD'
        GROUP BY fico_band, state_t, state_t_plus_1
    """).df()
    
    for fico in ['High-FICO', 'Mid-FICO', 'Lower-FICO']:
        sub = df_trans[df_trans['fico_band'] == fico]
        n_total = sub['n'].sum()
        n_def = sub[sub['state_t_plus_1'] == 'Default']['n'].sum() if 'Default' in sub['state_t_plus_1'].values else 0
        p_hat = n_def / n_total if n_total > 0 else 0
        ci_lower, ci_upper = wilson_interval(n_def, n_total)
        print(f"[{fico:10s}] 60 DPD -> Default | n={n_total:5.0f} | def={n_def:5.0f} | PD={p_hat:.4f} | 95% CI: [{ci_lower:.4f}, {ci_upper:.4f}]")

    # Bootstrap with fixed LGD
    lgd_lower, lgd_upper, lgd_midpoint = compute_lgd_bounds(con)
    print(f"\n--- Bootstrap with fixed LGD = {lgd_midpoint:.4f} ---")
    snapshot_df, fico_pds, C_portfolio = compute_fico_segmented_ecl(con, lgd_midpoint)
    C_loan_counts, unique_loans = build_fast_loan_tensor(con)
    
    bootstrap_portfolio_ecl(C_loan_counts, C_portfolio, snapshot_df, lgd_midpoint, lgd_midpoint, n_boot=100)

if __name__ == "__main__":
    main()
