import duckdb
import pandas as pd
import numpy as np
import math
import statsmodels.api as sm
import statsmodels.formula.api as smf
import sys
sys.path.append('.')
from src.markov import compute_12month_pd, build_markov_matrices

def wilson(k, n, confidence=0.95):
    if n == 0: return 0.0, 0.0, 0.0
    z = 1.96
    p = k / n
    denominator = 1 + z**2/n
    center = (p + z**2 / (2*n)) / denominator
    half_width = z * math.sqrt(p*(1-p)/n + z**2/(4*n**2)) / denominator
    return p, max(0, center - half_width), min(1, center + half_width)

def run():
    con = duckdb.connect('mortgage_risk.duckdb')
    
    print("="*80)
    print(" 1. FULL INGESTION GATES & 2014 SAMPLE RECONCILIATION")
    print("="*80)
    
    # 2014 sample vs 2014Q1
    vintage_2014 = con.execute("SELECT COUNT(*) FROM raw_origination WHERE loan_id LIKE 'F14%'").fetchone()[0]
    print(f"2014 Sample Originations (raw_origination): {vintage_2014}")
    
    q_2014_snap = """
    SELECT 
        COUNT(*) as total_loans,
        SUM(CASE WHEN loan_state = 'Default' THEN 1 ELSE 0 END) as defaults,
        SUM(CASE WHEN zero_balance_code IS NULL THEN 1 ELSE 0 END) as active
    FROM clean_monthly_performance
    WHERE monthly_reporting_period = 201812 AND loan_id LIKE 'F14%'
    """
    df_2014_snap = con.execute(q_2014_snap).df()
    print("2014 Sample at 201812 Snapshot:")
    print(df_2014_snap.to_string(index=False))
    
    # Gates
    raw_orig = con.execute("SELECT COUNT(*) FROM raw_origination").fetchone()[0]
    raw_perf = con.execute("SELECT COUNT(*) FROM raw_performance").fetchone()[0]
    clean_perf = con.execute("SELECT COUNT(*) FROM clean_monthly_performance").fetchone()[0]
    print(f"\nRaw Origination Rows: {raw_orig:,}")
    print(f"Raw Performance Rows: {raw_perf:,}")
    print(f"Clean Performance Rows: {clean_perf:,}")
    
    # loan_state dist
    dist = con.execute("SELECT loan_state, COUNT(*) as c FROM clean_monthly_performance GROUP BY loan_state ORDER BY c DESC").df()
    print("\nloan_state distribution:")
    print(dist.to_string(index=False))
    
    post_def = con.execute("""
        SELECT COUNT(*) FROM truncated_performance t
        INNER JOIN (
            SELECT loan_id, MIN(monthly_reporting_period) as first_def 
            FROM clean_monthly_performance WHERE loan_state='Default' GROUP BY loan_id
        ) f ON t.loan_id = f.loan_id
        WHERE t.monthly_reporting_period > f.first_def
    """).fetchone()[0]
    print(f"Post-default rows in truncated_performance: {post_def}")

    print("\n" + "="*80)
    print(" 2. LOAN AGE LABELS & VINTAGE x CALENDAR YEAR (2014-2019)")
    print("="*80)
    
    # Check loan_age distribution for 2016 vintage at 201812
    q_age_check = """
    SELECT loan_age, COUNT(*) as c 
    FROM clean_monthly_performance 
    WHERE monthly_reporting_period = 201812 AND loan_id LIKE 'F16%'
    GROUP BY loan_age ORDER BY c DESC LIMIT 10
    """
    print("Top 10 loan_age values for 2016 vintage at 201812:")
    print(con.execute(q_age_check).df().to_string(index=False))
    
    # Vintage x Calendar Year PD 2014-2019
    q_vc = """
    WITH snaps AS (
        SELECT 
            p.loan_id,
            CAST(SUBSTRING(p.loan_id, 2, 2) AS INT) + 2000 as vintage,
            CAST(SUBSTRING(CAST(p.monthly_reporting_period AS VARCHAR), 1, 4) AS INT) + 1 as calendar_year,
            p.loan_age
        FROM clean_monthly_performance p
        WHERE SUBSTRING(CAST(p.monthly_reporting_period AS VARCHAR), 5, 2) = '12'
          AND p.loan_state = 'Current'
          AND p.zero_balance_code IS NULL
    ),
    defaults AS (
        SELECT DISTINCT p.loan_id, CAST(SUBSTRING(CAST(p.monthly_reporting_period AS VARCHAR), 1, 4) AS INT) as def_year
        FROM clean_monthly_performance p
        WHERE p.loan_state = 'Default'
    )
    SELECT 
        s.vintage,
        s.calendar_year,
        FLOOR(s.loan_age / 12) * 12 as age_floor,
        COUNT(DISTINCT s.loan_id) as obs_count,
        COUNT(DISTINCT d.loan_id) as default_count
    FROM snaps s
    LEFT JOIN defaults d ON s.loan_id = d.loan_id AND s.calendar_year = d.def_year
    WHERE s.calendar_year BETWEEN 2014 AND 2019
    GROUP BY s.vintage, s.calendar_year, age_floor
    ORDER BY s.calendar_year, s.vintage
    """
    df_vc = con.execute(q_vc).df()
    
    # Compute PD and CIs
    df_vc['pd_12m'] = 0.0
    for idx, row in df_vc.iterrows():
        p, l, u = wilson(row['default_count'], row['obs_count'])
        df_vc.at[idx, 'pd_12m'] = p
        df_vc.at[idx, 'pd_str'] = f"{p:.4%} [{l:.4%}, {u:.4%}]"
    
    print("\nVintage x Calendar Year (12m PD from Current):")
    print(df_vc[['calendar_year', 'vintage', 'age_floor', 'obs_count', 'default_count', 'pd_str']].to_string(index=False))
    
    # Poisson GLM
    if len(df_vc) > 0:
        df_vc['log_obs'] = np.log(df_vc['obs_count'].clip(lower=1))
        # Filter where obs_count > 0 to avoid log(0) issues and meaningless fits
        df_fit = df_vc[df_vc['obs_count'] > 0].copy()
        try:
            model = smf.glm('default_count ~ vintage + calendar_year + age_floor', 
                            data=df_fit, 
                            family=sm.families.Poisson(),
                            offset=df_fit['log_obs'])
            res = model.fit()
            print("\nPoisson GLM Fit (age + vintage + calendar_year):")
            print(res.summary().tables[1])
        except Exception as e:
            print(f"GLM fit failed: {e}")

    print("\n" + "="*80)
    print(" 3. STAGE 1 PD RECONCILIATION")
    print("="*80)
    
    print("Direct Pooled 2019 Rate (from 201812 snapshot):")
    q_dir = """
    SELECT 
        COUNT(DISTINCT s.loan_id) as obs_count,
        SUM(CASE WHEN d.loan_id IS NOT NULL THEN 1 ELSE 0 END) as defaults
    FROM (SELECT loan_id FROM clean_monthly_performance WHERE monthly_reporting_period = 201812 AND loan_state = 'Current' AND zero_balance_code IS NULL) s
    LEFT JOIN (SELECT DISTINCT loan_id FROM clean_monthly_performance WHERE monthly_reporting_period BETWEEN 201901 AND 201912 AND loan_state = 'Default') d ON s.loan_id = d.loan_id
    """
    df_dir = con.execute(q_dir).df()
    obs = df_dir['obs_count'][0]
    defs = df_dir['defaults'][0]
    pd_dir, l, u = wilson(defs, obs)
    print(f"Observations: {obs:,}, Defaults: {defs:,}")
    print(f"Direct PD: {pd_dir:.5%} [{l:.5%}, {u:.5%}]")
    
    print("\nMarkov Matrix 12m PD (Trained on <=201812):")
    # Re-build full Markov on <=201812
    con.execute("""
    CREATE OR REPLACE VIEW v_oos_transitions AS
    SELECT state_t, state_t_plus_1, COUNT(*) AS n
    FROM loan_level_transitions
    WHERE monthly_reporting_period <= 201812
    GROUP BY state_t, state_t_plus_1;
    """)
    oos_counts_df = con.execute("SELECT * FROM v_oos_transitions").df()
    states_order = ['Current', '30_DPD', '60_DPD', 'Default', 'Paid_Off', 'Admin_Removal', 'Modified']
    state_to_idx = {s: i for i, s in enumerate(states_order)}
    C_train = np.zeros((7, 7))
    for _, r in oos_counts_df.iterrows():
        if r['state_t'] in state_to_idx and r['state_t_plus_1'] in state_to_idx:
            C_train[state_to_idx[r['state_t']], state_to_idx[r['state_t_plus_1']]] += r['n']
    
    Q_train = np.zeros((3, 3))
    R_train = np.zeros((3, 4))
    for i in range(3):
        row_sum = C_train[i].sum()
        if row_sum > 0:
            Q_train[i, :] = C_train[i, :3] / row_sum
            R_train[i, :] = C_train[i, 3:7] / row_sum
            
    P_12 = np.zeros((3, 4))
    for t in range(12):
        P_12 += np.linalg.matrix_power(Q_train, t) @ R_train
    pd_markov = P_12[0, 0]
    print(f"Markov PD: {pd_markov:.5%}")
    print(f"Conclusion: Stage 1 PD for ECL should be {pd_dir:.5%}, not 0.283% (which was single-vintage).")

    print("\n" + "="*80)
    print(" 4. LGD PURGE VS CENSOR & BUCKETS")
    print("="*80)
    q_censor = """
    WITH cohort AS (
        SELECT 
            p.loan_id,
            f.first_default_period,
            MAX(CASE WHEN month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) <= 36 AND p.loan_state = 'Modified' THEN 1 ELSE 0 END) as mod_flag,
            MAX(CASE WHEN month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) <= 36 THEN p.loan_state END) as last_state,
            MAX(CASE WHEN month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) <= 36 THEN p.zero_balance_code END) as zbc,
            MAX(CASE WHEN month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) = 0 THEN p.current_actual_upb END) as default_upb
        FROM clean_monthly_performance p
        INNER JOIN v_first_default f ON p.loan_id = f.loan_id
        WHERE f.first_default_period <= 201612
        GROUP BY p.loan_id, f.first_default_period
    ),
    outcomes AS (
        SELECT 
            loan_id,
            default_upb,
            CASE 
                WHEN mod_flag = 1 THEN 'Modified'
                WHEN zbc IN ('02', '03', '09') THEN 'Liquidated'
                WHEN zbc = '01' THEN 'Paid_Off'
                WHEN last_state IN ('Current', '30_DPD') THEN 'Cured_Active'
                WHEN last_state IN ('60_DPD', 'Default') THEN 'Still_In_Default'
                ELSE 'Other'
            END as outcome
        FROM cohort
    )
    SELECT outcome, COUNT(*) as count, SUM(default_upb) as dol
    FROM outcomes
    GROUP BY outcome ORDER BY dol DESC
    """
    df_censor = con.execute(q_censor).df()
    
    # LGD Purge (Exclude Modified)
    df_purge = df_censor.copy()
    
    print("36m Outcome Buckets (Censor/Baseline):")
    print(df_censor.to_string(index=False))
    
    liq_censor = df_censor[df_censor['outcome'] == 'Liquidated']['dol'].sum()
    tot_censor = df_censor['dol'].sum()
    p_liq_censor = liq_censor / tot_censor if tot_censor else 0
    
    print("\n36m Outcome Buckets (Purge Modified):")
    print(df_purge.to_string(index=False))
    
    # Exclude modified from denominator for Purge LGD
    liq_purge = df_purge[df_purge['outcome'] == 'Liquidated']['dol'].sum()
    tot_purge = df_purge[df_purge['outcome'] != 'Modified']['dol'].sum()
    p_liq_purge = liq_purge / tot_purge if tot_purge else 0
    
    severity = 0.3132 # From previous output
    print(f"\nCensor P(liq) = {p_liq_censor:.4f} -> LGD = {p_liq_censor * severity:.4%}")
    print(f"Purge P(liq) = {p_liq_purge:.4f} -> LGD = {p_liq_purge * severity:.4%}")

    print("\n" + "="*80)
    print(" 5. FULL BACKTEST BY STATE (Traffic Light)")
    print("="*80)
    
    # Get all active loans at 201812
    q_snap = """
    SELECT loan_state, COUNT(*) as obs_count
    FROM clean_monthly_performance
    WHERE monthly_reporting_period = 201812 AND zero_balance_code IS NULL
      AND loan_state IN ('Current', '30_DPD', '60_DPD', 'Modified')
    GROUP BY loan_state
    """
    df_snap = con.execute(q_snap).df()
    
    # Get defaults in 2019 for these loans
    q_def = """
    SELECT s.loan_state, COUNT(DISTINCT d.loan_id) as default_count
    FROM (SELECT loan_id, loan_state FROM clean_monthly_performance WHERE monthly_reporting_period = 201812 AND zero_balance_code IS NULL) s
    INNER JOIN (SELECT DISTINCT loan_id FROM clean_monthly_performance WHERE monthly_reporting_period BETWEEN 201901 AND 201912 AND loan_state = 'Default') d ON s.loan_id = d.loan_id
    GROUP BY s.loan_state
    """
    df_def = con.execute(q_def).df()
    df_backtest = df_snap.merge(df_def, on='loan_state', how='left').fillna(0)
    
    # Attach Expected PDs (Markov for Current/30/60, Pooled Hazard for Mod)
    pds = {
        'Current': P_12[0, 0],
        '30_DPD': P_12[1, 0],
        '60_DPD': P_12[2, 0],
        'Modified': 0.2250 # from previous pooled hazard
    }
    
    for idx, row in df_backtest.iterrows():
        state = row['loan_state']
        n = row['obs_count']
        act = row['default_count']
        pd_exp = pds.get(state, 0)
        exp = n * pd_exp
        z = (act - exp) / math.sqrt(n * pd_exp * (1 - pd_exp)) if n > 0 else 0
        df_backtest.at[idx, 'Expected'] = exp
        df_backtest.at[idx, 'Z-Score'] = z
        if abs(z) <= 1.96: df_backtest.at[idx, 'Traffic'] = '🟢 GREEN'
        elif abs(z) <= 2.58: df_backtest.at[idx, 'Traffic'] = '🟡 AMBER'
        else: df_backtest.at[idx, 'Traffic'] = '🔴 RED'
        
    print(df_backtest[['loan_state', 'obs_count', 'Expected', 'default_count', 'Z-Score', 'Traffic']].to_string(index=False))

    print("\n" + "="*80)
    print(" 6. 60 DPD 12M PD vs LIFETIME PD")
    print("="*80)
    print(f"60 DPD 12-Month PD (Markov): {P_12[2, 0]:.4%}")
    # Lifetime PD: B = (I-Q)^-1 * R
    I_minus_Q_inv = np.linalg.inv(np.eye(3) - Q_train)
    B = I_minus_Q_inv @ R_train
    print(f"60 DPD Lifetime PD (Markov B matrix): {B[2, 0]:.4%}")
    print("Check: Lifetime >= 12m? ", B[2, 0] >= P_12[2, 0])

    print("\n" + "="*80)
    print(" 7. FALLBACK EVENTS PER CELL (WILSON CIs)")
    print("="*80)
    q_fico = """
    SELECT fico_band, state_t, SUM(n) as row_sum,
           SUM(CASE WHEN state_t_plus_1 = 'Default' THEN n ELSE 0 END) as def_trans
    FROM v_transition_matrix_fico 
    GROUP BY fico_band, state_t
    """
    df_fico = con.execute(q_fico).df()
    for idx, row in df_fico.iterrows():
        p, l, u = wilson(row['def_trans'], row['row_sum'])
        df_fico.at[idx, 'monthly_pd'] = f"{p:.4%} [{l:.4%}, {u:.4%}]"
    print(df_fico[['fico_band', 'state_t', 'row_sum', 'def_trans', 'monthly_pd']].to_string(index=False))

if __name__ == '__main__':
    run()
