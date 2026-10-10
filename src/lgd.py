"""
Phase 1: LGD Cohort Statistics (Fixed 24-Month and 36-Month Follow-Up)
Implements Two-Factor Bounded LGD Composite:
LGD = P(Liquidation | 90+) * Empirical Loss Severity
"""
import duckdb
import pandas as pd
from src.config import LGD_24M_COHORT_CUTOFF, LGD_36M_COHORT_CUTOFF

def build_lgd_views(con: duckdb.DuckDBPyConnection):
    """
    Creates views for identifying first default, 24m/36m outcome distribution,
    and liquidation loss severity.
    """
    print("[LGD] Creating LGD cohort views...")
    con.execute(f"""
    CREATE OR REPLACE VIEW v_first_default AS
    SELECT
        loan_id,
        MIN(monthly_reporting_period) AS first_default_period
    FROM clean_monthly_performance
    WHERE loan_state = 'Default'
    GROUP BY loan_id;

    -- UPB at first default for dollar-weighting
    CREATE OR REPLACE VIEW v_first_default_upb AS
    SELECT 
        f.loan_id, 
        f.first_default_period, 
        p.current_actual_upb as default_upb
    FROM v_first_default f
    INNER JOIN clean_monthly_performance p 
    ON f.loan_id = p.loan_id AND f.first_default_period = p.monthly_reporting_period;

    -- 24-Month Outcome Tracking (Cohort <= 201712)
    CREATE OR REPLACE VIEW v_default_outcomes_24m AS
    WITH window_rows AS (
        SELECT
            p.loan_id,
            p.loan_state,
            p.zero_balance_code,
            p.monthly_reporting_period,
            f.first_default_period,
            month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) AS months_since_default
        FROM clean_monthly_performance p
        INNER JOIN v_first_default f ON p.loan_id = f.loan_id
        WHERE f.first_default_period <= {LGD_24M_COHORT_CUTOFF}
          AND p.monthly_reporting_period >= f.first_default_period
          AND month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) <= 24
    ),
    last_row_per_loan AS (
        SELECT *
        FROM window_rows
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY loan_id ORDER BY monthly_reporting_period DESC
        ) = 1
    )
    SELECT
        loan_id,
        first_default_period,
        months_since_default,
        CASE
            WHEN zero_balance_code IN ('02','03','09') THEN 'Liquidated'
            WHEN zero_balance_code = '01' THEN 'Paid_Off'
            WHEN zero_balance_code IN ('06','15','16','96') THEN 'Admin_Removed'
            WHEN loan_state = 'Default' THEN 'Still_In_Default'
            WHEN loan_state IN ('Current','30_DPD','60_DPD') THEN 'Cured_Active'
            ELSE 'Other'
        END AS outcome
    FROM last_row_per_loan;

    -- 36-Month Outcome Tracking (Cohort <= 201612)
    CREATE OR REPLACE VIEW v_default_outcomes_36m AS
    WITH window_rows AS (
        SELECT
            p.loan_id,
            p.loan_state,
            p.zero_balance_code,
            p.monthly_reporting_period,
            f.first_default_period,
            month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) AS months_since_default
        FROM clean_monthly_performance p
        INNER JOIN v_first_default f ON p.loan_id = f.loan_id
        WHERE f.first_default_period <= {LGD_36M_COHORT_CUTOFF}
          AND p.monthly_reporting_period >= f.first_default_period
          AND month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) <= 36
    ),
    last_row_per_loan AS (
        SELECT *
        FROM window_rows
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY loan_id ORDER BY monthly_reporting_period DESC
        ) = 1
    )
    SELECT
        loan_id,
        first_default_period,
        months_since_default,
        CASE
            WHEN zero_balance_code IN ('02','03','09') THEN 'Liquidated'
            WHEN zero_balance_code = '01' THEN 'Paid_Off'
            WHEN zero_balance_code IN ('06','15','16','96') THEN 'Admin_Removed'
            WHEN loan_state = 'Default' THEN 'Still_In_Default'
            WHEN loan_state IN ('Current','30_DPD','60_DPD') THEN 'Cured_Active'
            ELSE 'Other'
        END AS outcome
    FROM last_row_per_loan;

    -- 24-Month Loss Severity Given Liquidation
    CREATE OR REPLACE VIEW v_lgd_severity_24m AS
    WITH total_mod_cost AS (
        SELECT p.loan_id, SUM(p.modification_cost) as total_mod_cost
        FROM clean_monthly_performance p
        INNER JOIN v_first_default f ON p.loan_id = f.loan_id
        WHERE month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) <= 24
        GROUP BY p.loan_id
    )
    SELECT
        COUNT(*) AS total_liquidated_loans,
        SUM(p.zero_balance_removal_upb) AS total_disposition_upb,
        SUM(p.actual_loss_calculation + COALESCE(m.total_mod_cost, 0)) AS total_net_loss,
        ROUND(SUM(p.actual_loss_calculation + COALESCE(m.total_mod_cost, 0)) / NULLIF(SUM(p.zero_balance_removal_upb), 0), 4) AS empirical_loss_severity
    FROM clean_monthly_performance p
    INNER JOIN v_first_default f ON p.loan_id = f.loan_id
    LEFT JOIN total_mod_cost m ON p.loan_id = m.loan_id
    WHERE f.first_default_period <= {LGD_24M_COHORT_CUTOFF}
      AND month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) <= 24
      AND p.zero_balance_code IN ('02','03','09')
      AND p.actual_loss_calculation IS NOT NULL
      AND p.zero_balance_removal_upb > 0;
      
    -- 36-Month Loss Severity Given Liquidation
    CREATE OR REPLACE VIEW v_lgd_severity_36m AS
    WITH total_mod_cost AS (
        SELECT p.loan_id, SUM(p.modification_cost) as total_mod_cost
        FROM clean_monthly_performance p
        INNER JOIN v_first_default f ON p.loan_id = f.loan_id
        WHERE month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) <= 36
        GROUP BY p.loan_id
    )
    SELECT
        COUNT(*) AS total_liquidated_loans,
        SUM(p.zero_balance_removal_upb) AS total_disposition_upb,
        SUM(p.actual_loss_calculation + COALESCE(m.total_mod_cost, 0)) AS total_net_loss,
        ROUND(SUM(p.actual_loss_calculation + COALESCE(m.total_mod_cost, 0)) / NULLIF(SUM(p.zero_balance_removal_upb), 0), 4) AS empirical_loss_severity
    FROM clean_monthly_performance p
    INNER JOIN v_first_default f ON p.loan_id = f.loan_id
    LEFT JOIN total_mod_cost m ON p.loan_id = m.loan_id
    WHERE f.first_default_period <= {LGD_36M_COHORT_CUTOFF}
      AND month_idx(p.monthly_reporting_period) - month_idx(f.first_default_period) <= 36
      AND p.zero_balance_code IN ('02','03','09')
      AND p.actual_loss_calculation IS NOT NULL
      AND p.zero_balance_removal_upb > 0;
    """)

def compute_lgd_bounds(con: duckdb.DuckDBPyConnection):
    """
    Computes dollar-weighted bounded LGD sensitivity range for both 24m and 36m cohorts.
    Uses 36m bounds as the headline parameters for ECL, showing 24m as sensitivity.
    """
    import math
    def get_horizon_stats(horizon: str):
        stats = con.execute(f"""
            SELECT 
                o.outcome,
                COUNT(*) as count,
                SUM(u.default_upb) as dol
            FROM v_default_outcomes_{horizon} o
            INNER JOIN v_first_default_upb u ON o.loan_id = u.loan_id
            GROUP BY o.outcome
        """).df()
        print(f"\n--- {horizon} Outcome Buckets ---")
        print(stats.to_string(index=False))
        
        dol_liquidated = stats.loc[stats['outcome'] == 'Liquidated', 'dol'].sum() if 'Liquidated' in stats['outcome'].values else 0
        dol_still_in_default = stats.loc[stats['outcome'] == 'Still_In_Default', 'dol'].sum() if 'Still_In_Default' in stats['outcome'].values else 0
        
        # Original logic: Admin_Removed is excluded from denominator.
        dol_total = stats.loc[stats['outcome'] != 'Admin_Removed', 'dol'].sum()
        count_total = stats.loc[stats['outcome'] != 'Admin_Removed', 'count'].sum()
        
        severity_df = con.execute(f"SELECT * FROM v_lgd_severity_{horizon}").df()
        severity = severity_df['empirical_loss_severity'].values[0] if len(severity_df) > 0 and severity_df['empirical_loss_severity'].values[0] is not None else 0.25
        total_net_loss = severity_df['total_net_loss'].values[0] if len(severity_df) > 0 else 0
        total_liquidated_loans = severity_df['total_liquidated_loans'].values[0] if len(severity_df) > 0 else 0
        
        if dol_total == 0:
            return 0.15, 0.45, 0.30, severity, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
            
        p_liq_lower = dol_liquidated / dol_total
        p_liq_upper = (dol_liquidated + dol_still_in_default) / dol_total
        
        p_liq_excl_mod_lower = p_liq_lower
        p_liq_excl_mod_upper = p_liq_upper
        
        # Binomial CIs
        def calc_ci(p, n):
            if n == 0: return 0.0
            return 1.96 * math.sqrt((p * (1 - p)) / n)
            
        ci_liq_lower = calc_ci(p_liq_lower, count_total)
        ci_liq_upper = calc_ci(p_liq_upper, count_total)
        ci_sev = calc_ci(severity, total_liquidated_loans)
        
        direct_crosscheck = total_net_loss / dol_total
        
        lgd_lower = p_liq_lower * severity
        lgd_upper = p_liq_upper * severity
        lgd_midpoint = (lgd_lower + lgd_upper) / 2.0
        
        return lgd_lower, lgd_upper, lgd_midpoint, p_liq_lower, p_liq_upper, severity, ci_liq_lower, ci_liq_upper, ci_sev, direct_crosscheck, p_liq_excl_mod_lower, p_liq_excl_mod_upper

    lgd_lower_24, lgd_upper_24, lgd_midpoint_24, p_liq_lower_24, p_liq_upper_24, sev_24, ci_l_24, ci_u_24, ci_s_24, direct_24, p24_ex_l, p24_ex_u = get_horizon_stats("24m")
    lgd_lower_36, lgd_upper_36, lgd_midpoint_36, p_liq_lower_36, p_liq_upper_36, sev_36, ci_l_36, ci_u_36, ci_s_36, direct_36, p36_ex_l, p36_ex_u = get_horizon_stats("36m")
    
    print("\n--- [LGD Cohort Analysis: Dollar-Weighted] ---")
    print(f"24-Month Follow-Up (Sensitivity):")
    print(f"  P(Liquidation | 90+): Lower = {p_liq_lower_24:.4f} (±{ci_l_24:.4f}), Upper = {p_liq_upper_24:.4f} (±{ci_u_24:.4f})")
    print(f"  P(Liquidation) Excl Mod: Lower = {p24_ex_l:.4f}, Upper = {p24_ex_u:.4f}")
    print(f"  Empirical Loss Severity: {sev_24:.4f} (±{ci_s_24:.4f})")
    print(f"  LGD Range: [{lgd_lower_24:.4f}, {lgd_upper_24:.4f}] | Midpoint: {lgd_midpoint_24:.4f}")
    print(f"\n36-Month Follow-Up (Headline, benign 2014-2016 vintage):")
    print(f"  P(Liquidation | 90+): Lower = {p_liq_lower_36:.4f} (±{ci_l_36:.4f}), Upper = {p_liq_upper_36:.4f} (±{ci_u_36:.4f})")
    print(f"  P(Liquidation) Excl Mod: Lower = {p36_ex_l:.4f}, Upper = {p36_ex_u:.4f}")
    print(f"  Empirical Loss Severity: {sev_36:.4f} (±{ci_s_36:.4f})")
    print(f"  LGD Range: [{lgd_lower_36:.4f}, {lgd_upper_36:.4f}] | Midpoint: {lgd_midpoint_36:.4f}")
    print(f"  Direct Cross-check (Net Loss / Total UPB): {direct_36:.4f}")
    
    # Return 36m as the headline LGD bounds
    return lgd_lower_36, lgd_upper_36, lgd_midpoint_36
