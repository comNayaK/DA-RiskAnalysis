import duckdb
import numpy as np
import pandas as pd
from src.markov import counts_df_to_array, build_markov_matrices, compute_12month_pd
from src.config import PRE_COVID_CUTOFF, BACKTEST_TRAIN_CUTOFF, BACKTEST_SNAPSHOT, LGD_36M_COHORT_CUTOFF, LGD_24M_COHORT_CUTOFF

con = duckdb.connect('mortgage_risk.duckdb')

with open('output/validation_report.md', 'w') as f:
    f.write("# Validation Report and Sensitivities\n\n")

    # ---------------------------------------------------------
    # 2. Missing Outputs
    # ---------------------------------------------------------
    f.write("## 1. Purge & Gap Stats\n")
    total_loans = con.execute("SELECT COUNT(DISTINCT loan_id) FROM raw_origination").fetchone()[0]
    purged_loans = con.execute(f"SELECT COUNT(DISTINCT loan_id) FROM raw_performance WHERE CAST(monthly_reporting_period AS INT) <= {PRE_COVID_CUTOFF} AND COALESCE(modification_flag, '') IN ('Y', 'P')").fetchone()[0]
    f.write(f"- Total Loans Originated: {total_loans:,}\n")
    f.write(f"- Loans Purged due to Modification (<=202002): {purged_loans:,} ({purged_loans/total_loans*100:.2f}%)\n")
    
    states = con.execute("SELECT loan_state, COUNT(*) FROM clean_monthly_performance GROUP BY loan_state").fetchall()
    total_rows = sum(x[1] for x in states)
    uncertain = next((x[1] for x in states if x[0] == 'Uncertain_Quarantine'), 0)
    f.write(f"- Uncertain_Quarantine (Reporting Gap) Share: {uncertain:,} / {total_rows:,} ({uncertain/total_rows*100:.3f}%, target <1%)\n\n")

    f.write("## 2. LGD Outcome Buckets (24m & 36m)\n")
    # 24m Outcomes
    outcomes_24 = con.execute("SELECT outcome_24m, COUNT(*) FROM v_default_outcomes_24m GROUP BY outcome_24m").fetchall()
    f.write("### 24-Month Follow-Up\n")
    for out, cnt in outcomes_24:
        f.write(f"- {out}: {cnt}\n")
    sev_24 = con.execute("SELECT empirical_loss_severity FROM v_lgd_severity_24m").fetchone()[0]
    f.write(f"Severity 24m: {sev_24}\n\n")
    
    # 36m Outcomes (Create view)
    con.execute(f"""
    CREATE OR REPLACE VIEW v_default_outcomes_36m AS
    WITH window_rows AS (
        SELECT p.loan_id, p.loan_state, p.zero_balance_code, p.monthly_reporting_period, f.first_default_period,
            month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) AS months_since_default
        FROM clean_monthly_performance p
        INNER JOIN v_first_default f ON p.loan_id = f.loan_id
        WHERE f.first_default_period <= {LGD_36M_COHORT_CUTOFF}
          AND p.monthly_reporting_period >= f.first_default_period
          AND month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) <= 36
    ),
    last_row_per_loan AS (
        SELECT * FROM window_rows QUALIFY ROW_NUMBER() OVER (PARTITION BY loan_id ORDER BY monthly_reporting_period DESC) = 1
    )
    SELECT loan_id, first_default_period, months_since_default,
        CASE
            WHEN zero_balance_code IN ('02','03','09') THEN 'Liquidated'
            WHEN zero_balance_code = '01' THEN 'Paid_Off'
            WHEN zero_balance_code IN ('06','15','16','96') THEN 'Admin_Removed'
            WHEN loan_state = 'Default' THEN 'Still_In_Default'
            WHEN loan_state IN ('Current','30_DPD','60_DPD') THEN 'Cured_Active'
            ELSE 'Other'
        END AS outcome_36m
    FROM last_row_per_loan;
    
    CREATE OR REPLACE VIEW v_lgd_severity_36m AS
    SELECT ROUND(SUM(p.actual_loss_calculation) / NULLIF(SUM(p.zero_balance_removal_upb), 0), 4) AS empirical_loss_severity
    FROM clean_monthly_performance p
    INNER JOIN v_first_default f ON p.loan_id = f.loan_id
    WHERE f.first_default_period <= {LGD_36M_COHORT_CUTOFF}
      AND month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) <= 36
      AND p.zero_balance_code IN ('02','03','09')
      AND p.actual_loss_calculation IS NOT NULL AND p.zero_balance_removal_upb > 0;
    """)
    outcomes_36 = con.execute("SELECT outcome_36m, COUNT(*) FROM v_default_outcomes_36m GROUP BY outcome_36m").fetchall()
    f.write("### 36-Month Follow-Up\n")
    for out, cnt in outcomes_36:
        f.write(f"- {out}: {cnt}\n")
    sev_36 = con.execute("SELECT empirical_loss_severity FROM v_lgd_severity_36m").fetchone()
    sev_36 = sev_36[0] if sev_36 else None
    f.write(f"Severity 36m: {sev_36}\n\n")

    sum_loss = con.execute("SELECT SUM(actual_loss_calculation) FROM clean_monthly_performance WHERE zero_balance_code IN ('02','03','09')").fetchone()[0]
    f.write(f"- Sum of actual_loss_calculation: {sum_loss:,.2f} (Positive means loss)\n\n")

    f.write("## 3. FICO Monotonicity & Cell Count Audit\n")
    df_port = con.execute("SELECT state_t, state_t_plus_1, n FROM v_transition_matrix_portfolio").df()
    C_p = counts_df_to_array(df_port)
    Q_p, R_p, N_p, B_p, P_p = build_markov_matrices(C_p)
    f.write(f"**Portfolio Counts:**\nCurrent: {C_p[0].sum():.0f}, 30_DPD: {C_p[1].sum():.0f}, 60_DPD: {C_p[2].sum():.0f}\n\n")

    for band in ['High-FICO', 'Mid-FICO', 'Lower-FICO']:
        df_b = con.execute(f"SELECT state_t, state_t_plus_1, n FROM v_transition_matrix_fico WHERE fico_band = '{band}'").df()
        C_b = counts_df_to_array(df_b)
        Q_b, R_b, N_b, B_b, P_b = build_markov_matrices(C_b, C_p)
        pd_12m = compute_12month_pd(Q_b, R_b)
        f.write(f"**{band}** (Counts - Cur: {C_b[0].sum():.0f}, 30: {C_b[1].sum():.0f}, 60: {C_b[2].sum():.0f})\n")
        f.write(f"- 12m PD (Current): {pd_12m:.4f}\n")
        f.write(f"- Lifetime PD (Current): {B_b[0, 1]:.4f}\n")
        f.write(f"- Lifetime PD (30 DPD): {B_b[1, 1]:.4f}\n")
        f.write(f"- Lifetime PD (60 DPD): {B_b[2, 1]:.4f}\n\n")

    # Vintage shape and snapshot reconciliation
    f.write("## 4. Vintage Curve Shape & Snapshot Reconciliation\n")
    snap_count_total = con.execute("SELECT COUNT(*) FROM ecl_snapshot").fetchone()[0]
    f.write(f"- Snapshot Loan Count at 201912: {snap_count_total}\n")
    vc_sample = con.execute("SELECT orig_year, loan_age, cumulative_default_rate_pct FROM v_vintage_curves WHERE loan_age IN (12, 24, 36, 48, 60)").df()
    f.write(f"- Vintage Curve Sample:\n{vc_sample.to_string()}\n\n")

    # ---------------------------------------------------------
    # 3. Backtest Breakdown
    # ---------------------------------------------------------
    f.write("## 5. Backtest Breakdown (2018 -> 2019)\n")
    snap_count = con.execute(f"SELECT COUNT(*) FROM oos_snapshot_201812").fetchone()[0]
    expected_defaults = snap_count * compute_12month_pd(Q_p, R_p)
    actual_defaults = con.execute(f"SELECT COUNT(DISTINCT s.loan_id) FROM oos_snapshot_201812 s INNER JOIN clean_monthly_performance p ON s.loan_id = p.loan_id WHERE p.monthly_reporting_period BETWEEN 201901 AND 201912 AND p.loan_state = 'Default'").fetchone()[0]
    
    z_score = (actual_defaults - expected_defaults) / np.sqrt(expected_defaults)
    f.write(f"- Overall Z-Score (Poisson): {z_score:.2f} std devs\n")
    
    # FICO bucketed
    expected_fico = 0
    f.write("- FICO Breakdown:\n")
    for band in ['High-FICO', 'Mid-FICO', 'Lower-FICO']:
        df_b = con.execute(f"SELECT state_t, state_t_plus_1, COUNT(*) AS n FROM loan_level_transitions WHERE monthly_reporting_period <= {BACKTEST_TRAIN_CUTOFF} AND fico_band = '{band}' GROUP BY 1,2").df()
        C_b = counts_df_to_array(df_b)
        if C_b[0].sum() > 0:
            Q_b, R_b, _, _, _ = build_markov_matrices(C_b, C_p)
            pd_b = compute_12month_pd(Q_b, R_b)
            fico_case = "CASE WHEN TRY_CAST(o.credit_score AS INT) BETWEEN 740 AND 850 THEN 'High-FICO' WHEN TRY_CAST(o.credit_score AS INT) BETWEEN 680 AND 739 THEN 'Mid-FICO' WHEN TRY_CAST(o.credit_score AS INT) BETWEEN 300 AND 679 THEN 'Lower-FICO' ELSE 'Unknown' END"
            sc = con.execute(f"SELECT COUNT(*) FROM oos_snapshot_201812 s INNER JOIN raw_origination o ON s.loan_id = o.loan_id WHERE {fico_case} = '{band}'").fetchone()[0]
            act = con.execute(f"SELECT COUNT(DISTINCT s.loan_id) FROM oos_snapshot_201812 s INNER JOIN raw_origination o ON s.loan_id = o.loan_id INNER JOIN clean_monthly_performance p ON s.loan_id = p.loan_id WHERE p.monthly_reporting_period BETWEEN 201901 AND 201912 AND p.loan_state = 'Default' AND {fico_case} = '{band}'").fetchone()[0]
            f.write(f"  * {band}: Expected={sc*pd_b:.1f}, Actual={act}\n")
            expected_fico += sc*pd_b
    f.write(f"  * Total Expected (FICO-Bucketed): {expected_fico:.1f} vs Actual: {actual_defaults}\n")

    # Age bucketed
    con.execute(f"""
    CREATE OR REPLACE VIEW v_oos_transitions_age AS
    SELECT CASE WHEN loan_age <= 24 THEN '<=24' WHEN loan_age <= 48 THEN '25-48' ELSE '>48' END as age_bucket,
        state_t, state_t_plus_1, COUNT(*) AS n
    FROM loan_level_transitions
    WHERE monthly_reporting_period <= {BACKTEST_TRAIN_CUTOFF} GROUP BY 1, 2, 3;
    """)
    con.execute(f"""
    CREATE OR REPLACE TABLE oos_snapshot_age AS
    SELECT s.loan_id, CASE WHEN p.loan_age <= 24 THEN '<=24' WHEN p.loan_age <= 48 THEN '25-48' ELSE '>48' END as age_bucket
    FROM oos_snapshot_201812 s
    INNER JOIN clean_monthly_performance p ON s.loan_id = p.loan_id
    WHERE p.monthly_reporting_period = {BACKTEST_SNAPSHOT};
    """)
    expected_age = 0
    f.write("- Age Breakdown:\n")
    for ab in ['<=24', '25-48', '>48']:
        df_ab = con.execute(f"SELECT state_t, state_t_plus_1, n FROM v_oos_transitions_age WHERE age_bucket = '{ab}'").df()
        C_ab = counts_df_to_array(df_ab)
        if C_ab[0].sum() > 100:
            Q_ab, R_ab, _, _, _ = build_markov_matrices(C_ab, C_p)
            pd_ab = compute_12month_pd(Q_ab, R_ab)
            sc = con.execute(f"SELECT COUNT(*) FROM oos_snapshot_age WHERE age_bucket = '{ab}'").fetchone()[0]
            act = con.execute(f"SELECT COUNT(DISTINCT s.loan_id) FROM oos_snapshot_age s INNER JOIN clean_monthly_performance p ON s.loan_id = p.loan_id WHERE p.monthly_reporting_period BETWEEN 201901 AND 201912 AND p.loan_state = 'Default' AND s.age_bucket = '{ab}'").fetchone()[0]
            f.write(f"  * Age Bucket {ab}: Expected={sc*pd_ab:.1f}, Actual={act}\n")
            expected_age += sc*pd_ab
    f.write(f"  * Total Expected (Age-Bucketed): {expected_age:.1f} vs Actual: {actual_defaults}\n")
    z_score_age = (actual_defaults - expected_age) / np.sqrt(expected_age)
    f.write(f"  * Age-Bucketed Z-Score (Poisson): {z_score_age:.2f} std devs\n\n")

    # ---------------------------------------------------------
    # 6. Bias Sensitivities
    # ---------------------------------------------------------
    f.write("## 6. Bias Sensitivities\n")
    
    # 1. Censor instead of purge
    con.execute(f"""
    CREATE OR REPLACE TABLE clean_monthly_performance_censored AS
    WITH mod_dates AS (
        SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as mod_date
        FROM raw_performance 
        WHERE COALESCE(modification_flag, '') IN ('Y', 'P')
        GROUP BY loan_id
    )
    SELECT p.*
    FROM raw_performance p
    LEFT JOIN mod_dates m ON p.loan_id = m.loan_id
    WHERE CAST(p.monthly_reporting_period AS INT) <= {PRE_COVID_CUTOFF}
      AND (m.mod_date IS NULL OR CAST(p.monthly_reporting_period AS INT) <= m.mod_date);
    """)
    cnt_cens = con.execute("SELECT COUNT(DISTINCT loan_id) FROM clean_monthly_performance_censored").fetchone()[0]
    f.write(f"- Censoring Modifications vs Purging: Retained {cnt_cens:,} unique loans up to modification date (vs ~{total_loans - purged_loans:,} purged).\n")
    
    # 2. Treat 15/16 as default
    con.execute(f"""
    CREATE OR REPLACE VIEW v_default_outcomes_24m_sens AS
    WITH window_rows AS (
        SELECT p.loan_id, p.loan_state, p.zero_balance_code, p.monthly_reporting_period, f.first_default_period
        FROM clean_monthly_performance p INNER JOIN v_first_default f ON p.loan_id = f.loan_id
        WHERE f.first_default_period <= {LGD_24M_COHORT_CUTOFF} AND p.monthly_reporting_period >= f.first_default_period
          AND month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) <= 24
    ),
    last_row_per_loan AS (
        SELECT * FROM window_rows QUALIFY ROW_NUMBER() OVER (PARTITION BY loan_id ORDER BY monthly_reporting_period DESC) = 1
    )
    SELECT CASE WHEN zero_balance_code IN ('02','03','09','15','16') THEN 'Liquidated_or_Sale' ELSE 'Other' END as outcome, COUNT(*) as cnt
    FROM last_row_per_loan GROUP BY 1;
    """)
    res = con.execute("SELECT * FROM v_default_outcomes_24m_sens").fetchall()
    f.write(f"- LGD Outcomes treating 15/16 as Liquidated: {res}\n")

    # 3. Cured in snapshot
    cnt_all = con.execute("SELECT COUNT(*) FROM ecl_snapshot").fetchone()[0]
    cnt_cured = con.execute("""
        SELECT COUNT(DISTINCT s.loan_id) 
        FROM ecl_snapshot s
        INNER JOIN clean_monthly_performance p ON s.loan_id = p.loan_id
        WHERE p.monthly_reporting_period < 201912 AND p.loan_state = 'Default'
    """).fetchone()[0]
    f.write(f"- Snapshot loans that previously defaulted (Cured): {cnt_cured} / {cnt_all}\n")
    
    # 4. P(liq) Dollar weighted
    con.execute(f"""
    CREATE OR REPLACE VIEW v_last_row_24 AS
    WITH window_rows AS (
        SELECT p.loan_id, p.loan_state, p.zero_balance_code, p.monthly_reporting_period, f.first_default_period, p.current_actual_upb
        FROM clean_monthly_performance p INNER JOIN v_first_default f ON p.loan_id = f.loan_id
        WHERE f.first_default_period <= {LGD_24M_COHORT_CUTOFF} AND p.monthly_reporting_period >= f.first_default_period AND month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) <= 24
    )
    SELECT * FROM window_rows QUALIFY ROW_NUMBER() OVER (PARTITION BY loan_id ORDER BY monthly_reporting_period DESC) = 1;
    """)
    liq_dol = con.execute("""
        SELECT 
            SUM(CASE WHEN zero_balance_code IN ('02','03','09') OR loan_state = 'Default' THEN 1 ELSE 0 END) as count_upper,
            SUM(1) as total_count,
            SUM(CASE WHEN zero_balance_code IN ('02','03','09') OR loan_state = 'Default' THEN COALESCE(current_actual_upb, 0) ELSE 0 END) as dol_upper,
            SUM(COALESCE(current_actual_upb, 0)) as total_dol
        FROM v_last_row_24 WHERE zero_balance_code NOT IN ('06','15','16','96') OR zero_balance_code IS NULL
    """).fetchone()
    f.write(f"- P(liq) Upper Bound (Count-weighted): {liq_dol[0]/liq_dol[1]:.4f} (N={liq_dol[1]})\n")
    if liq_dol[3] > 0:
        f.write(f"- P(liq) Upper Bound (Dollar-weighted): {liq_dol[2]/liq_dol[3]:.4f} (Dol={liq_dol[3]:,.0f})\n")

print("Validation script completed successfully.")
