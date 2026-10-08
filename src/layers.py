"""
Layers 1 to 3: Clean Panel Construction, Truncation, Transitions, Vintages & ECL Snapshot
"""
import duckdb
from src.config import PRE_COVID_CUTOFF, ECL_SNAPSHOT_PERIOD

def build_layer1_clean_performance(con: duckdb.DuckDBPyConnection):
    """
    Layer 1: clean_monthly_performance (Untruncated Base Layer)
    - Maps delinquency and zero-balance codes to Basel/RBI 90-day states.
    - Applies hard pre-COVID cutoff (<= 202002).
    - Excludes modified loans ('Y') to establish contractual baseline risk.
    """
    print("[Layer 1] Building clean_monthly_performance...")
    con.execute(f"""
    CREATE OR REPLACE TABLE clean_monthly_performance AS
    WITH Mod_Dates AS (
        SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as mod_period
        FROM raw_performance
        WHERE COALESCE(modification_flag, '') IN ('Y', 'P')
        GROUP BY loan_id
    )
    SELECT
        r.loan_id,
        CAST(r.monthly_reporting_period AS INT) AS monthly_reporting_period,
        TRY_CAST(r.loan_age AS INT) AS loan_age,
        COALESCE(TRY_CAST(r.zero_balance_removal_upb AS DOUBLE), 0) AS zero_balance_removal_upb,
        COALESCE(TRY_CAST(r.current_actual_upb AS DOUBLE), 0) AS current_actual_upb,
        TRY_CAST(r.actual_loss_calculation AS DOUBLE) AS actual_loss_calculation,
        r.zero_balance_code,
        r.current_delinquency_status,
        r.modification_flag,
        CASE
            WHEN r.zero_balance_code IN ('02','03','09')
                 OR r.current_delinquency_status = 'RA' THEN 'Default'
            WHEN TRY_CAST(r.current_delinquency_status AS INT) >= 3 THEN 'Default'
            WHEN r.zero_balance_code = '01' THEN 'Paid_Off'
            WHEN r.zero_balance_code IN ('06','15','16','96') THEN 'Admin_Removal'
            WHEN TRY_CAST(r.current_delinquency_status AS INT) = 2 THEN '60_DPD'
            WHEN TRY_CAST(r.current_delinquency_status AS INT) = 1 THEN '30_DPD'
            WHEN TRY_CAST(r.current_delinquency_status AS INT) = 0 THEN 'Current'
            ELSE 'Uncertain_Quarantine'
        END AS loan_state
    FROM raw_performance r
    LEFT JOIN Mod_Dates m ON r.loan_id = m.loan_id
    WHERE CAST(r.monthly_reporting_period AS INT) <= {PRE_COVID_CUTOFF}
      AND (m.mod_period IS NULL OR CAST(r.monthly_reporting_period AS INT) <= m.mod_period);
    """)
    cnt = con.execute("SELECT COUNT(*) FROM clean_monthly_performance").fetchone()[0]
    print(f"[Layer 1] clean_monthly_performance created: {cnt:,} rows.")

def build_layer2_truncated_performance(con: duckdb.DuckDBPyConnection):
    """
    Layer 2: truncated_performance (First-Default Truncated)
    - Truncates history after the first default (inclusive) to enforce absorbing Markov properties.
    - Excludes Admin_Removal and Uncertain_Quarantine.
    """
    print("[Layer 2] Building truncated_performance...")
    con.execute("""
    CREATE OR REPLACE TABLE truncated_performance AS
    WITH first_default AS (
        SELECT loan_id, MIN(monthly_reporting_period) AS first_default_period
        FROM clean_monthly_performance
        WHERE loan_state = 'Default'
        GROUP BY loan_id
    )
    SELECT c.*
    FROM clean_monthly_performance c
    LEFT JOIN first_default f USING (loan_id)
    WHERE c.monthly_reporting_period <= COALESCE(f.first_default_period, 999999)
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
    """
    print("[Vintages] Building vintage curve views...")
    con.execute(f"""
    CREATE OR REPLACE VIEW v_vintage_loan_counts AS
    SELECT
        2000 + CAST(SUBSTRING(loan_id, 2, 2) AS INT) AS orig_year,
        COUNT(*) AS loans_originated
    FROM raw_origination
    WHERE loan_id NOT IN (
        SELECT loan_id FROM raw_performance 
        WHERE CAST(monthly_reporting_period AS INT) <= {PRE_COVID_CUTOFF}
          AND COALESCE(modification_flag, '') IN ('Y', 'P')
    )
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

    CREATE OR REPLACE VIEW v_vintage_curves AS
    SELECT
        d.orig_year,
        d.loan_age,
        d.new_defaults_at_age,
        SUM(d.new_defaults_at_age) OVER (
            PARTITION BY d.orig_year ORDER BY d.loan_age
        ) AS cumulative_defaults,
        c.loans_originated,
        ROUND(SUM(d.new_defaults_at_age) OVER (
            PARTITION BY d.orig_year ORDER BY d.loan_age
        ) * 100.0 / c.loans_originated, 4) AS cumulative_default_rate_pct
    FROM v_defaults_by_age d
    INNER JOIN v_vintage_loan_counts c USING (orig_year);
    """)
    print("[Vintages] v_vintage_curves view created successfully.")

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
