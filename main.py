"""
Main Execution Script: Residential Mortgage Credit Risk Engine
Phases 1-3: Panel Construction, Absorbing Markov ECL & FICO Risk Segmentation
"""
import argparse
import sys
import time
from src.db import get_connection
from src.ingestion import audit_files, ingest_raw_data
from src.layers import (
    build_layer1_clean_performance,
    build_layer2_truncated_performance,
    build_layer3_transitions,
    build_vintage_curve_views,
    build_ecl_snapshot
)
from src.lgd import build_lgd_views, compute_lgd_bounds
from src.markov import build_transition_views, compute_fico_segmented_ecl
from src.diagnostics import check_monotonicity, build_fast_loan_tensor, bootstrap_portfolio_ecl
from src.backtest import run_oos_backtest

def main():
    parser = argparse.ArgumentParser(description="Freddie Mac Credit Risk & Absorbing Markov Engine")
    parser.add_argument("--orig", type=str, default="data/orig_*.txt", help="Origination files glob pattern")
    parser.add_argument("--svcg", type=str, default="data/perf_*.txt", help="Performance / servicing files glob pattern")
    parser.add_argument("--db", type=str, default="mortgage_risk.duckdb", help="DuckDB database path")
    parser.add_argument("--skip-ingest", action="store_true", help="Skip raw ingestion if already loaded in db")
    parser.add_argument("--boot-draws", type=int, default=500, help="Number of bootstrap draws for ECL uncertainty")
    args = parser.parse_args()

    start_time = time.time()
    print("=" * 70)
    print("   Residential Mortgage Credit Risk Engine (Phases 1–3)")
    print("   Barclays / JPMC / StanChart GCC Portfolio Provisioning")
    print("=" * 70)

    con = get_connection(args.db)

    # 1. Section 0: Audit & Ingestion
    if not args.skip_ingest:
        orig_cols, svcg_cols = audit_files(args.orig, args.svcg)
        ingest_raw_data(con, args.orig, args.svcg, orig_cols, svcg_cols)
    else:
        print("[Setup] Skipping raw ingestion (using existing database tables).")

    # Start-up assertion: Check max period
    max_period_res = con.execute("SELECT MAX(CAST(monthly_reporting_period AS INT)) FROM raw_performance").fetchone()[0]
    if max_period_res is None or max_period_res < 202002:
        raise ValueError(f"Startup check failed: raw_performance max period is {max_period_res}, expected >= 202002")

    # 2. Section 2.2: Layer 1 Clean Performance
    build_layer1_clean_performance(con)
    # Verification Gate: loan_state distribution
    dist = con.execute("SELECT loan_state, COUNT(*) FROM clean_monthly_performance GROUP BY loan_state").fetchall()
    print("[Verification] loan_state distribution:", dist)

    # 3. Section 2.3: Layer 2 Truncated Performance
    build_layer2_truncated_performance(con)
    # Verification Gate: zero post-default rows
    post_default_cnt = con.execute("""
        SELECT COUNT(*) FROM truncated_performance t
        INNER JOIN (
            SELECT loan_id, MIN(monthly_reporting_period) as first_default 
            FROM clean_monthly_performance WHERE loan_state='Default' GROUP BY loan_id
        ) f ON t.loan_id = f.loan_id
        WHERE t.monthly_reporting_period > f.first_default
    """).fetchone()[0]
    print(f"[Verification] Post-default rows in truncated_performance: {post_default_cnt}")
    assert post_default_cnt == 0, "Found post-default rows in truncated_performance!"

    # 4. Section 2.4: Layer 3 Transitions
    build_layer3_transitions(con)

    # 5. Section 2.5: Vintage Curves
    build_vintage_curve_views(con)

    # 6. Section 2.6: ECL Snapshot at 201912
    build_ecl_snapshot(con)
    # Verification Gate: snapshot loan count > 0
    snap_count = con.execute("SELECT COUNT(*) FROM ecl_snapshot").fetchone()[0]
    print(f"[Verification] Snapshot loan count at 201912: {snap_count}")
    if snap_count == 0:
        raise ValueError("Startup check failed: Snapshot loan count is 0 at 201912.")

    # 7. Section 3: LGD Cohort Statistics (Two-Factor Bounded)
    build_lgd_views(con)
    lgd_lower, lgd_upper, lgd_midpoint = compute_lgd_bounds(con)

    # 8. Section 4 & 5: Absorbing Markov Chain & FICO Stratified ECL (Flag 1 Fixed)
    build_transition_views(con)
    snapshot_df, fico_pds, C_portfolio = compute_fico_segmented_ecl(con, lgd_midpoint)

    # 9. Section 5.3: Monotonicity Diagnostics
    check_monotonicity(fico_pds)

    # 10. Section 5.2: Fast DuckDB 3D Tensor & Bootstrap ECL (Flag 2 Fixed)
    C_loan_counts, unique_loans = build_fast_loan_tensor(con)
    bootstrap_portfolio_ecl(C_loan_counts, C_portfolio, snapshot_df, lgd_lower, lgd_upper, n_boot=args.boot_draws)

    # 11. Section 8: Out-of-Sample Backtest (2018 -> 2019)
    run_oos_backtest(con)

    elapsed = time.time() - start_time
    print("\n" + "=" * 70)
    print(f"   Execution Successfully Completed in {elapsed:.2f} seconds.")
    print("=" * 70)

if __name__ == "__main__":
    main()
