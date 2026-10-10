"""
Phase 3: Heterogeneity Diagnostics, Wilson Intervals & Fast Bootstrap ECL
Fixes Execution Flag 2: DuckDB-Aggregated 3D Tensor Construction for Bootstrap
"""
import duckdb
import numpy as np
import pandas as pd
from src.config import TRANSIENT_STATES, ALL_STATES, FICO_BANDS
from src.markov import build_markov_matrices, compute_12month_pd

def wilson_interval(k: float, n: float, z: float = 1.96) -> tuple:
    """
    Computes Wilson score confidence interval for small n and p near 0 or 1.
    """
    if n == 0:
        return (0.0, 0.0)
    p_hat = k / n
    centre = p_hat + (z**2) / (2 * n)
    spread = z * np.sqrt((p_hat * (1 - p_hat) / n) + (z**2) / (4 * (n**2)))
    denom = 1 + (z**2) / n
    return (max(0.0, (centre - spread) / denom), min(1.0, (centre + spread) / denom))

def check_monotonicity(fico_pds: dict):
    """
    Validates risk ranking monotonicity across FICO segments:
    PD(High) <= PD(Mid) <= PD(Lower)
    """
    print("\n--- [Monotonicity Diagnostics across FICO Tiers] ---")
    states = [('Current', 0), ('30_DPD', 1), ('60_DPD', 2)]
    
    for state_label, idx in states:
        hi = fico_pds['High-FICO']['B'][idx, 1]
        mid = fico_pds['Mid-FICO']['B'][idx, 1]
        lo = fico_pds['Lower-FICO']['B'][idx, 1]
        ordered = (hi <= mid <= lo)
        status = "PASSED [High <= Mid <= Lower]" if ordered else "VIOLATED (Inspect cell counts / sample bias)"
        print(f"[{state_label:10s}] Lifetime PD: High={hi:.4f}, Mid={mid:.4f}, Lower={lo:.4f} -> {status}")

def build_fast_loan_tensor(con: duckdb.DuckDBPyConnection):
    """
    Fixes Flag 2: Pushes transition aggregation into DuckDB, builds the 3D tensor
    shape (n_loans, 3, 5) without iterrows() memory exhaustion.
    """
    print("[Diagnostics] Aggregating loan transitions in DuckDB for 3D tensor...")
    loan_agg_df = con.execute("""
        SELECT
            loan_id,
            state_t,
            state_t_plus_1,
            COUNT(*) AS n
        FROM loan_level_transitions
        WHERE state_t_plus_1 IS NOT NULL
          AND state_t IN ('Current', '30_DPD', '60_DPD')
        GROUP BY loan_id, state_t, state_t_plus_1
    """).df()

    state_t_to_i = {s: i for i, s in enumerate(TRANSIENT_STATES)}
    state_next_to_j = {s: i for i, s in enumerate(ALL_STATES)}

    loan_agg_df['i'] = loan_agg_df['state_t'].map(state_t_to_i)
    loan_agg_df['j'] = loan_agg_df['state_t_plus_1'].map(state_next_to_j)

    unique_loans = loan_agg_df['loan_id'].unique()
    loan_to_idx = {l_id: idx for idx, l_id in enumerate(unique_loans)}
    loan_agg_df['k'] = loan_agg_df['loan_id'].map(loan_to_idx)

    n_loans = len(unique_loans)
    print(f"[Diagnostics] Constructing 3D tensor for {n_loans:,} unique loans...")
    C_loan_counts = np.zeros((n_loans, 3, 5), dtype=float)
    C_loan_counts[loan_agg_df['k'].values, loan_agg_df['i'].values, loan_agg_df['j'].values] = loan_agg_df['n'].values

    return C_loan_counts, unique_loans

def bootstrap_portfolio_ecl(
    C_loan_counts: np.ndarray,
    C_portfolio: np.ndarray,
    snapshot_df: pd.DataFrame,
    lgd_lower: float,
    lgd_upper: float,
    n_boot: int = 500,
    seed: int = 42
) -> tuple:
    """
    Executes loan-level multinomial bootstrapping over transition parameters.
    Also incorporates a uniform draw over LGD bounds as a sensitivity assumption.
    """
    print(f"\n[Bootstrap] Running {n_boot} multinomial bootstrap draws for ECL matrix uncertainty...")
    print(f"[Bootstrap] Note: Incorporating LGD [lower, upper] via uniform draw as a sensitivity assumption.")
    rng = np.random.default_rng(seed)
    n_loans = len(C_loan_counts)
    
    upb = snapshot_df['snapshot_upb'].fillna(0).values
    state = snapshot_df['loan_state'].values
    total_upb = upb.sum()
    
    ecl_totals = []
    skipped = 0

    for _ in range(n_boot):
        w = rng.multinomial(n_loans, np.full(n_loans, 1.0 / n_loans)).astype(float)
        C_boot = np.tensordot(w, C_loan_counts, axes=([0], [0]))

        try:
            Q_b, R_b, _, B_boot, _ = build_markov_matrices(C_boot, C_portfolio)
        except (ValueError, np.linalg.LinAlgError):
            skipped += 1
            continue

        pd_12m_boot = compute_12month_pd(Q_b, R_b)
        lp = B_boot[:, 1]

        pd_vec = np.where(
            state == 'Current', pd_12m_boot,
            np.where(state == '30_DPD', lp[1],
            np.where(state == '60_DPD', lp[2],
            np.where(state == 'Default', 1.0, 0.0)))
        )
        sampled_lgd = rng.uniform(lgd_lower, lgd_upper)
        ecl_totals.append((upb * pd_vec * sampled_lgd).sum())

    if skipped > 0:
        print(f"[Bootstrap Warning] Skipped {skipped} singular bootstrap draws.")

    lo, hi = np.percentile(ecl_totals, [2.5, 97.5])
    point_est = np.median(ecl_totals)
    
    # Calculate static values for lower, mid, upper LGD by stage
    print(f"\n--- [ECL Snapshot by LGD Bound and Stage] ---")
    
    # Get base PDs (from non-bootstrapped matrix, approximated here by taking median values if needed, 
    # but we just need a point estimate. We can use the portfolio matrix for this reporting)
    Q_p, R_p, _, B_p, _ = build_markov_matrices(C_portfolio)
    pd_12m_p = compute_12month_pd(Q_p, R_p)
    lp_p = B_p[:, 1]
    
    base_pd_vec = np.where(
        state == 'Current', pd_12m_p,
        np.where(state == '30_DPD', lp_p[1],
        np.where(state == '60_DPD', lp_p[2],
        np.where(state == 'Default', 1.0, 0.0)))
    )
    
    lgd_mid = (lgd_lower + lgd_upper) / 2.0
    for stage_name, mask in [('Stage 1 (Current)', state == 'Current'), 
                             ('Stage 2 (30-60 DPD)', np.isin(state, ['30_DPD', '60_DPD'])),
                             ('Stage 3 (Default)', state == 'Default')]:
        st_upb = upb[mask].sum()
        if st_upb > 0:
            st_ecl_mid = (upb[mask] * base_pd_vec[mask] * lgd_mid).sum()
            st_ecl_low = (upb[mask] * base_pd_vec[mask] * lgd_lower).sum()
            st_ecl_hi = (upb[mask] * base_pd_vec[mask] * lgd_upper).sum()
            print(f"[{stage_name:20s}] UPB: ${st_upb:,.0f} | ECL Mid: ${st_ecl_mid:,.0f} ({st_ecl_mid/st_upb*100:.2f}%) | Range: [${st_ecl_low:,.0f}, ${st_ecl_hi:,.0f}]")
    
    print(f"\n[Bootstrap Result] 95% ECL Range (Matrix Uncertainty + LGD Sensitivity):")
    print(f"                     [${lo:,.2f} - ${hi:,.2f}] ({lo/total_upb*100:.2f}% - {hi/total_upb*100:.2f}% of UPB) | Median: ${point_est:,.2f} ({point_est/total_upb*100:.2f}% of UPB)")
    return lo, hi, point_est
