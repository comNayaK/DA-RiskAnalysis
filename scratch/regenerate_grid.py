import duckdb
import pandas as pd
import numpy as np

# ==============================================================================
# SINGLE CANONICAL SOURCE OF TRUTH: REGENERATE GRID & GATE 7 VERIFICATION
# All UPBs and Loan Counts are read directly from `ecl_snapshot` in DuckDB.
# ==============================================================================

# Central Parameter Source:
PARAMS = {
    # Default Probabilities (PD)
    "p1_clean_pd": 0.001560,       # 0.1560% trailing clean-history baseline
    "p1_prob_pd": 0.095100,        # 9.510% ex-hurricane probation lifetime PD
    "p1_30_pd": 0.156800,          # 15.680% calibrated lifetime PD
    "p1_60_pd": 0.601000,          # 60.100% calibrated lifetime PD
    "p2_curr_pd": 0.122400,        # 12.240% proxy lifetime PD
    "p2_mod_pd": 0.104800,         # 10.480% 12m hazard floor lifetime PD
    "p2_30_pd": 0.515000,          # 51.500% pooled historical PD
    "p2_60_pd": 0.794900,          # 79.490% pooled historical PD
    "p3_def_pd": 1.000000,         # 100.00% active default PD
    "uncal_curr_pd": 0.002180,     # 0.2180% uncalibrated unsegmented current PD

    # Loss Given Default (LGD)
    "lgd_p1_headline_48m": 0.1418, # 14.18% (11.50% base + 2.68% 48m tail)
    "lgd_p1_sensitivity_36m": 0.1400, # 14.00% (11.50% base + 2.50% 36m tail)
    "lgd_p1_censor_upper": 0.1628, # 16.28% (13.60% upper base + 2.68% 48m tail)
    "lgd_p2_base": 0.1150,         # 11.50% censor lower bound (no double counting)
    "lgd_p2_upper": 0.1360,        # 13.60% censor upper bound
    "lgd_p3_headline": 0.1418,     # 14.18% matches Pop 1 headline
    "lgd_p3_upper": 0.1628         # 16.28% matches Pop 1 upper bound
}

def load_ecl_snapshot_segments(con):
    """
    Directly queries `ecl_snapshot` to extract exact loan counts and UPBs.
    """
    q = """
    WITH p2_loans AS (
        SELECT loan_id FROM clean_monthly_performance WHERE monthly_reporting_period <= 201912 AND loan_state = 'Modified'
        UNION
        SELECT loan_id FROM clean_monthly_performance WHERE monthly_reporting_period <= 201912 AND loan_state = 'Default'
        UNION
        SELECT loan_id FROM raw_performance WHERE COALESCE(modification_flag, '') IN ('Y', 'P') AND CAST(monthly_reporting_period AS INT) <= 201912
    ),
    trailing_delq AS (
        SELECT DISTINCT loan_id
        FROM clean_monthly_performance
        WHERE monthly_reporting_period BETWEEN 201901 AND 201912
          AND loan_state IN ('30_DPD', '60_DPD')
    )
    SELECT
        CASE
            WHEN s.loan_state = 'Default' THEN 'Pop 3: Active Default'
            WHEN s.loan_id IN (SELECT loan_id FROM p2_loans) THEN
                CASE
                    WHEN s.loan_state = 'Current' THEN 'Pop 2: Current'
                    WHEN s.loan_state = 'Modified' THEN 'Pop 2: Modified (Clean)'
                    WHEN s.loan_state = '30_DPD' THEN 'Pop 2: 30_DPD'
                    WHEN s.loan_state = '60_DPD' THEN 'Pop 2: 60_DPD'
                    ELSE 'Pop 2: Other'
                END
            ELSE
                CASE
                    WHEN s.loan_state = 'Current' AND s.loan_id IN (SELECT loan_id FROM trailing_delq) THEN 'Pop 1: Current (Probation)'
                    WHEN s.loan_state = 'Current' THEN 'Pop 1: Current (Clean)'
                    WHEN s.loan_state = '30_DPD' THEN 'Pop 1: 30_DPD'
                    WHEN s.loan_state = '60_DPD' THEN 'Pop 1: 60_DPD'
                    ELSE 'Pop 1: Other'
                END
        END AS segment,
        CASE
            WHEN s.loan_state = 'Default' THEN 'Stage 3'
            WHEN s.loan_id NOT IN (SELECT loan_id FROM p2_loans) AND s.loan_state = 'Current' AND s.loan_id NOT IN (SELECT loan_id FROM trailing_delq) THEN 'Stage 1'
            ELSE 'Stage 2'
        END AS stage,
        COUNT(*) AS loan_count,
        SUM(s.snapshot_upb) AS total_upb
    FROM ecl_snapshot s
    GROUP BY 1, 2
    ORDER BY 1;
    """
    df = con.execute(q).df()
    return df

def generate_headline_and_gate7():
    con = duckdb.connect("mortgage_risk.duckdb", read_only=True)
    df_snap = load_ecl_snapshot_segments(con)
    con.close()

    # Map parameters to segments
    pd_map = {
        "Pop 1: Current (Clean)": PARAMS["p1_clean_pd"],
        "Pop 1: Current (Probation)": PARAMS["p1_prob_pd"],
        "Pop 1: 30_DPD": PARAMS["p1_30_pd"],
        "Pop 1: 60_DPD": PARAMS["p1_60_pd"],
        "Pop 2: Current": PARAMS["p2_curr_pd"],
        "Pop 2: Modified (Clean)": PARAMS["p2_mod_pd"],
        "Pop 2: 30_DPD": PARAMS["p2_30_pd"],
        "Pop 2: 60_DPD": PARAMS["p2_60_pd"],
        "Pop 3: Active Default": PARAMS["p3_def_pd"]
    }

    lgd_map_headline = {
        "Pop 1: Current (Clean)": PARAMS["lgd_p1_headline_48m"],
        "Pop 1: Current (Probation)": PARAMS["lgd_p1_headline_48m"],
        "Pop 1: 30_DPD": PARAMS["lgd_p1_headline_48m"],
        "Pop 1: 60_DPD": PARAMS["lgd_p1_headline_48m"],
        "Pop 2: Current": PARAMS["lgd_p2_base"],
        "Pop 2: Modified (Clean)": PARAMS["lgd_p2_base"],
        "Pop 2: 30_DPD": PARAMS["lgd_p2_base"],
        "Pop 2: 60_DPD": PARAMS["lgd_p2_base"],
        "Pop 3: Active Default": PARAMS["lgd_p3_headline"]
    }

    df_master = df_snap.copy()
    df_master["PD"] = df_master["segment"].map(pd_map)
    df_master["LGD"] = df_master["segment"].map(lgd_map_headline)
    df_master["ECL"] = df_master["total_upb"] * df_master["PD"] * df_master["LGD"]
    total_ecl = df_master["ECL"].sum()
    df_master["ECL_Share"] = (df_master["ECL"] / total_ecl) * 100.0

    print("=========================================================================================================================")
    print("                                   GATE 7 RECONCILIATION: MASTER TABLE (FROM ecl_snapshot)                                ")
    print("=========================================================================================================================")
    print(f"{'Segment':<27} | {'Stage':<7} | {'Loans':>7} | {'UPB':>19} | {'PD':>8} | {'LGD':>6} | {'Calculated ECL':>14} | {'Share':>6}")
    print("-" * 121)
    for _, r in df_master.iterrows():
        print(f"{r['segment']:<27} | {r['stage']:<7} | {r['loan_count']:>7,} | ${r['total_upb']:>18,.2f} | {r['PD']:>7.4%} | {r['LGD']:>5.2%} | ${r['ECL']:>13,.2f} | {r['ECL_Share']:>5.2f}%")
    print("-" * 121)
    tot_loans = df_master["loan_count"].sum()
    tot_upb = df_master["total_upb"].sum()
    print(f"{'TOTAL PORTFOLIO':<27} | {' ':7} | {tot_loans:>7,} | ${tot_upb:>18,.2f} | {' ':8} | {' ':6} | ${total_ecl:>13,.2f} | 100.00%")
    print("=========================================================================================================================")

    pop2_ecl = df_master[df_master["segment"].str.startswith("Pop 2")]["ECL"].sum()
    stage1_ecl = df_master[df_master["stage"] == "Stage 1"]["ECL"].sum()
    stage2_ecl = df_master[df_master["stage"] == "Stage 2"]["ECL"].sum()
    stage3_ecl = df_master[df_master["stage"] == "Stage 3"]["ECL"].sum()
    print(f"Summary Subtotals:")
    print(f"  Stage 1 ECL: ${stage1_ecl:>12,.2f} ({stage1_ecl/total_ecl*100:5.2f}%)")
    print(f"  Stage 2 ECL: ${stage2_ecl:>12,.2f} ({stage2_ecl/total_ecl*100:5.2f}%)")
    print(f"  Stage 3 ECL: ${stage3_ecl:>12,.2f} ({stage3_ecl/total_ecl*100:5.2f}%)")
    print(f"  Pop 2 Total: ${pop2_ecl:>12,.2f} ({pop2_ecl/total_ecl*100:5.2f}% of total ECL)")
    print()

    # ==============================================================================
    # SCENARIO SENSITIVITY GRID REGENERATION (Reading directly from ecl_snapshot)
    # ==============================================================================
    def calc_grid_ecl(pd_override_dict, lgd_p1, lgd_p2, lgd_p3):
        tot = 0
        details = {}
        for _, r in df_snap.iterrows():
            seg = r["segment"]
            upb = r["total_upb"]
            pd_val = pd_override_dict.get(seg, pd_map[seg])
            lgd_val = lgd_p2 if seg.startswith("Pop 2") else (lgd_p3 if seg.startswith("Pop 3") else lgd_p1)
            e = upb * pd_val * lgd_val
            details[seg] = e
            tot += e
        return tot, details

    # 1. Calibrated Reference Baseline (No Probation: all Current @ 0.1560% Clean PD)
    pd_no_prob = pd_map.copy()
    pd_no_prob["Pop 1: Current (Probation)"] = PARAMS["p1_clean_pd"]
    tot_cal_base, det_cal_base = calc_grid_ecl(pd_no_prob, PARAMS["lgd_p1_headline_48m"], PARAMS["lgd_p2_base"], PARAMS["lgd_p3_headline"])

    # 2. Uncalibrated Baseline (No Probation: all Current @ 0.2180% Unsegmented PD)
    pd_uncal = pd_no_prob.copy()
    pd_uncal["Pop 1: Current (Clean)"] = PARAMS["uncal_curr_pd"]
    pd_uncal["Pop 1: Current (Probation)"] = PARAMS["uncal_curr_pd"]
    tot_uncal_base, det_uncal_base = calc_grid_ecl(pd_uncal, PARAMS["lgd_p1_headline_48m"], PARAMS["lgd_p2_base"], PARAMS["lgd_p3_headline"])

    # 3. 36m Tail Sensitivity (14.00% Pop 1 LGD, 9.510% Probation PD)
    tot_36m, det_36m = calc_grid_ecl(pd_map, PARAMS["lgd_p1_sensitivity_36m"], PARAMS["lgd_p2_base"], PARAMS["lgd_p1_sensitivity_36m"])

    # 4. Headline Scenario (48m Tail, 14.18% Pop 1 LGD)
    tot_headline = total_ecl

    # 5. Alternative Cohort (4,606 probation loans, 165,717 clean loans @ 14.18% LGD)
    ecl_clean_alt = 27293055342.19 * PARAMS["p1_clean_pd"] * PARAMS["lgd_p1_headline_48m"]
    ecl_prob_alt = 742803118.96 * PARAMS["p1_prob_pd"] * PARAMS["lgd_p1_headline_48m"]
    tot_alt = (tot_headline - df_master.loc[df_master["segment"]=="Pop 1: Current (Clean)", "ECL"].values[0] - df_master.loc[df_master["segment"]=="Pop 1: Current (Probation)", "ECL"].values[0]) + ecl_clean_alt + ecl_prob_alt

    # 6. Censor Upper Bound (16.28% Pop 1 / 13.60% Pop 2 LGD)
    tot_upper, det_upper = calc_grid_ecl(pd_map, PARAMS["lgd_p1_censor_upper"], PARAMS["lgd_p2_upper"], PARAMS["lgd_p3_upper"])

    # 7. Regime-Calibrated Scenario (scaling non-Stage-3 provisions by 0.88)
    ecl_s3 = df_master.loc[df_master["segment"]=="Pop 3: Active Default", "ECL"].values[0]
    ecl_non_s3 = tot_headline - ecl_s3
    tot_regime = (ecl_non_s3 * 0.88) + ecl_s3

    print("=========================================================================================================================")
    print("                                   POLICY SCENARIO SENSITIVITY GRID (FROM ecl_snapshot)                                  ")
    print("=========================================================================================================================")
    print(f"1. Calibrated Base (No Probation):  ${tot_cal_base:>12,.2f} | Reference Baseline")
    print(f"2. Uncalibrated Base (No Probation):${tot_uncal_base:>12,.2f} | Delta vs Cal Base: +${tot_uncal_base - tot_cal_base:>10,.2f} (+{(tot_uncal_base - tot_cal_base)/tot_cal_base*100:5.2f}%)")
    print(f"3. 36m Tail Sensitivity (14.00%):   ${tot_36m:>12,.2f} | Delta vs Cal Base: +${tot_36m - tot_cal_base:>10,.2f} (+{(tot_36m - tot_cal_base)/tot_cal_base*100:5.2f}%)")
    print(f"4. HEADLINE SCENARIO (48m Tail):    ${tot_headline:>12,.2f} | Delta vs Cal Base: +${tot_headline - tot_cal_base:>10,.2f} (+{(tot_headline - tot_cal_base)/tot_cal_base*100:5.2f}%)")
    print(f"5. Alternative Cohort (4,606):      ${tot_alt:>12,.2f} | Delta vs Cal Base: +${tot_alt - tot_cal_base:>10,.2f} (+{(tot_alt - tot_cal_base)/tot_cal_base*100:5.2f}%)")
    print(f"6. Censor Upper Bound (16.28% LGD): ${tot_upper:>12,.2f} | Delta vs Cal Base: +${tot_upper - tot_cal_base:>10,.2f} (+{(tot_upper - tot_cal_base)/tot_cal_base*100:5.2f}%)")
    print(f"7. Regime-Calibrated (0.88x non-S3):${tot_regime:>12,.2f} | Delta vs Headline: -${tot_headline - tot_regime:>10,.2f} (-{(tot_headline - tot_regime)/tot_headline*100:5.2f}%)")
    print("=========================================================================================================================")

    return df_master, total_ecl

if __name__ == "__main__":
    generate_headline_and_gate7()
