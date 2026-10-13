import os
import sys
import duckdb
import numpy as np
import pandas as pd

# Add repository root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scratch.regenerate_grid import load_ecl_snapshot_segments, PARAMS
from scratch.rolling_backtest import (
    init_backtest_tables,
    compute_pop2_pds,
    compute_pop1_params,
    counts_df_to_array,
    build_markov_matrices,
)
from src.lgd import compute_lgd_bounds
from src.markov import compute_12month_pd
from src.config import FICO_BANDS, TRANSIENT_STATES, ALL_STATES

OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "output", "tableau"))

def export_ecl_master(con):
    """
    Exports ecl_master.csv with aggregated segments, counts, UPB, PD, LGD, and calculated ECL.
    """
    df_snap = load_ecl_snapshot_segments(con)
    
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
    df_master["pd"] = df_master["segment"].map(pd_map)
    df_master["lgd"] = df_master["segment"].map(lgd_map_headline)
    df_master["calculated_ecl"] = df_master["total_upb"] * df_master["pd"] * df_master["lgd"]
    total_ecl = df_master["calculated_ecl"].sum()
    df_master["ecl_share_pct"] = (df_master["calculated_ecl"] / total_ecl) * 100.0

    # Reconciliation Checks:
    tot_loans = int(df_master["loan_count"].sum())
    tot_upb = float(df_master["total_upb"].sum())
    tot_ecl = float(total_ecl)

    expected_loans = 174293
    expected_upb = 28708141480.57
    expected_ecl = 45073223.87

    assert tot_loans == expected_loans, f"Loan count mismatch: got {tot_loans}, expected {expected_loans}"
    assert abs(tot_upb - expected_upb) < 0.05, f"UPB mismatch: got {tot_upb:.2f}, expected {expected_upb:.2f}"
    assert abs(tot_ecl - expected_ecl) < 0.05, f"ECL mismatch: got {tot_ecl:.2f}, expected {expected_ecl:.2f}"

    out_csv = os.path.join(OUTPUT_DIR, "ecl_master.csv")
    df_master.to_csv(out_csv, index=False)
    return df_master, len(df_master), (tot_ecl, tot_loans, tot_upb)

def export_ecl_scenarios(df_master, con):
    """
    Exports ecl_scenarios.csv with policy scenarios and sensitivity grid.
    """
    df_snap = load_ecl_snapshot_segments(con)
    
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

    def calc_grid_ecl(pd_override_dict, lgd_p1, lgd_p2, lgd_p3):
        tot = 0.0
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

    # 1. Calibrated Reference Baseline (No Probation)
    pd_no_prob = pd_map.copy()
    pd_no_prob["Pop 1: Current (Probation)"] = PARAMS["p1_clean_pd"]
    tot_cal_base, _ = calc_grid_ecl(pd_no_prob, PARAMS["lgd_p1_headline_48m"], PARAMS["lgd_p2_base"], PARAMS["lgd_p3_headline"])

    # 2. Uncalibrated Baseline (No Probation: all Current @ 0.2180%)
    pd_uncal = pd_no_prob.copy()
    pd_uncal["Pop 1: Current (Clean)"] = PARAMS["uncal_curr_pd"]
    pd_uncal["Pop 1: Current (Probation)"] = PARAMS["uncal_curr_pd"]
    tot_uncal_base, _ = calc_grid_ecl(pd_uncal, PARAMS["lgd_p1_headline_48m"], PARAMS["lgd_p2_base"], PARAMS["lgd_p3_headline"])

    # 3. 36m Tail Sensitivity (14.00% Pop 1 LGD)
    tot_36m, _ = calc_grid_ecl(pd_map, PARAMS["lgd_p1_sensitivity_36m"], PARAMS["lgd_p2_base"], PARAMS["lgd_p1_sensitivity_36m"])

    # 4. Headline Scenario (48m Tail, 14.18% Pop 1 LGD)
    tot_headline = float(df_master["calculated_ecl"].sum())

    # 5. Alternative Cohort (4,606 probation loans)
    ecl_clean_alt = 27293055342.19 * PARAMS["p1_clean_pd"] * PARAMS["lgd_p1_headline_48m"]
    ecl_prob_alt = 742803118.96 * PARAMS["p1_prob_pd"] * PARAMS["lgd_p1_headline_48m"]
    tot_alt = (tot_headline - df_master.loc[df_master["segment"]=="Pop 1: Current (Clean)", "calculated_ecl"].values[0] 
               - df_master.loc[df_master["segment"]=="Pop 1: Current (Probation)", "calculated_ecl"].values[0]) + ecl_clean_alt + ecl_prob_alt

    # 6. Censor Upper Bound (16.28% Pop 1 / 13.60% Pop 2 LGD)
    tot_upper, _ = calc_grid_ecl(pd_map, PARAMS["lgd_p1_censor_upper"], PARAMS["lgd_p2_upper"], PARAMS["lgd_p3_upper"])

    # 7. Measured Trailing Scaling (0.9518x non-Stage-3 ECL)
    ecl_s3 = df_master.loc[df_master["segment"]=="Pop 3: Active Default", "calculated_ecl"].values[0]
    ecl_non_s3 = tot_headline - ecl_s3
    scale_trailing = 912.0 / 958.2
    tot_regime_trailing = (ecl_non_s3 * scale_trailing) + ecl_s3

    # 8. Legacy Spec D Scaling (0.885x non-Stage-3 ECL)
    tot_regime_legacy = (ecl_non_s3 * 0.885) + ecl_s3

    # 9. 2019 Realized Clean PD Sensitivity (0.1163%)
    pd_realized_clean = pd_map.copy()
    pd_realized_clean["Pop 1: Current (Clean)"] = 218.0 / 187493.0
    tot_realized_clean, _ = calc_grid_ecl(pd_realized_clean, PARAMS["lgd_p1_headline_48m"], PARAMS["lgd_p2_base"], PARAMS["lgd_p3_headline"])

    # 10. Strict Clean PD Only (0.1513%)
    pd_strict_clean = pd_map.copy()
    pd_strict_clean["Pop 1: Current (Clean)"] = 313.0 / 206839.0
    tot_strict_clean, _ = calc_grid_ecl(pd_strict_clean, PARAMS["lgd_p1_headline_48m"], PARAMS["lgd_p2_base"], PARAMS["lgd_p3_headline"])

    # 11. Measured Trailing Pop 2 + Strict Clean
    pd_meas_trailing = pd_strict_clean.copy()
    pd_meas_trailing["Pop 2: Current"] = 36.0 / 423.0
    pd_meas_trailing["Pop 2: 30_DPD"] = 25.0 / 87.0
    pd_meas_trailing["Pop 2: 60_DPD"] = 49.0 / 76.0
    pd_meas_trailing["Pop 2: Modified (Clean)"] = 91.0 / 740.0
    tot_meas_trailing, _ = calc_grid_ecl(pd_meas_trailing, PARAMS["lgd_p1_headline_48m"], PARAMS["lgd_p2_base"], PARAMS["lgd_p3_headline"])

    # 12. Measured Pooled Pop 2 + Strict Clean
    pd_meas_pooled = pd_strict_clean.copy()
    pd_meas_pooled["Pop 2: Current"] = 141.0 / 1396.0
    pd_meas_pooled["Pop 2: 30_DPD"] = 105.0 / 306.0
    pd_meas_pooled["Pop 2: 60_DPD"] = 138.0 / 213.0
    pd_meas_pooled["Pop 2: Modified (Clean)"] = 321.0 / 2199.0
    tot_meas_pooled, _ = calc_grid_ecl(pd_meas_pooled, PARAMS["lgd_p1_headline_48m"], PARAMS["lgd_p2_base"], PARAMS["lgd_p3_headline"])

    scenarios = [
        {"scenario_id": "SCEN_01", "scenario_name": "Calibrated Base (No Probation)", "total_ecl": tot_cal_base, "description": "All performing loans at 0.1560% clean PD; no probation Stage 2 split"},
        {"scenario_id": "SCEN_02", "scenario_name": "Uncalibrated Base (No Probation)", "total_ecl": tot_uncal_base, "description": "All performing loans at uncalibrated 0.2180% current PD"},
        {"scenario_id": "SCEN_03", "scenario_name": "36m Tail Sensitivity (14.00% LGD)", "total_ecl": tot_36m, "description": "14.00% Pop 1 LGD (11.50% base + 2.50% 36m tail); 9.510% probation PD"},
        {"scenario_id": "SCEN_04", "scenario_name": "Headline Scenario (48m Tail, 14.18% LGD)", "total_ecl": tot_headline, "description": "Single headline reserve basis (14.18% Pop 1 LGD, 11.50% Pop 2 LGD, 9.510% probation PD)"},
        {"scenario_id": "SCEN_05", "scenario_name": "Alternative Cohort (4,606 Probation)", "total_ecl": tot_alt, "description": "Extended probation cohort identification at 14.18% LGD"},
        {"scenario_id": "SCEN_06", "scenario_name": "Censor Upper Bound (16.28% LGD)", "total_ecl": tot_upper, "description": "Upper bound censoring (16.28% Pop 1, 13.60% Pop 2 LGD)"},
        {"scenario_id": "SCEN_07", "scenario_name": "Measured Trailing Scaling (0.9518x)", "total_ecl": tot_regime_trailing, "description": "Uniform scaling of non-Stage-3 ECL by measured trailing ratio 912 / 958.2 = 0.9518x"},
        {"scenario_id": "SCEN_08", "scenario_name": "Legacy Spec D Scaling (0.885x)", "total_ecl": tot_regime_legacy, "description": "Legacy uniform scaling of non-Stage-3 ECL by 0.885x (912 / 1,031)"},
        {"scenario_id": "SCEN_09", "scenario_name": "2019 Realized Clean PD (0.1163%)", "total_ecl": tot_realized_clean, "description": "Evaluating clean history at 2019 realized default rate 0.1163% vs 0.1560% policy choice"},
        {"scenario_id": "SCEN_10", "scenario_name": "Strict Clean Only (0.1513%)", "total_ecl": tot_strict_clean, "description": "Strict Pop 1 Clean PD (313/206,839) with headline baseline parameters"},
        {"scenario_id": "SCEN_11", "scenario_name": "Measured Trailing Pop 2 + Strict Clean", "total_ecl": tot_meas_trailing, "description": "All measured trailing parameters (Pop 2 and Clean) applied to portfolio"},
        {"scenario_id": "SCEN_12", "scenario_name": "Measured Pooled Pop 2 + Strict Clean", "total_ecl": tot_meas_pooled, "description": "Measured pooled historical parameters applied to portfolio"},
    ]

    df_scen = pd.DataFrame(scenarios)
    df_scen["delta_vs_headline"] = df_scen["total_ecl"] - tot_headline
    df_scen["pct_delta_vs_headline"] = (df_scen["delta_vs_headline"] / tot_headline) * 100.0

    out_csv = os.path.join(OUTPUT_DIR, "ecl_scenarios.csv")
    df_scen.to_csv(out_csv, index=False)
    return df_scen, len(df_scen)

def export_vintage_curves(con):
    """
    Exports vintage_curves.csv directly from v_vintage_curves.
    """
    q = "SELECT * FROM v_vintage_curves ORDER BY orig_year, loan_age"
    df_vc = con.execute(q).df()
    out_csv = os.path.join(OUTPUT_DIR, "vintage_curves.csv")
    df_vc.to_csv(out_csv, index=False)
    return df_vc, len(df_vc)

def export_transition_matrix_fico(con):
    """
    Exports transition_matrix_fico.csv with 12m and lifetime PD by band and state.
    """
    C_port_df = con.execute("SELECT state_t, state_t_plus_1, n FROM v_transition_matrix_portfolio").df()
    C_portfolio = counts_df_to_array(C_port_df)
    Q_p, R_p, N_p, B_p, P_p = build_markov_matrices(C_portfolio)
    P_bar_p = np.block([[Q_p, R_p], [np.zeros((2, 3)), np.eye(2)]])
    P12_p = np.linalg.matrix_power(P_bar_p, 12)

    band_matrices = {}
    for band in FICO_BANDS:
        df_b = con.execute(f"SELECT state_t, state_t_plus_1, n FROM v_transition_matrix_fico WHERE fico_band = '{band}'").df()
        C_band = counts_df_to_array(df_b)
        Q_b, R_b, N_b, B_b, P_b = build_markov_matrices(C_band, C_portfolio)
        P_bar_b = np.block([[Q_b, R_b], [np.zeros((2, 3)), np.eye(2)]])
        P12_b = np.linalg.matrix_power(P_bar_b, 12)
        band_matrices[band] = (P_b, P12_b, B_b)

    band_matrices["Portfolio"] = (P_p, P12_p, B_p)

    rows = []
    for band, (P_mat, P12_mat, B_mat) in band_matrices.items():
        for i, st_from in enumerate(TRANSIENT_STATES):
            pd_12m = float(P12_mat[i, 4])       # Col 4 is Default
            pd_lifetime = float(B_mat[i, 1])   # Col 1 is Default in absorbing matrix B
            for j, st_to in enumerate(ALL_STATES):
                prob = float(P_mat[i, j])
                # Fetch actual transition count from views
                if band == "Portfolio":
                    cnt_q = f"SELECT n FROM v_transition_matrix_portfolio WHERE state_t = '{st_from}' AND state_t_plus_1 = '{st_to}'"
                else:
                    cnt_q = f"SELECT n FROM v_transition_matrix_fico WHERE fico_band = '{band}' AND state_t = '{st_from}' AND state_t_plus_1 = '{st_to}'"
                cnt_res = con.execute(cnt_q).fetchall()
                cnt = cnt_res[0][0] if len(cnt_res) > 0 else 0
                rows.append({
                    "fico_band": band,
                    "state_t": st_from,
                    "state_t_plus_1": st_to,
                    "transition_count": cnt,
                    "transition_prob": prob,
                    "pd_12m_from_state_t": pd_12m,
                    "pd_lifetime_from_state_t": pd_lifetime
                })

    df_trans = pd.DataFrame(rows)
    out_csv = os.path.join(OUTPUT_DIR, "transition_matrix_fico.csv")
    df_trans.to_csv(out_csv, index=False)
    return df_trans, len(df_trans)

def export_backtest_rolling(con):
    """
    Exports backtest_rolling.csv containing all 4 snapshots, all states,
    for both trailing and pooled parameterizations.
    """
    init_backtest_tables(con)
    pop2_params = compute_pop2_pds(con)
    pop1_params = compute_pop1_params(con)

    snapshots = [
        {"snap": 201512, "eval_yr": 2016, "e_start": 201601, "e_end": 201612},
        {"snap": 201612, "eval_yr": 2017, "e_start": 201701, "e_end": 201712},
        {"snap": 201712, "eval_yr": 2018, "e_start": 201801, "e_end": 201812},
        {"snap": 201812, "eval_yr": 2019, "e_start": 201901, "e_end": 201912},
    ]

    seg_order = [
        "Pop 1: Current (Clean)", "Pop 1: Current (Probation)", "Pop 1: 30_DPD", "Pop 1: 60_DPD",
        "Pop 2: Current", "Pop 2: 30_DPD", "Pop 2: 60_DPD", "Pop 2: Modified"
    ]

    all_rows = []
    totals_check = {}

    for mode in ["trailing", "pooled"]:
        totals_check[mode] = {}
        for s_info in snapshots:
            snap = s_info["snap"]
            eval_yr = s_info["eval_yr"]
            e_start = s_info["e_start"]
            e_end = s_info["e_end"]

            # Matrix estimation frozen <= snap
            q_mat = f"""
            SELECT state_t, state_t_plus_1, COUNT(*) as n
            FROM loan_level_transitions
            WHERE monthly_reporting_period <= {snap}
            GROUP BY state_t, state_t_plus_1
            """
            df_c = con.execute(q_mat).df()
            C = counts_df_to_array(df_c)
            Q, R, N, B, P = build_markov_matrices(C)
            P_bar = np.block([[Q, R], [np.zeros((2, 3)), np.eye(2)]])
            P12 = np.linalg.matrix_power(P_bar, 12)
            pd_p1_30 = float(P12[1, 4])
            pd_p1_60 = float(P12[2, 4])

            pd_clean, pd_clean_label = pop1_params[mode][snap]["clean"]
            pd_prob, pd_prob_label = pop1_params[mode][snap]["prob"]
            p2_snap = pop2_params[mode][snap]

            param_map = {
                "Pop 1: Current (Clean)": (pd_clean, pd_clean_label),
                "Pop 1: Current (Probation)": (pd_prob, pd_prob_label),
                "Pop 1: 30_DPD": (pd_p1_30, f"{pd_p1_30:.4%} (Matrix 12m)"),
                "Pop 1: 60_DPD": (pd_p1_60, f"{pd_p1_60:.4%} (Matrix 12m)"),
                "Pop 2: Current": (p2_snap["Current"]["pd"], p2_snap["Current"]["label"]),
                "Pop 2: 30_DPD": (p2_snap["30_DPD"]["pd"], p2_snap["30_DPD"]["label"]),
                "Pop 2: 60_DPD": (p2_snap["60_DPD"]["pd"], p2_snap["60_DPD"]["label"]),
                "Pop 2: Modified": (p2_snap["Modified"]["pd"], p2_snap["Modified"]["label"]),
            }

            q_eval = f"""
            WITH active AS (
                SELECT 
                    c.loan_id,
                    c.loan_state,
                    p2.min_p2_period
                FROM clean_monthly_performance c
                LEFT JOIN p2_first p2 ON c.loan_id = p2.loan_id
                WHERE c.monthly_reporting_period = {snap} AND c.zero_balance_code IS NULL
            ),
            with_hist AS (
                SELECT 
                    a.loan_id,
                    a.loan_state,
                    CASE 
                        WHEN a.min_p2_period IS NOT NULL AND a.min_p2_period <= {snap} THEN 'Pop2'
                        ELSE 'Pop1'
                    END as pop,
                    MAX(CASE WHEN h.loan_state IN ('30_DPD', '60_DPD') THEN 1 ELSE 0 END) as had_delinq
                FROM active a
                LEFT JOIN clean_monthly_performance h 
                  ON a.loan_id = h.loan_id AND h.monthly_reporting_period BETWEEN {snap-99} AND {snap}
                GROUP BY a.loan_id, a.loan_state, a.min_p2_period
            ),
            segmented AS (
                SELECT 
                    loan_id,
                    CASE 
                        WHEN pop = 'Pop1' AND loan_state = 'Current' AND had_delinq = 0 THEN 'Pop 1: Current (Clean)'
                        WHEN pop = 'Pop1' AND loan_state = 'Current' AND had_delinq = 1 THEN 'Pop 1: Current (Probation)'
                        WHEN pop = 'Pop1' AND loan_state = '30_DPD' THEN 'Pop 1: 30_DPD'
                        WHEN pop = 'Pop1' AND loan_state = '60_DPD' THEN 'Pop 1: 60_DPD'
                        WHEN pop = 'Pop2' AND loan_state = 'Current' THEN 'Pop 2: Current'
                        WHEN pop = 'Pop2' AND loan_state = '30_DPD' THEN 'Pop 2: 30_DPD'
                        WHEN pop = 'Pop2' AND loan_state = '60_DPD' THEN 'Pop 2: 60_DPD'
                        WHEN pop = 'Pop2' AND loan_state = 'Modified' THEN 'Pop 2: Modified'
                        ELSE 'Other'
                    END as segment
                FROM with_hist
            ),
            defs AS (
                SELECT DISTINCT loan_id 
                FROM clean_monthly_performance 
                WHERE monthly_reporting_period BETWEEN {e_start} AND {e_end} AND loan_state = 'Default'
            )
            SELECT 
                s.segment,
                COUNT(*) as n,
                COUNT(d.loan_id) as act_defs
            FROM segmented s
            LEFT JOIN defs d ON s.loan_id = d.loan_id
            WHERE s.segment != 'Other'
            GROUP BY s.segment
            ORDER BY s.segment;
            """
            df_eval = con.execute(q_eval).df()

            tot_n, tot_act, tot_exp, tot_var = 0, 0, 0.0, 0.0
            failures = []

            for seg in seg_order:
                row_match = df_eval[df_eval['segment'] == seg]
                if len(row_match) == 0:
                    continue
                n = int(row_match['n'].values[0])
                act = int(row_match['act_defs'].values[0])
                p, p_label = param_map[seg]
                exp = n * p
                var = n * p * (1.0 - p)
                sd = np.sqrt(var)
                z = (act - exp) / sd if sd > 0 else 0.0
                err = (exp - act) / exp * 100.0 if exp > 0 else 0.0
                is_fail = bool(abs(z) > 2.0 or abs(err) > 15.0)
                status = "FAIL" if is_fail else "PASS"
                if is_fail:
                    failures.append(seg)

                all_rows.append({
                    "parameterization_mode": mode,
                    "snapshot": snap,
                    "eval_year": eval_yr,
                    "segment": seg,
                    "loans_n": n,
                    "actual_defaults": act,
                    "model_pd": p,
                    "pd_basis": p_label,
                    "expected_defaults": exp,
                    "z_score": z,
                    "relative_error_pct": err,
                    "status": status,
                    "is_failure": is_fail
                })
                tot_n += n
                tot_act += act
                tot_exp += exp
                tot_var += var

            tot_sd = np.sqrt(tot_var)
            tot_z = (tot_act - tot_exp) / tot_sd if tot_sd > 0 else 0.0
            tot_err = (tot_exp - tot_act) / tot_exp * 100.0 if tot_exp > 0 else 0.0
            agg_pass = (abs(tot_z) <= 2.0 and abs(tot_err) <= 15.0)
            tot_fail = not agg_pass or (len(failures) > 0)
            tot_status = "PASS" if not tot_fail else ("FAIL (State Breaches)" if agg_pass else "FAIL")

            all_rows.append({
                "parameterization_mode": mode,
                "snapshot": snap,
                "eval_year": eval_yr,
                "segment": "PORTFOLIO TOTAL",
                "loans_n": tot_n,
                "actual_defaults": tot_act,
                "model_pd": tot_exp / tot_n if tot_n > 0 else 0.0,
                "pd_basis": "Portfolio Aggregate",
                "expected_defaults": tot_exp,
                "z_score": tot_z,
                "relative_error_pct": tot_err,
                "status": tot_status,
                "is_failure": tot_fail
            })

            totals_check[mode][snap] = {
                "active_n": tot_n,
                "actual": tot_act,
                "expected": tot_exp
            }

    # RECONCILIATION CHECKS AGAINST docs/progress_report.md
    expected_totals = {
        "trailing": {
            201512: (215270, 843, 930.3),
            201612: (233615, 1366, 955.7),
            201712: (214259, 1011, 1427.5),
            201812: (194925, 912, 958.2)
        },
        "pooled": {
            201512: (215270, 843, 936.2),
            201612: (233615, 1366, 1029.0),
            201712: (214259, 1011, 1259.8),
            201812: (194925, 912, 1124.7)
        }
    }

    for m in ["trailing", "pooled"]:
        for sn, (exp_n, exp_act, exp_e) in expected_totals[m].items():
            got = totals_check[m][sn]
            assert got["active_n"] == exp_n, f"[{m} {sn}] Active loans mismatch: {got['active_n']} vs {exp_n}"
            assert got["actual"] == exp_act, f"[{m} {sn}] Actual defaults mismatch: {got['actual']} vs {exp_act}"
            assert abs(got["expected"] - exp_e) < 0.5, f"[{m} {sn}] Expected defaults mismatch: {got['expected']:.1f} vs {exp_e}"

    df_backtest = pd.DataFrame(all_rows)
    out_csv = os.path.join(OUTPUT_DIR, "backtest_rolling.csv")
    df_backtest.to_csv(out_csv, index=False)
    return df_backtest, len(df_backtest), totals_check

def export_lgd_bounds(con):
    """
    Exports lgd_bounds.csv with empirical follow-up bounds and model specifications.
    """
    # 1. Empirical follow-up bounds from DuckDB views
    lgd_l_36, lgd_u_36, lgd_m_36 = compute_lgd_bounds(con)

    # Query 24m and 36m views directly for full parameters
    s24 = con.execute("SELECT * FROM v_lgd_severity_24m").df()
    s36 = con.execute("SELECT * FROM v_lgd_severity_36m").df()
    
    o24 = con.execute("""
        SELECT outcome, COUNT(*) as cnt, SUM(u.default_upb) as dol 
        FROM v_default_outcomes_24m o 
        JOIN v_first_default_upb u ON o.loan_id = u.loan_id 
        GROUP BY outcome
    """).df()
    o36 = con.execute("""
        SELECT outcome, COUNT(*) as cnt, SUM(u.default_upb) as dol 
        FROM v_default_outcomes_36m o 
        JOIN v_first_default_upb u ON o.loan_id = u.loan_id 
        GROUP BY outcome
    """).df()

    def get_stats(o_df, s_df):
        dol_liq = o_df.loc[o_df['outcome'] == 'Liquidated', 'dol'].sum() if 'Liquidated' in o_df['outcome'].values else 0
        dol_def = o_df.loc[o_df['outcome'] == 'Still_In_Default', 'dol'].sum() if 'Still_In_Default' in o_df['outcome'].values else 0
        dol_tot = o_df.loc[o_df['outcome'] != 'Admin_Removed', 'dol'].sum()
        p_l = dol_liq / dol_tot if dol_tot > 0 else 0
        p_u = (dol_liq + dol_def) / dol_tot if dol_tot > 0 else 0
        sev = float(s_df['empirical_loss_severity'].values[0]) if len(s_df) > 0 else 0.28
        lgd_l = p_l * sev
        lgd_u = p_u * sev
        lgd_m = (lgd_l + lgd_u) / 2.0
        return p_l, p_u, sev, lgd_l, lgd_u, lgd_m

    p24_l, p24_u, sev_24, lgd24_l, lgd24_u, lgd24_m = get_stats(o24, s24)
    p36_l, p36_u, sev_36, lgd36_l, lgd36_u, lgd36_m = get_stats(o36, s36)

    rows = [
        {
            "specification": "24-Month Follow-Up (Empirical Cohort)",
            "category": "Empirical Follow-Up",
            "horizon_months": 24,
            "p_liquidation_lower": p24_l,
            "p_liquidation_upper": p24_u,
            "severity": sev_24,
            "lgd_lower": lgd24_l,
            "lgd_upper": lgd24_u,
            "lgd_midpoint": lgd24_m,
            "base_lgd": lgd24_l,
            "tail_addon": 0.0,
            "modeled_lgd": lgd24_m,
            "notes": "Sensitivity cohort (<=201712 defaults); empirical loss severity 28.74%"
        },
        {
            "specification": "36-Month Follow-Up (Empirical Cohort)",
            "category": "Empirical Follow-Up",
            "horizon_months": 36,
            "p_liquidation_lower": p36_l,
            "p_liquidation_upper": p36_u,
            "severity": sev_36,
            "lgd_lower": lgd36_l,
            "lgd_upper": lgd36_u,
            "lgd_midpoint": lgd36_m,
            "base_lgd": 0.1150,
            "tail_addon": 0.0,
            "modeled_lgd": 0.1150,
            "notes": "Headline base cohort (<=201612 defaults); 11.50% base censor floor, 13.60% upper bound"
        },
        {
            "specification": "Pop 1 Headline (48m Re-default Tail)",
            "category": "Model Specification",
            "horizon_months": 48,
            "p_liquidation_lower": p36_l,
            "p_liquidation_upper": p36_u,
            "severity": sev_36,
            "lgd_lower": 0.1150,
            "lgd_upper": 0.1360,
            "lgd_midpoint": 0.1255,
            "base_lgd": 0.1150,
            "tail_addon": 0.0268,
            "modeled_lgd": PARAMS["lgd_p1_headline_48m"],
            "notes": "Headline provision basis: 11.50% base + 2.68% 48m chained re-default tail = 14.18%"
        },
        {
            "specification": "Pop 1 Sensitivity (36m Re-default Tail)",
            "category": "Model Specification",
            "horizon_months": 36,
            "p_liquidation_lower": p36_l,
            "p_liquidation_upper": p36_u,
            "severity": sev_36,
            "lgd_lower": 0.1150,
            "lgd_upper": 0.1360,
            "lgd_midpoint": 0.1255,
            "base_lgd": 0.1150,
            "tail_addon": 0.0250,
            "modeled_lgd": PARAMS["lgd_p1_sensitivity_36m"],
            "notes": "Sensitivity provision basis: 11.50% base + 2.50% 36m chained re-default tail = 14.00%"
        },
        {
            "specification": "Pop 1 Censor Upper Bound",
            "category": "Model Specification",
            "horizon_months": 48,
            "p_liquidation_lower": p36_l,
            "p_liquidation_upper": p36_u,
            "severity": sev_36,
            "lgd_lower": 0.1150,
            "lgd_upper": 0.1360,
            "lgd_midpoint": 0.1255,
            "base_lgd": 0.1360,
            "tail_addon": 0.0268,
            "modeled_lgd": PARAMS["lgd_p1_censor_upper"],
            "notes": "Upper bound sensitivity: 13.60% upper base + 2.68% tail = 16.28%"
        },
        {
            "specification": "Pop 2 Base LGD (No Tail)",
            "category": "Model Specification",
            "horizon_months": 36,
            "p_liquidation_lower": p36_l,
            "p_liquidation_upper": p36_u,
            "severity": sev_36,
            "lgd_lower": 0.1150,
            "lgd_upper": 0.1360,
            "lgd_midpoint": 0.1255,
            "base_lgd": PARAMS["lgd_p2_base"],
            "tail_addon": 0.0,
            "modeled_lgd": PARAMS["lgd_p2_base"],
            "notes": "Active modified loans: 11.50% base floor without tail to prevent double counting"
        },
        {
            "specification": "Pop 2 Upper Bound LGD",
            "category": "Model Specification",
            "horizon_months": 36,
            "p_liquidation_lower": p36_l,
            "p_liquidation_upper": p36_u,
            "severity": sev_36,
            "lgd_lower": 0.1150,
            "lgd_upper": 0.1360,
            "lgd_midpoint": 0.1255,
            "base_lgd": PARAMS["lgd_p2_upper"],
            "tail_addon": 0.0,
            "modeled_lgd": PARAMS["lgd_p2_upper"],
            "notes": "Active modified upper bound: 13.60% censor upper limit"
        },
        {
            "specification": "Pop 3 Active Default (Headline)",
            "category": "Model Specification",
            "horizon_months": 48,
            "p_liquidation_lower": p36_l,
            "p_liquidation_upper": p36_u,
            "severity": sev_36,
            "lgd_lower": 0.1150,
            "lgd_upper": 0.1360,
            "lgd_midpoint": 0.1255,
            "base_lgd": PARAMS["lgd_p3_headline"],
            "tail_addon": 0.0,
            "modeled_lgd": PARAMS["lgd_p3_headline"],
            "notes": "Matches Pop 1 headline LGD 14.18% applied to 100% default PD"
        },
        {
            "specification": "Pop 3 Active Default (Upper Bound)",
            "category": "Model Specification",
            "horizon_months": 48,
            "p_liquidation_lower": p36_l,
            "p_liquidation_upper": p36_u,
            "severity": sev_36,
            "lgd_lower": 0.1150,
            "lgd_upper": 0.1360,
            "lgd_midpoint": 0.1255,
            "base_lgd": PARAMS["lgd_p3_upper"],
            "tail_addon": 0.0,
            "modeled_lgd": PARAMS["lgd_p3_upper"],
            "notes": "Matches Pop 1 upper bound LGD 16.28%"
        }
    ]

    df_lgd = pd.DataFrame(rows)
    out_csv = os.path.join(OUTPUT_DIR, "lgd_bounds.csv")
    df_lgd.to_csv(out_csv, index=False)
    return df_lgd, len(df_lgd)

def export_clean_default_rate_by_year(con):
    """
    Exports clean_default_rate_by_year.csv with Pop 1 Clean default rates by age bucket and year.
    """
    init_backtest_tables(con)
    q_age = """
    WITH snaps AS (
        SELECT 201412 as snap, 201501 as st, 201512 as ed, 2015 as yr
        UNION ALL SELECT 201512, 201601, 201612, 2016
        UNION ALL SELECT 201612, 201701, 201712, 2017
        UNION ALL SELECT 201712, 201801, 201812, 2018
        UNION ALL SELECT 201812, 201901, 201912, 2019
    ),
    active AS (
        SELECT 
            s.yr,
            s.snap,
            s.st,
            s.ed,
            c.loan_id,
            c.loan_age,
            CASE 
                WHEN c.loan_age <= 12 THEN '01-12m'
                WHEN c.loan_age <= 24 THEN '13-24m'
                WHEN c.loan_age <= 36 THEN '25-36m'
                WHEN c.loan_age <= 48 THEN '37-48m'
                WHEN c.loan_age <= 60 THEN '49-60m'
                WHEN c.loan_age <= 84 THEN '61-84m'
                ELSE '85m+'
            END as age_bucket
        FROM snaps s
        JOIN clean_monthly_performance c 
          ON c.monthly_reporting_period = s.snap 
         AND c.loan_state = 'Current' 
         AND c.zero_balance_code IS NULL
        LEFT JOIN p2_first p ON c.loan_id = p.loan_id
        WHERE (p.min_p2_period IS NULL OR p.min_p2_period > s.snap)
          AND NOT EXISTS (
              SELECT 1 FROM clean_monthly_performance h
              WHERE h.loan_id = c.loan_id 
                AND h.monthly_reporting_period BETWEEN s.snap - 99 AND s.snap
                AND h.loan_state IN ('30_DPD', '60_DPD')
          )
    ),
    defs AS (
        SELECT 
            a.yr,
            a.snap,
            a.age_bucket,
            a.loan_id,
            MAX(CASE WHEN p.loan_state = 'Default' THEN 1 ELSE 0 END) as defaulted
        FROM active a
        LEFT JOIN clean_monthly_performance p 
          ON a.loan_id = p.loan_id AND p.monthly_reporting_period BETWEEN a.st AND a.ed
        GROUP BY a.yr, a.snap, a.age_bucket, a.loan_id
    )
    SELECT 
        yr as eval_year,
        snap as snapshot,
        age_bucket,
        COUNT(*) as active_loans,
        SUM(defaulted) as defaults,
        ROUND(SUM(defaulted) * 100.0 / COUNT(*), 4) as default_rate_pct
    FROM defs
    GROUP BY yr, snap, age_bucket
    ORDER BY yr, age_bucket;
    """
    df_clean_age = con.execute(q_age).df()
    out_csv = os.path.join(OUTPUT_DIR, "clean_default_rate_by_year.csv")
    df_clean_age.to_csv(out_csv, index=False)
    return df_clean_age, len(df_clean_age)

def run_export():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    con = duckdb.connect("mortgage_risk.duckdb", read_only=True)

    print("=========================================================================================================")
    print("                              EXPORTING TABLEAU CSV AGGREGATES FROM DUCKDB                               ")
    print("=========================================================================================================\n")

    # 1. ECL Master
    df_master, n_master, check_master = export_ecl_master(con)
    tot_ecl, tot_loans, tot_upb = check_master
    print(f"1. ecl_master.csv:                {n_master:>5} rows exported.")
    print(f"   [Reconciliation Check PASSED]: Total ECL = ${tot_ecl:,.2f}, Loans = {tot_loans:,}, UPB = ${tot_upb:,.2f}")

    # 2. ECL Scenarios
    _, n_scen = export_ecl_scenarios(df_master, con)
    print(f"2. ecl_scenarios.csv:             {n_scen:>5} rows exported.")

    # 3. Vintage Curves
    _, n_vc = export_vintage_curves(con)
    print(f"3. vintage_curves.csv:            {n_vc:>5} rows exported.")

    # 4. Transition Matrix FICO
    _, n_trans = export_transition_matrix_fico(con)
    print(f"4. transition_matrix_fico.csv:    {n_trans:>5} rows exported.")

    # 5. Backtest Rolling
    _, n_bt, _ = export_backtest_rolling(con)
    print(f"5. backtest_rolling.csv:          {n_bt:>5} rows exported.")
    print("   [Reconciliation Check PASSED]: Backtest totals exactly tie out to docs/progress_report.md for all 4 snapshots.")

    # 6. LGD Bounds
    _, n_lgd = export_lgd_bounds(con)
    print(f"6. lgd_bounds.csv:                {n_lgd:>5} rows exported.")

    # 7. Clean Default Rate by Year
    _, n_clean = export_clean_default_rate_by_year(con)
    print(f"7. clean_default_rate_by_year.csv:{n_clean:>5} rows exported.")

    print("\n=========================================================================================================")
    print("                            ALL 7 TABLEAU AGGREGATE CSVS GENERATED & RECONCILED                          ")
    print("=========================================================================================================\n")

if __name__ == "__main__":
    run_export()
