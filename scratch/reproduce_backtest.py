import duckdb
import numpy as np
import pandas as pd

def run_reproduce_backtest():
    con = duckdb.connect("mortgage_risk.duckdb", read_only=True)

    print("=========================================================================================================================")
    print("                      1. POP 2 CURRENT HISTORICAL 12M DEFAULT RATES (2015-2017 SNAPSHOTS)                                ")
    print("=========================================================================================================================")
    
    # Measure Pop 2 Current 12m default rates across pre-2019 snapshots:
    q_pool = """
    WITH p2_all AS (
        SELECT DISTINCT loan_id, CAST(monthly_reporting_period AS INT) as rep_p
        FROM raw_performance 
        WHERE COALESCE(modification_flag, '') IN ('Y', 'P')
        UNION
        SELECT DISTINCT loan_id, monthly_reporting_period as rep_p
        FROM clean_monthly_performance
        WHERE loan_state IN ('Modified', 'Default')
    ),
    snaps AS (
        SELECT 201512 as snap, 201601 as e_start, 201612 as e_end, 2015 as yr
        UNION ALL SELECT 201612, 201701, 201712, 2016
        UNION ALL SELECT 201712, 201801, 201812, 2017
    ),
    cohort AS (
        SELECT s.yr, s.snap, s.e_start, s.e_end, c.loan_id
        FROM snaps s
        JOIN clean_monthly_performance c 
          ON c.monthly_reporting_period = s.snap AND c.loan_state = 'Current' AND c.zero_balance_code IS NULL
        WHERE EXISTS (
            SELECT 1 FROM p2_all p WHERE p.loan_id = c.loan_id AND p.rep_p <= s.snap
        )
    ),
    defs AS (
        SELECT c.yr, c.loan_id, MAX(CASE WHEN p.loan_state = 'Default' THEN 1 ELSE 0 END) as defaulted
        FROM cohort c
        LEFT JOIN clean_monthly_performance p 
          ON c.loan_id = p.loan_id AND p.monthly_reporting_period BETWEEN c.e_start AND c.e_end
        GROUP BY c.yr, c.loan_id
    )
    SELECT 
        yr,
        COUNT(*) as obs,
        SUM(defaulted) as defs,
        ROUND(SUM(defaulted) * 100.0 / COUNT(*), 4) as rate_pct
    FROM defs
    GROUP BY yr
    ORDER BY yr;
    """
    df_snaps = con.execute(q_pool).df()
    print("| Snapshot Year | Active Pop 2 Current Loans | 12m Realized Defaults | Measured 12m Default Rate % |")
    print("|---|---|---|---|")
    tot_obs = df_snaps['obs'].sum()
    tot_defs = df_snaps['defs'].sum()
    pool_rate = tot_defs / tot_obs
    for _, r in df_snaps.iterrows():
        print(f"| **{int(r['yr'])}12** | {int(r['obs']):>6,d} | {int(r['defs']):>4,d} | **{r['rate_pct']:.4f}%** |")
    print(f"| **Pooled 2015–2017** | **{int(tot_obs):>6,d}** | **{int(tot_defs):>4,d}** | **{pool_rate*100.0:.4f}%** |")
    print(f"\nNote: The pooled rate of {pool_rate:.4%} feeds the out-of-sample backtest, while 12.24% is kept as the lifetime ECL proxy.")

    print("\n=========================================================================================================================")
    print("                      2. OUT-OF-SAMPLE BACKTEST COMPARISON ACROSS SPECIFICATIONS A–D                                    ")
    print("=========================================================================================================================")

    # Segment specifications and rates:
    # Segment definitions: (Name, active_count, actual_defaults, pd)
    p_pool_curr = pool_rate           # 9.6397%
    p_trail_curr = df_snaps.loc[df_snaps['yr']==2017, 'defs'].values[0] / df_snaps.loc[df_snaps['yr']==2017, 'obs'].values[0] # 8.5106%

    specs = [
        ("SPECIFICATION A: True Frozen Model Parameters (Data <= 201812 Pool)", [
            ("Pop 1: Current", 191476, 340, 0.002180, "0.2180% (In-Sample)"),
            ("Pop 1: 30_DPD", 1255, 170, 0.120800, "12.0800% (Matrix 12m)"),
            ("Pop 1: 60_DPD", 220, 136, 0.590900, "59.0900% (Matrix 12m)"),
            ("Pop 2: Current", 636, 55, p_pool_curr, f"{p_pool_curr:.4%} (Pool 2015-17)"),
            ("Pop 2: 30_DPD", 115, 34, 0.531944, "53.1944% (Frozen Pool)"),
            ("Pop 2: 60_DPD", 87, 58, 0.793258, "79.3258% (Frozen Pool)"),
            ("Pop 2: Modified", 1136, 119, 0.120599, "12.0599% (Hazard 12m)"),
        ]),
        ("SPECIFICATION B: Trailing 1-Year Clean-History Baseline (201712 -> 2018: 0.1560%)", [
            ("Pop 1: Current", 191476, 340, 0.001560, "0.1560% (Trailing Clean)"),
            ("Pop 1: 30_DPD", 1255, 170, 0.120800, "12.0800% (Matrix 12m)"),
            ("Pop 1: 60_DPD", 220, 136, 0.590900, "59.0900% (Matrix 12m)"),
            ("Pop 2: Current", 636, 55, p_trail_curr, f"{p_trail_curr:.4%} (Trailing 2017)"),
            ("Pop 2: 30_DPD", 115, 34, 0.531944, "53.1944% (Frozen Pool)"),
            ("Pop 2: 60_DPD", 87, 58, 0.793258, "79.3258% (Frozen Pool)"),
            ("Pop 2: Modified", 1136, 119, 0.120599, "12.0599% (Hazard 12m)"),
        ]),
        ("SPECIFICATION C: Pre-2018 Clean-History Baseline (Data <= 201712 Snapshots Ex-Hurricane: 0.1800%)", [
            ("Pop 1: Current", 191476, 340, 0.001800, "0.1800% (Ex-Hurr Pool)"),
            ("Pop 1: 30_DPD", 1255, 170, 0.120800, "12.0800% (Matrix 12m)"),
            ("Pop 1: 60_DPD", 220, 136, 0.590900, "59.0900% (Matrix 12m)"),
            ("Pop 2: Current", 636, 55, p_pool_curr, f"{p_pool_curr:.4%} (Pool 2015-17)"),
            ("Pop 2: 30_DPD", 115, 34, 0.531944, "53.1944% (Frozen Pool)"),
            ("Pop 2: 60_DPD", 87, 58, 0.793258, "79.3258% (Frozen Pool)"),
            ("Pop 2: Modified", 1136, 119, 0.120599, "12.0599% (Hazard 12m)"),
        ]),
        ("SPECIFICATION D: Production Staged Structure (Clean @ 0.1560%, Probation @ 3.2236%)", [
            ("Pop 1: Current (Clean)", 187493, 218, 0.001560, "0.1560% (Trailing Clean)"),
            ("Pop 1: Current (Probation)", 3983, 122, 0.032236, "3.2236% (Trailing Delq)"),
            ("Pop 1: 30_DPD", 1255, 170, 0.120800, "12.0800% (Matrix 12m)"),
            ("Pop 1: 60_DPD", 220, 136, 0.590900, "59.0900% (Matrix 12m)"),
            ("Pop 2: Current", 636, 55, p_pool_curr, f"{p_pool_curr:.4%} (Pool 2015-17)"),
            ("Pop 2: 30_DPD", 115, 34, 0.531944, "53.1944% (Frozen Pool)"),
            ("Pop 2: 60_DPD", 87, 58, 0.793258, "79.3258% (Frozen Pool)"),
            ("Pop 2: Modified", 1136, 119, 0.120599, "12.0599% (Hazard 12m)"),
        ])
    ]

    for title, rows in specs:
        print(f"\n{title}")
        print(f"{'Segment':<27} | {'Loans':>7} | {'Actual':>6} | {'12m PD Feeding Row':<24} | {'Expected':>8} | {'Z-Score':>7} | {'Rel Error':>9} | {'Stricter Gate Status'}")
        print("-" * 115)
        tot_n = sum(r[1] for r in rows)
        tot_act = sum(r[2] for r in rows)
        tot_exp = sum(r[1] * r[3] for r in rows)
        tot_var = sum(r[1] * r[3] * (1.0 - r[3]) for r in rows)
        tot_sd = np.sqrt(tot_var)
        tot_z = (tot_act - tot_exp) / tot_sd
        tot_err = (tot_exp - tot_act) / tot_exp * 100.0

        failed_segments = []
        for r in rows:
            seg, n, act, p, p_label = r
            exp = n * p
            var = n * p * (1.0 - p)
            sd = np.sqrt(var)
            z = (act - exp) / sd
            err = (exp - act) / exp * 100.0
            status = "🔴 FAIL" if (abs(z) > 2.0 or abs(err) > 15.0) else "🟢 PASS"
            if status == "🔴 FAIL":
                failed_segments.append(seg)
            print(f"{seg:<27} | {n:>7,d} | {act:>6,d} | {p_label:<24} | {exp:>8.1f} | {z:>+6.2f}σ | {err:>+8.1f}% | {status}")
        print("-" * 115)
        
        agg_pass = (abs(tot_z) <= 2.0 and abs(tot_err) <= 15.0)
        if agg_pass and len(failed_segments) > 0:
            tot_status = "aggregate pass, state-level FAIL (offsetting errors)"
        elif not agg_pass:
            tot_status = "🔴 FAIL (|Z| > 2.0)" if abs(tot_z) > 2.0 else "🔴 FAIL"
        else:
            tot_status = "🟢 PASS (Aggregate & State-Level)"
            
        print(f"{'PORTFOLIO TOTAL':<27} | {tot_n:>7,d} | {tot_act:>6,d} | {' ':24} | {tot_exp:>8.1f} | {tot_z:>+6.2f}σ | {tot_err:>+8.1f}% | {tot_status}")
        print(f"State-Level Verdict: {'🔴 FAIL' if failed_segments else '🟢 PASS'} (Breaches: {', '.join(failed_segments) if failed_segments else 'None'})")
        print(f"Plan Gate 1 Rule (per state and in total): {'🔴 FAIL' if (not agg_pass or failed_segments) else '🟢 PASS'}")

    print("\n=========================================================================================================================")

if __name__ == "__main__":
    run_reproduce_backtest()
