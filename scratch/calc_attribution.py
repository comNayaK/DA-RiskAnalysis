import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import duckdb
import pandas as pd
from scratch.regenerate_grid import load_ecl_snapshot_segments, PARAMS
from scratch.rolling_backtest import init_backtest_tables, compute_pop2_pds, compute_pop1_params

def run_attribution():
    con = duckdb.connect("mortgage_risk.duckdb", read_only=True)
    
    print("=========================================================================================================================")
    print("             EXPECTED-DEFAULT AND ECL ATTRIBUTION: v0.1 LEGACY FROZEN -> MEASURED TRAILING                               ")
    print("=========================================================================================================================\n")

    # -------------------------------------------------------------------------
    # PART 1: 201812 OUT-OF-SAMPLE BACKTEST EXPECTED DEFAULTS ATTRIBUTION
    # -------------------------------------------------------------------------
    init_backtest_tables(con)
    pop2_params = compute_pop2_pds(con)
    pop1_params = compute_pop1_params(con)

    # Exact snapshot 201812 loan census counts (194,925 active loans):
    counts = {
        "Pop 1: Current (Clean)": 187493,
        "Pop 1: Current (Probation)": 3983,
        "Pop 1: 30_DPD": 1255,
        "Pop 1: 60_DPD": 220,
        "Pop 2: Current": 636,
        "Pop 2: 30_DPD": 115,
        "Pop 2: 60_DPD": 87,
        "Pop 2: Modified": 1136,
    }

    # Legacy Frozen Spec D PDs:
    pds_v01 = {
        "Pop 1: Current (Clean)": 0.001560,
        "Pop 1: Current (Probation)": 0.032236,
        "Pop 1: 30_DPD": 0.120800,
        "Pop 1: 60_DPD": 0.590900,
        "Pop 2: Current": 0.096397,
        "Pop 2: 30_DPD": 0.531944,
        "Pop 2: 60_DPD": 0.793258,
        "Pop 2: Modified": 0.120599,
    }

    # Measured Trailing PDs (strictly <= 201812):
    pds_meas = {
        "Pop 1: Current (Clean)": pop1_params["trailing"][201812]["clean"][0],       # 313 / 206,839 = 0.151325%
        "Pop 1: Current (Probation)": pop1_params["trailing"][201812]["prob"][0],     # 116 / 4,204 = 2.759277%
        "Pop 1: 30_DPD": 0.120777,
        "Pop 1: 60_DPD": 0.590935,
        "Pop 2: Current": pop2_params["trailing"][201812]["Current"]["pd"],           # 36 / 423 = 8.510638%
        "Pop 2: 30_DPD": pop2_params["trailing"][201812]["30_DPD"]["pd"],             # 25 / 87 = 28.735632%
        "Pop 2: 60_DPD": pop2_params["trailing"][201812]["60_DPD"]["pd"],             # 49 / 76 = 64.473684%
        "Pop 2: Modified": pop2_params["trailing"][201812]["Modified"]["pd"],         # 91 / 740 = 12.297297%
    }

    exp_v01 = {k: counts[k] * pds_v01[k] for k in counts}
    exp_meas = {k: counts[k] * pds_meas[k] for k in counts}

    tot_v01_defs = sum(exp_v01.values())
    tot_meas_defs = sum(exp_meas.values())

    # Component deltas:
    p2_keys = ["Pop 2: Current", "Pop 2: 30_DPD", "Pop 2: 60_DPD", "Pop 2: Modified"]
    delta_p2_defs = sum(exp_meas[k] - exp_v01[k] for k in p2_keys)
    delta_clean_defs = exp_meas["Pop 1: Current (Clean)"] - exp_v01["Pop 1: Current (Clean)"]
    delta_prob_defs = exp_meas["Pop 1: Current (Probation)"] - exp_v01["Pop 1: Current (Probation)"]
    delta_matrix_defs = (exp_meas["Pop 1: 30_DPD"] - exp_v01["Pop 1: 30_DPD"]) + (exp_meas["Pop 1: 60_DPD"] - exp_v01["Pop 1: 60_DPD"])

    print("1. EXPECTED DEFAULTS ATTRIBUTION (201812 SNAPSHOT -> 2019 OUTCOMES):")
    print(f"{'Segment':<28} | {'Loans':>7} | {'v0.1 PD':>9} | {'v0.1 Exp':>9} | {'Trailing PD':>12} | {'Trailing Exp':>12} | {'Delta Loans':>11}")
    print("-" * 105)
    for k in counts:
        d = exp_meas[k] - exp_v01[k]
        print(f"{k:<28} | {counts[k]:>7,d} | {pds_v01[k]:>8.4%} | {exp_v01[k]:>9.2f} | {pds_meas[k]:>11.4%} | {exp_meas[k]:>12.2f} | {d:>+11.2f}")
    print("-" * 105)
    print(f"{'TOTAL PORTFOLIO':<28} | {sum(counts.values()):>7,d} | {'':>9} | {tot_v01_defs:>9.2f} | {'':>12} | {tot_meas_defs:>12.2f} | {tot_meas_defs - tot_v01_defs:>+11.2f}")
    print("\nExpected Defaults Component Summary:")
    print(f" - Pop 2 Dynamic Trailing Updates:    {delta_p2_defs:>+6.1f} defaults (~ -45.6 loans)")
    print(f" - Pop 1 Clean Rate Update (0.1513%): {delta_clean_defs:>+6.1f} defaults (~  -8.8 loans)")
    print(f" - Pop 1 Probation Update (2.7593%):  {delta_prob_defs:>+6.1f} defaults (~ -18.5 loans)")
    print(f" - Pop 1 Matrix Transitions (30/60m): {delta_matrix_defs:>+6.2f} defaults")
    print(f" - TOTAL EXPECTED DEFAULT REDUCTION:  {tot_meas_defs - tot_v01_defs:>+6.1f} defaults (1,031.0 -> 958.2)\n")

    # -------------------------------------------------------------------------
    # PART 2: 201912 PORTFOLIO ECL PROVISION ATTRIBUTION (FROM ecl_snapshot)
    # -------------------------------------------------------------------------
    df_snap = load_ecl_snapshot_segments(con)
    base_ecl = 45073223.87

    pd_ecl_base = {
        "Pop 1: Current (Clean)": 0.001560,
        "Pop 1: Current (Probation)": 0.095100,
        "Pop 1: 30_DPD": 0.156800,
        "Pop 1: 60_DPD": 0.601000,
        "Pop 2: Current": 0.122400,
        "Pop 2: Modified (Clean)": 0.104800,
        "Pop 2: 30_DPD": 0.515000,
        "Pop 2: 60_DPD": 0.794900,
        "Pop 3: Active Default": 1.000000,
    }

    def calc_ecl_total(pd_map):
        tot = 0.0
        for _, r in df_snap.iterrows():
            seg = r["segment"]
            upb = r["total_upb"]
            pd_val = pd_map[seg]
            lgd_val = PARAMS["lgd_p2_base"] if seg.startswith("Pop 2") else (PARAMS["lgd_p3_headline"] if seg.startswith("Pop 3") else PARAMS["lgd_p1_headline_48m"])
            tot += upb * pd_val * lgd_val
        return tot

    # A. Strict Clean Only:
    pd_clean_only = pd_ecl_base.copy()
    pd_clean_only["Pop 1: Current (Clean)"] = 313.0 / 206839.0
    ecl_clean_only = calc_ecl_total(pd_clean_only)
    delta_clean_ecl = ecl_clean_only - base_ecl

    # B. Measured Trailing Pop 2 Inputs Only:
    pd_pop2_only = pd_ecl_base.copy()
    pd_pop2_only["Pop 2: Current"] = 36.0 / 423.0
    pd_pop2_only["Pop 2: 30_DPD"] = 25.0 / 87.0
    pd_pop2_only["Pop 2: 60_DPD"] = 49.0 / 76.0
    pd_pop2_only["Pop 2: Modified (Clean)"] = 91.0 / 740.0
    ecl_pop2_only = calc_ecl_total(pd_pop2_only)
    delta_pop2_ecl = ecl_pop2_only - base_ecl

    # C. All Measured Trailing Inputs Combined (Pop 2 + Clean):
    pd_all_meas = pd_clean_only.copy()
    pd_all_meas["Pop 2: Current"] = 36.0 / 423.0
    pd_all_meas["Pop 2: 30_DPD"] = 25.0 / 87.0
    pd_all_meas["Pop 2: 60_DPD"] = 49.0 / 76.0
    pd_all_meas["Pop 2: Modified (Clean)"] = 91.0 / 740.0
    ecl_all_meas = calc_ecl_total(pd_all_meas)
    delta_all_meas_ecl = ecl_all_meas - base_ecl

    print("2. 201912 PORTFOLIO ECL PROVISION ATTRIBUTION (FROM ecl_snapshot):")
    print(f"{'Specification / Scenario':<36} | {'Total ECL ($)':>14} | {'ECL Delta ($)':>14} | {'Delta %':>8}")
    print("-" * 80)
    print(f"{'Headline v0.1 Provision (Baseline)':<36} | ${base_ecl:>13,.2f} | {'$0.00':>14} | {'0.00%':>8}")
    print(f"{'Pop 2 Inputs Only (Measured)':<36} | ${ecl_pop2_only:>13,.2f} | -${abs(delta_pop2_ecl):>13,.2f} | {delta_pop2_ecl / base_ecl:>+7.2%}")
    print(f"{'Strict Clean PD Only (0.1513%)':<36} | ${ecl_clean_only:>13,.2f} | -${abs(delta_clean_ecl):>13,.2f} | {delta_clean_ecl / base_ecl:>+7.2%}")
    print(f"{'All Measured Inputs Combined':<36} | ${ecl_all_meas:>13,.2f} | -${abs(delta_all_meas_ecl):>13,.2f} | {delta_all_meas_ecl / base_ecl:>+7.2%}")
    print("-" * 80)
    print("ECL Reserve Impact Summary:")
    print(f" - Pop 2 Inputs Alone:     -${abs(delta_pop2_ecl):,.2f} (~ -$725k / -1.61%)")
    print(f" - Clean PD Alone:         -${abs(delta_clean_ecl):,.2f} (~ -$181k / -0.40%)")
    print(f" - All Measured Combined:  -${abs(delta_all_meas_ecl):,.2f} (~ -$907k / -2.01%)\n")
    print("=========================================================================================================================\n")

if __name__ == "__main__":
    run_attribution()
