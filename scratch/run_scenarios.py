import duckdb
from src.layers import build_layer1_clean_performance, build_layer2_truncated_performance, build_layer3_transitions, build_ecl_snapshot
from src.lgd import build_lgd_views
from src.markov import build_transition_views, compute_fico_segmented_ecl
from src.diagnostics import bootstrap_portfolio_ecl, build_fast_loan_tensor

con = duckdb.connect('mortgage_risk.duckdb')

def run_scenario(policy_name: str, mod_policy: str, lgd_index: int):
    print(f"\n==============================================")
    print(f"   RUNNING SCENARIO: {policy_name}")
    print(f"==============================================")
    
    build_layer1_clean_performance(con, mod_policy=mod_policy)
    build_layer2_truncated_performance(con)
    build_layer3_transitions(con)
    build_ecl_snapshot(con)
    
    build_lgd_views(con)
    from src.lgd import compute_lgd_bounds
    
    stats = con.execute("""
        SELECT 
            o.outcome,
            COUNT(*) as count,
            SUM(u.default_upb) as dol
        FROM v_default_outcomes_36m o
        INNER JOIN v_first_default_upb u ON o.loan_id = u.loan_id
        GROUP BY o.outcome
    """).df()
    
    dol_liquidated = stats.loc[stats['outcome'] == 'Liquidated', 'dol'].sum() if 'Liquidated' in stats['outcome'].values else 0
    dol_total = stats.loc[stats['outcome'] != 'Admin_Removed', 'dol'].sum()
    dol_total_excl_mod = stats.loc[~stats['outcome'].isin(['Admin_Removed', 'Modified']), 'dol'].sum()
    
    severity_df = con.execute("SELECT * FROM v_lgd_severity_36m").df()
    sev_36 = severity_df['empirical_loss_severity'].values[0] if len(severity_df) > 0 and severity_df['empirical_loss_severity'].values[0] is not None else 0.25
    
    p_liq = dol_liquidated / dol_total if dol_total > 0 else 0
    p_liq_excl_mod = dol_liquidated / dol_total_excl_mod if dol_total_excl_mod > 0 else 0
    
    lgd = 0
    if lgd_index == 0:
        lgd = p_liq * sev_36
        print(f"Using standard LGD (purge/censor): {lgd:.4f}")
    elif lgd_index == 1:
        lgd = p_liq_excl_mod * sev_36
        print(f"Using exclude-Modified LGD: {lgd:.4f}")

    build_transition_views(con)
    snapshot_df, fico_pds, C_portfolio = compute_fico_segmented_ecl(con, lgd)
    print("\nECL Summary Computed.")
    
    # Let's get total ECL directly from snapshot_df
    total_ecl = snapshot_df['ecl'].sum()
    print(f"Total Portfolio ECL (Point Estimate): ${total_ecl:,.2f}")

run_scenario("Purge (Baseline)", "purge", 0)
run_scenario("Censor (Modified Included in denom)", "censor", 0)
run_scenario("Censor (Exclude-Modified)", "censor", 1)

