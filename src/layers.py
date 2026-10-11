"""
Layers 1 to 3: Clean Panel Construction, Truncation, Transitions, Vintages & ECL Snapshot
"""
import duckdb
from src.config import PRE_COVID_CUTOFF, ECL_SNAPSHOT_PERIOD

def build_layer1_clean_performance(con: duckdb.DuckDBPyConnection, as_of_date: int = PRE_COVID_CUTOFF):
    """
    Layer 1: clean_monthly_performance
    - Maps delinquency and zero-balance codes to Basel/RBI 90-day states.
    - Captures 'Modified' as an explicit state.
    """
    print(f"[Layer 1] Building clean_monthly_performance (As of {as_of_date})...")
    
    con.execute(f"""
    CREATE OR REPLACE TABLE clean_monthly_performance AS
    WITH Mod_Dates AS (
        SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as mod_period
        FROM raw_performance
        WHERE COALESCE(modification_flag, '') IN ('Y', 'P')
          AND CAST(monthly_reporting_period AS INT) <= {as_of_date}
        GROUP BY loan_id
    )
    SELECT
        r.loan_id,
        CAST(r.monthly_reporting_period AS INT) AS monthly_reporting_period,
        TRY_CAST(r.loan_age AS INT) AS loan_age,
        COALESCE(TRY_CAST(r.zero_balance_removal_upb AS DOUBLE), 0) AS zero_balance_removal_upb,
        COALESCE(TRY_CAST(r.current_actual_upb AS DOUBLE), 0) AS current_actual_upb,
        TRY_CAST(r.actual_loss_calculation AS DOUBLE) AS actual_loss_calculation,
        COALESCE(TRY_CAST(r.modification_cost AS DOUBLE), 0) AS modification_cost,
        r.zero_balance_code,
        r.current_delinquency_status,
        r.modification_flag,
        m.mod_period as first_mod_period,
        CASE
            WHEN r.zero_balance_code IN ('02','03','09')
                 OR r.current_delinquency_status = 'RA' THEN 'Default'
            WHEN TRY_CAST(r.current_delinquency_status AS INT) >= 3 THEN 'Default'
            WHEN r.zero_balance_code = '01' THEN 'Paid_Off'
            WHEN r.zero_balance_code IN ('06','15','16','96') THEN 'Admin_Removal'
            WHEN COALESCE(r.modification_flag, '') IN ('Y', 'P') THEN 'Modified'
            WHEN TRY_CAST(r.current_delinquency_status AS INT) = 2 THEN '60_DPD'
            WHEN TRY_CAST(r.current_delinquency_status AS INT) = 1 THEN '30_DPD'
            WHEN TRY_CAST(r.current_delinquency_status AS INT) = 0 THEN 'Current'
            ELSE 'Uncertain_Quarantine'
        END AS loan_state
    FROM raw_performance r
    LEFT JOIN Mod_Dates m ON r.loan_id = m.loan_id
    WHERE CAST(r.monthly_reporting_period AS INT) <= {as_of_date};
    """)
    cnt = con.execute("SELECT COUNT(*) FROM clean_monthly_performance").fetchone()[0]
    print(f"[Layer 1] clean_monthly_performance created: {cnt:,} rows.")

def build_layer2_truncated_performance(con: duckdb.DuckDBPyConnection):
    """
    Layer 2: truncated_performance (First-Default/Mod Truncated)
    - Truncates history after the first default OR first modification.
    """
    print(f"[Layer 2] Building truncated_performance...")
    
    con.execute(f"""
    CREATE OR REPLACE TABLE truncated_performance AS
    WITH terminal_events AS (
        SELECT loan_id, MIN(monthly_reporting_period) AS terminal_period
        FROM clean_monthly_performance
        WHERE loan_state IN ('Default', 'Modified')
        GROUP BY loan_id
    )
    SELECT c.*
    FROM clean_monthly_performance c
    LEFT JOIN terminal_events f USING (loan_id)
    WHERE c.monthly_reporting_period <= COALESCE(f.terminal_period, 999999)
      AND c.loan_state NOT IN ('Uncertain_Quarantine', 'Admin_Removal');
    """)
    cnt = con.execute("SELECT COUNT(*) FROM truncated_performance").fetchone()[0]
    print(f"[Layer 2] truncated_performance created: {cnt:,} rows.")

def build_layer3_transitions(con: duckdb.DuckDBPyConnection):
    """
    Layer 3: loan_level_transitions (Markov Inputs & FICO Enriched)
    - Computes LEAD state using integer division month_idx continuity.
    - Enriches with origination vintage year and FICO bands.
    - Guards against sentinel values (9999, 999).
    """
    print("[Layer 3] Building loan_level_transitions...")
    con.execute("""
    CREATE OR REPLACE TABLE loan_level_transitions AS
    WITH State_Sequencing AS (
        SELECT
            p.loan_id,
            p.monthly_reporting_period,
            p.current_actual_upb,
            p.loan_age,
            p.modification_flag,
            p.loan_state AS state_t,
            LEAD(p.loan_state) OVER (
                PARTITION BY p.loan_id ORDER BY p.monthly_reporting_period
            ) AS raw_next_state,
            LEAD(p.monthly_reporting_period) OVER (
                PARTITION BY p.loan_id ORDER BY p.monthly_reporting_period
            ) AS next_period
        FROM truncated_performance p
    ),
    Continuity_Validated AS (
        SELECT
            *,
            CASE
                WHEN month_idx(next_period) - month_idx(monthly_reporting_period) = 1
                THEN raw_next_state
                ELSE NULL
            END AS state_t_plus_1
        FROM State_Sequencing
    )
    SELECT
        t.loan_id,
        t.monthly_reporting_period,
        t.current_actual_upb,
        t.loan_age,
        t.modification_flag,
        t.state_t,
        t.state_t_plus_1,
        2000 + CAST(SUBSTRING(o.loan_id, 2, 2) AS INT) AS orig_year,
        CASE
            WHEN TRY_CAST(o.credit_score AS INT) BETWEEN 740 AND 850 THEN 'High-FICO'
            WHEN TRY_CAST(o.credit_score AS INT) BETWEEN 680 AND 739 THEN 'Mid-FICO'
            WHEN TRY_CAST(o.credit_score AS INT) BETWEEN 300 AND 679 THEN 'Lower-FICO'
            ELSE 'Unknown'
        END AS fico_band,
        CASE
            WHEN TRY_CAST(o.credit_score AS INT) = 9999 THEN NULL
            ELSE TRY_CAST(o.credit_score AS INT)
        END AS credit_score,
        CASE
            WHEN TRY_CAST(o.orig_ltv AS DOUBLE) = 999 THEN NULL
            ELSE TRY_CAST(o.orig_ltv AS DOUBLE)
        END AS orig_ltv,
        CASE
            WHEN TRY_CAST(o.orig_dti AS DOUBLE) = 999 THEN NULL
            ELSE TRY_CAST(o.orig_dti AS DOUBLE)
        END AS orig_dti,
        CASE
            WHEN TRY_CAST(o.orig_cltv AS DOUBLE) = 999 THEN NULL
            ELSE TRY_CAST(o.orig_cltv AS DOUBLE)
        END AS orig_cltv,
        TRY_CAST(o.orig_upb AS DOUBLE) AS orig_upb
    FROM Continuity_Validated t
    INNER JOIN raw_origination o ON t.loan_id = o.loan_id
    WHERE t.state_t_plus_1 IS NOT NULL
      AND t.state_t IN ('Current', '30_DPD', '60_DPD');
    """)
    cnt = con.execute("SELECT COUNT(*) FROM loan_level_transitions").fetchone()[0]
    print(f"[Layer 3] loan_level_transitions created: {cnt:,} rows.")

def build_vintage_curve_views(con: duckdb.DuckDBPyConnection):
    """
    Creates views for cohort densified vintage default curves.
    Rule: Cohorts defined at origination (350,000 loans); modification treated
    as censoring at its date, keeping modified-after-default loans (6,009 defaults).
    Denominators at age a are strictly restricted to loans observable at age a.
    """
    print("[Vintages] Building vintage curve views...")
    con.execute(f"""
    CREATE OR REPLACE VIEW v_vintage_loan_counts AS
    SELECT
        2000 + CAST(SUBSTRING(loan_id, 2, 2) AS INT) AS orig_year,
        COUNT(*) AS loans_originated
    FROM raw_origination o
    GROUP BY orig_year;

    CREATE OR REPLACE VIEW v_defaults_by_age AS
    WITH max_ages AS (
        SELECT
            2000 + CAST(SUBSTRING(o.loan_id, 2, 2) AS INT) AS orig_year,
            MAX(p.loan_age) AS max_age
        FROM truncated_performance p
        INNER JOIN raw_origination o ON p.loan_id = o.loan_id
        GROUP BY orig_year
    ),
    age_grid AS (
        SELECT m.orig_year, UNNEST(GENERATE_SERIES(0, m.max_age)) AS loan_age
        FROM max_ages m
    ),
    raw_defaults AS (
        SELECT
            2000 + CAST(SUBSTRING(o.loan_id, 2, 2) AS INT) AS orig_year,
            p.loan_age,
            COUNT(*) AS new_defaults_at_age
        FROM truncated_performance p
        INNER JOIN raw_origination o ON p.loan_id = o.loan_id
        WHERE p.loan_state = 'Default'
        GROUP BY orig_year, p.loan_age
    )
    SELECT
        g.orig_year,
        g.loan_age,
        COALESCE(r.new_defaults_at_age, 0) AS new_defaults_at_age
    FROM age_grid g
    LEFT JOIN raw_defaults r ON g.orig_year = r.orig_year AND g.loan_age = r.loan_age;

    CREATE OR REPLACE VIEW v_vintage_observable_counts AS
    WITH loan_max_obs AS (
        SELECT 
            loan_id,
            2000 + CAST(SUBSTRING(loan_id, 2, 2) AS INT) AS orig_year,
            month_idx({PRE_COVID_CUTOFF}) - month_idx(TRY_CAST(first_payment_date AS INT)) + 1 AS max_obs_age
        FROM raw_origination
    ),
    max_ages AS (
        SELECT
            2000 + CAST(SUBSTRING(o.loan_id, 2, 2) AS INT) AS orig_year,
            MAX(p.loan_age) AS max_age
        FROM truncated_performance p
        INNER JOIN raw_origination o ON p.loan_id = o.loan_id
        GROUP BY orig_year
    ),
    age_grid AS (
        SELECT m.orig_year, UNNEST(GENERATE_SERIES(0, m.max_age)) AS loan_age
        FROM max_ages m
    )
    SELECT
        g.orig_year,
        g.loan_age,
        COUNT(l.loan_id) AS observable_loans
    FROM age_grid g
    LEFT JOIN loan_max_obs l 
      ON g.orig_year = l.orig_year AND l.max_obs_age >= g.loan_age
    GROUP BY g.orig_year, g.loan_age;

    CREATE OR REPLACE VIEW v_vintage_curves AS
    WITH base_hazard AS (
        SELECT
            d.orig_year,
            d.loan_age,
            d.new_defaults_at_age,
            o.observable_loans,
            SUM(d.new_defaults_at_age) OVER (
                PARTITION BY d.orig_year ORDER BY d.loan_age
            ) AS cumulative_defaults,
            c.loans_originated,
            CASE 
                WHEN o.observable_loans > 0 
                THEN d.new_defaults_at_age * 1.0 / o.observable_loans 
                ELSE 0.0 
            END AS monthly_hazard,
            CASE
                WHEN c.loans_originated > 0
                THEN d.new_defaults_at_age * 1.0 / c.loans_originated
                ELSE 0.0
            END AS per_original_loan_inc
        FROM v_defaults_by_age d
        INNER JOIN v_vintage_loan_counts c USING (orig_year)
        INNER JOIN v_vintage_observable_counts o USING (orig_year, loan_age)
    )
    SELECT
        orig_year,
        loan_age,
        new_defaults_at_age,
        observable_loans,
        cumulative_defaults,
        loans_originated,
        ROUND(per_original_loan_inc * 100.0, 4) AS per_original_loan_incidence_pct,
        ROUND(monthly_hazard * 100.0, 4) AS monthly_hazard_pct,
        ROUND((1.0 - EXP(SUM(LN(GREATEST(1.0 - monthly_hazard, 0.000001))) OVER (
            PARTITION BY orig_year ORDER BY loan_age
        ))) * 100.0, 4) AS cumulative_incidence_per_observable_pct,
        ROUND((1.0 - EXP(SUM(LN(GREATEST(1.0 - monthly_hazard, 0.000001))) OVER (
            PARTITION BY orig_year ORDER BY loan_age
        ))) * 100.0, 4) AS cumulative_default_rate_pct
    FROM base_hazard;
    """)
    print("[Vintages] v_vintage_curves view created successfully with relabeled observable columns.")

def build_ecl_snapshot(con: duckdb.DuckDBPyConnection, snapshot_period: int = ECL_SNAPSHOT_PERIOD):
    """
    Extracts the ECL portfolio snapshot from the untruncated clean layer at a fixed month (201912).
    Restricted to open active loans (zero_balance_code IS NULL).
    """
    print(f"[Snapshot] Building ecl_snapshot at period {snapshot_period}...")
    con.execute(f"""
    CREATE OR REPLACE TABLE ecl_snapshot AS
    SELECT
        p.loan_id,
        p.loan_state,
        p.modification_flag,
        COALESCE(
            NULLIF(p.current_actual_upb, 0),
            p.zero_balance_removal_upb
        ) AS snapshot_upb,
        CASE
            WHEN TRY_CAST(o.credit_score AS INT) BETWEEN 740 AND 850 THEN 'High-FICO'
            WHEN TRY_CAST(o.credit_score AS INT) BETWEEN 680 AND 739 THEN 'Mid-FICO'
            WHEN TRY_CAST(o.credit_score AS INT) BETWEEN 300 AND 679 THEN 'Lower-FICO'
            ELSE 'Unknown'
        END AS fico_band,
        CASE
            WHEN TRY_CAST(o.orig_ltv AS DOUBLE) = 999 THEN NULL
            ELSE TRY_CAST(o.orig_ltv AS DOUBLE)
        END AS orig_ltv
    FROM clean_monthly_performance p
    INNER JOIN raw_origination o ON p.loan_id = o.loan_id
    WHERE p.monthly_reporting_period = {snapshot_period}
      AND p.zero_balance_code IS NULL
      AND p.loan_state NOT IN ('Admin_Removal', 'Uncertain_Quarantine');
    """)
    cnt = con.execute("SELECT COUNT(*) FROM ecl_snapshot").fetchone()[0]
    print(f"[Snapshot] ecl_snapshot created: {cnt:,} active loans.")
