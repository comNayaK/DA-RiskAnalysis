"""
Phase 2: Absorbing Markov Chain & Risk-Stratified ECL Engine
Fixes Execution Flag 1: True FICO-Stratified Staged ECL Vectorization
"""
import duckdb
import numpy as np
import pandas as pd
from src.config import TRANSIENT_STATES, ABSORBING_STATES, ALL_STATES, FICO_BANDS

def build_transition_views(con: duckdb.DuckDBPyConnection):
    """
    Creates views for portfolio-level and FICO-segmented transition counts & p_hat.
    """
    print("[Markov] Creating transition views...")
    con.execute("""
    -- Portfolio-level transition counts
    CREATE OR REPLACE VIEW v_transition_matrix_portfolio AS
    SELECT
        state_t,
        state_t_plus_1,
        COUNT(*) AS n,
        ROUND(COUNT(*) * 1.0 / SUM(COUNT(*)) OVER (PARTITION BY state_t), 6) AS p_hat
    FROM loan_level_transitions
    GROUP BY state_t, state_t_plus_1;

    -- FICO-segmented transition counts
    CREATE OR REPLACE VIEW v_transition_matrix_fico AS
    SELECT
        fico_band,
        state_t,
        state_t_plus_1,
        COUNT(*) AS n,
        ROUND(COUNT(*) * 1.0 / SUM(COUNT(*)) OVER (PARTITION BY fico_band, state_t), 6) AS p_hat
    FROM loan_level_transitions
    WHERE fico_band IN ('High-FICO', 'Mid-FICO', 'Lower-FICO')
    GROUP BY fico_band, state_t, state_t_plus_1;
    """)

def counts_df_to_array(df_counts: pd.DataFrame) -> np.ndarray:
    """
    Converts a DataFrame with columns [state_t, state_t_plus_1, n]
    into a (3, 5) count matrix C aligned to TRANSIENT x ALL_STATES.
    """
    C = np.zeros((3, 5), dtype=float)
    for _, row in df_counts.iterrows():
        st = row['state_t']
        st1 = row['state_t_plus_1']
        if st in TRANSIENT_STATES and st1 in ALL_STATES:
            i = TRANSIENT_STATES.index(st)
            j = ALL_STATES.index(st1)
            C[i, j] = row['n']
    return C

def build_markov_matrices(C: np.ndarray, C_portfolio: np.ndarray = None, min_row_n: int = 100):
    """
    Builds Q, R, N, B, P from a (3, 5) count matrix C.
    Applies row substitution from C_portfolio if a row has count < min_row_n.
    Returns: Q (3x3), R (3x2), N (3x3), B (3x2), P (3x5)
    """
    C_work = C.copy()
    row_ns = C_work.sum(axis=1)
    
    for i in range(3):
        if row_ns[i] < min_row_n:
            if C_portfolio is None:
                raise ValueError(
                    f"Row {TRANSIENT_STATES[i]} has n={int(row_ns[i])} < {min_row_n} "
                    f"and no portfolio fallback was supplied."
                )
            print(f"[Markov Fallback] Row '{TRANSIENT_STATES[i]}' substituted from portfolio matrix (n={int(row_ns[i])} < {min_row_n})")
            C_work[i, :] = C_portfolio[i, :]

    # Normalize rows to probabilities
    row_totals = C_work.sum(axis=1, keepdims=True)
    # Avoid zero division if empty
    row_totals = np.where(row_totals == 0, 1.0, row_totals)
    P = C_work / row_totals

    # Count reconciliation
    if np.any(row_totals == 0):
        raise ValueError("Count reconciliation failed: Found row with 0 total transitions.")

    Q = P[:, :3]  # Transient -> Transient (Current, 30_DPD, 60_DPD)
    R = P[:, 3:]  # Transient -> Absorbing (Paid_Off, Default)

    # Check Spectral Radius of Q
    eigenvalues = np.linalg.eigvals(Q)
    spectral_radius = np.max(np.abs(eigenvalues))
    if spectral_radius >= 1.0:
        raise ValueError(f"Absorbing Markov assumption violated: Spectral radius of Q is {spectral_radius:.4f} >= 1")

    # Calibrated range check for Current -> Current (accounts for prepayment)
    if not (0.95 <= P[0, 0] <= 0.995):
        print(f"[Warning] Current -> Current transition {P[0,0]:.4f} outside calibrated range [0.95, 0.995].")

    # Fundamental matrix: N = (I - Q)^(-1)
    N = np.linalg.inv(np.eye(3) - Q)

    # Absorption matrix: B = N * R; Column 1 is lifetime PD to Default
    B = np.dot(N, R)

    return Q, R, N, B, P

def compute_12month_pd(Q: np.ndarray, R: np.ndarray) -> float:
    """
    Computes 12-month horizon PD for Stage 1 (Current) loans using the 12th matrix power.
    """
    P_bar = np.block([
        [Q, R],
        [np.zeros((2, 3)), np.eye(2)]
    ])
    P_bar_12 = np.linalg.matrix_power(P_bar, 12)
    # Row 0 (Current) -> Column 4 (Default) after 12 months
    return float(P_bar_12[0, 4])

def compute_fico_segmented_ecl(con: duckdb.DuckDBPyConnection, lgd: float):
    """
    Fixes Flag 1: Computes true FICO-stratified absorbing Markov matrices and
    vectorized staged ECL on the snapshot.
    """
    # 1. Portfolio matrix
    C_port_df = con.execute("SELECT state_t, state_t_plus_1, n FROM v_transition_matrix_portfolio").df()
    C_portfolio = counts_df_to_array(C_port_df)
    
    # Count reconciliation
    total_transitions = con.execute("SELECT COUNT(*) FROM loan_level_transitions").fetchone()[0]
    matrix_sum = C_portfolio.sum()
    if matrix_sum != total_transitions:
        print(f"Warning: Count reconciliation mismatch: C_portfolio sum ({matrix_sum}) != loan_level_transitions count ({total_transitions}). Missing {total_transitions - matrix_sum} rows.")
        
    Q_p, R_p, N_p, B_p, P_p = build_markov_matrices(C_portfolio)
    
    # 2. Segmented matrices
    fico_pds = {}
    for band in FICO_BANDS:
        df_b = con.execute(f"""
            SELECT state_t, state_t_plus_1, n 
            FROM v_transition_matrix_fico 
            WHERE fico_band = '{band}'
        """).df()
        C_band = counts_df_to_array(df_b)
        Q_b, R_b, N_b, B_b, P_b = build_markov_matrices(C_band, C_portfolio)
        fico_pds[band] = {
            'pd_12m': compute_12month_pd(Q_b, R_b),
            'pd_lifetime_current': B_b[0, 1],
            'pd_lifetime_30dpd': B_b[1, 1],
            'pd_lifetime_60dpd': B_b[2, 1],
            'B': B_b
        }
        
    # Fallback for Unknown band
    fico_pds['Unknown'] = {
        'pd_12m': compute_12month_pd(Q_p, R_p),
        'pd_lifetime_current': B_p[0, 1],
        'pd_lifetime_30dpd': B_p[1, 1],
        'pd_lifetime_60dpd': B_p[2, 1],
        'B': B_p
    }

    # Print summary of Segment-Specific PDs
    print("\n--- [FICO-Segmented Absorbing PD Parameters] ---")
    for band in FICO_BANDS:
        print(f"[{band:10s}] 12m PD (Current): {fico_pds[band]['pd_12m']:.4f} | "
              f"Lifetime PD (Current): {fico_pds[band]['pd_lifetime_current']:.4f} | "
              f"30 DPD: {fico_pds[band]['pd_lifetime_30dpd']:.4f} | "
              f"60 DPD: {fico_pds[band]['pd_lifetime_60dpd']:.4f}")

    # 3. Load snapshot
    snapshot_df = con.execute("SELECT * FROM ecl_snapshot").df()
    
    # 4. Vectorized ECL calculation across FICO bands
    upb = snapshot_df['snapshot_upb'].fillna(0).values
    state = snapshot_df['loan_state'].values
    band = snapshot_df['fico_band'].values
    pd_vec = np.zeros(len(snapshot_df), dtype=float)

    for b_name, pds in fico_pds.items():
        mask_band = (band == b_name)
        pd_vec[mask_band & (state == 'Current')] = pds['pd_12m']
        pd_vec[mask_band & (state == '30_DPD')] = pds['pd_lifetime_30dpd']
        pd_vec[mask_band & (state == '60_DPD')] = pds['pd_lifetime_60dpd']

    pd_vec[state == 'Default'] = 1.0

    snapshot_df['applied_pd'] = pd_vec
    snapshot_df['ecl'] = upb * pd_vec * lgd
    
    print("\n--- [Portfolio Provisioning Summary by FICO Band] ---")
    summary = snapshot_df.groupby('fico_band').agg(
        Loan_Count=('loan_id', 'count'),
        Total_UPB=('snapshot_upb', 'sum'),
        Total_ECL=('ecl', 'sum'),
        Weighted_Avg_PD=('applied_pd', lambda x: np.average(x, weights=snapshot_df.loc[x.index, 'snapshot_upb']) if snapshot_df.loc[x.index, 'snapshot_upb'].sum() > 0 else 0),
        Coverage_Rate_Pct=('ecl', lambda x: (x.sum() / snapshot_df.loc[x.index, 'snapshot_upb'].sum() * 100) if snapshot_df.loc[x.index, 'snapshot_upb'].sum() > 0 else 0)
    )
    print(summary.to_string())

    return snapshot_df, fico_pds, C_portfolio
