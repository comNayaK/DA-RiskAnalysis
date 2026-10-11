import pandas as pd
import numpy as np

# Script to rigorously regenerate all scenario grid rows and master table from code

# Segments and UPBs at 201912:
segments = [
    # name, stage, loans, upb, base_pd, prob_pd_ex_hurr, prob_pd_all, p1_30_pd, p1_60_pd, p2_curr_pd, p2_mod_pd, p2_30_pd, p2_60_pd, p3_pd
    ("Pop 1: Current (Clean)", "Stage 1", 166009, 27336521222.18),
    ("Pop 1: Current (Probation)", "Stage 2", 4314, 699337238.97),
    ("Pop 1: 30_DPD", "Stage 2", 1135, 189879874.19),
    ("Pop 1: 60_DPD", "Stage 2", 189, 30997278.97),
    ("Pop 2: Current", "Stage 2", 675, 101614965.47),
    ("Pop 2: Modified (Clean)", "Stage 2", 1069, 201229039.43),
    ("Pop 2: 30_DPD", "Stage 2", 134, 19034568.03),
    ("Pop 2: 60_DPD", "Stage 2", 86, 12261970.10),
    ("Pop 3: Active Default", "Stage 3", 682, 117265323.23)
]

# Baseline PDs
pds_headline = {
    "Pop 1: Current (Clean)": 0.001560,       # 0.1560% clean-history
    "Pop 1: Current (Probation)": 0.095100,   # 9.510% ex-hurricane probation
    "Pop 1: 30_DPD": 0.156800,               # 15.680% calibrated lifetime
    "Pop 1: 60_DPD": 0.601000,               # 60.100% calibrated lifetime
    "Pop 2: Current": 0.122400,              # 12.240% proxy lifetime
    "Pop 2: Modified (Clean)": 0.104800,     # 10.480% 12m hazard floor
    "Pop 2: 30_DPD": 0.515000,               # 51.500% pooled historical
    "Pop 2: 60_DPD": 0.794900,               # 79.490% pooled historical
    "Pop 3: Active Default": 1.000000        # 100% default
}

# LGDs:
# 48m Tail Pop 1: 14.18% (11.5% + 2.68%)
# 36m Tail Pop 1: 14.00% (11.5% + 2.50%)
# Pop 2 Base: 11.50%
# Pop 3: equals Pop 1 LGD

def calc_ecl(pds, lgd_p1, lgd_p2, lgd_p3):
    total = 0
    details = {}
    for seg, stg, cnt, upb in segments:
        pd_val = pds[seg]
        lgd_val = lgd_p2 if seg.startswith("Pop 2") else (lgd_p3 if seg.startswith("Pop 3") else lgd_p1)
        ecl = upb * pd_val * lgd_val
        details[seg] = ecl
        total += ecl
    return total, details

# 1. Headline Scenario (48m Tail, 0.1560% clean, 9.51% probation, 10.48% mod floor)
tot_headline, det_headline = calc_ecl(pds_headline, 0.1418, 0.1150, 0.1418)
print(f"1. Headline Scenario (48m Tail, 14.18% LGD): ${tot_headline:,.2f}")
for s, v in det_headline.items():
    print(f"   {s:<27}: ${v:>12,.2f} ({v/tot_headline*100:5.2f}%)")

pop2_tot = sum(v for s, v in det_headline.items() if s.startswith("Pop 2"))
print(f"   Pop 2 Total: ${pop2_tot:,.2f} ({pop2_tot/tot_headline*100:.2f}%)")

# 2. 36m Tail Scenario (14.00% Pop 1 LGD, 11.50% Pop 2, 14.00% Pop 3)
tot_36m, det_36m = calc_ecl(pds_headline, 0.1400, 0.1150, 0.1400)
print(f"\n2. 36m Tail Scenario (14.00% LGD): ${tot_36m:,.2f}")

# 3. Calibrated Baseline (No Probation: all Current @ 0.1560%):
pds_no_prob = pds_headline.copy()
pds_no_prob["Pop 1: Current (Probation)"] = 0.001560
tot_cal_base, det_cal_base = calc_ecl(pds_no_prob, 0.1418, 0.1150, 0.1418)
print(f"\n3. Calibrated Baseline (No Probation @ 0.1560%): ${tot_cal_base:,.2f}")

# 4. Uncalibrated Direct Baseline (No Probation: all Current @ 0.2180%):
pds_uncal = pds_no_prob.copy()
pds_uncal["Pop 1: Current (Clean)"] = 0.002180
pds_uncal["Pop 1: Current (Probation)"] = 0.002180
tot_uncal_base, det_uncal_base = calc_ecl(pds_uncal, 0.1418, 0.1150, 0.1418)
print(f"\n4. Uncalibrated Baseline (No Probation @ 0.2180%): ${tot_uncal_base:,.2f}")

# 5. Purge Baseline (Legacy):
# All LGDs = 16.70%, Current @ 0.2554%, 30 DPD @ 12.24%, 60 DPD @ 52.59%
pds_purge = {
    "Pop 1: Current (Clean)": 0.002554,
    "Pop 1: Current (Probation)": 0.002554,
    "Pop 1: 30_DPD": 0.1224,
    "Pop 1: 60_DPD": 0.5259,
    "Pop 2: Current": 0.1224,
    "Pop 2: Modified (Clean)": 0.1224,
    "Pop 2: 30_DPD": 0.1224,
    "Pop 2: 60_DPD": 0.5259,
    "Pop 3: Active Default": 1.0000
}
tot_purge, _ = calc_ecl(pds_purge, 0.1670, 0.1670, 0.1670)
print(f"\n5. Purge Baseline (Legacy @ 16.70% LGD): ${tot_purge:,.2f}")

# 6. Alternative Cohort (4,606 probation loans, 165,717 clean loans):
# Clean UPB: $27,293,055,342.19, Probation UPB: $742,803,118.96
ecl_clean_alt = 27293055342.19 * 0.001560 * 0.1418
ecl_prob_alt = 742803118.96 * 0.095100 * 0.1418
tot_alt = (tot_headline - det_headline["Pop 1: Current (Clean)"] - det_headline["Pop 1: Current (Probation)"]) + ecl_clean_alt + ecl_prob_alt
print(f"\n6. Alternative Cohort (4,606 Probation Loans): ${tot_alt:,.2f}")

# 7. Censor Upper Bound:
# Variant A: 16.21% Pop 1 (13.60% + 2.61% tail), 13.60% Pop 2, 16.21% Pop 3
tot_upper, det_upper = calc_ecl(pds_headline, 0.1621, 0.1360, 0.1621)
print(f"\n7a. Censor Upper Bound (16.21% Pop 1 / 13.60% Pop 2): ${tot_upper:,.2f}")

# Variant B: 16.28% Pop 1 (13.60% + 2.68% 48m tail), 13.60% Pop 2, 16.28% Pop 3
tot_upper_1628, _ = calc_ecl(pds_headline, 0.1628, 0.1360, 0.1628)
print(f"7b. Censor Upper Bound (16.28% Pop 1 48m Tail / 13.60% Pop 2): ${tot_upper_1628:,.2f}")

# 8. Regime-Calibrated Scenario (scaling non-Stage-3 by 0.88):
ecl_s3 = det_headline["Pop 3: Active Default"]
ecl_non_s3 = tot_headline - ecl_s3
tot_regime = (ecl_non_s3 * 0.88) + ecl_s3
print(f"\n8. Regime-Calibrated Scenario (0.88 Scale): ${tot_regime:,.2f}")

print("\n=== SUMMARY SCENARIO GRID ===")
print(f"Purge Baseline:                  ${tot_purge:,.2f}")
print(f"Calibrated Base (No Probation):  ${tot_cal_base:,.2f} (Delta vs Purge: +${tot_cal_base - tot_purge:,.2f})")
print(f"Uncalibrated Base (No Probation):${tot_uncal_base:,.2f} (Delta vs Purge: +${tot_uncal_base - tot_purge:,.2f})")
print(f"36m Tail Scenario (14.00% LGD):  ${tot_36m:,.2f} (Delta vs Cal Base: +${tot_36m - tot_cal_base:,.2f})")
print(f"Headline Scenario (14.18% LGD):  ${tot_headline:,.2f} (Delta vs Cal Base: +${tot_headline - tot_cal_base:,.2f})")
print(f"Alternative Cohort (4,606):      ${tot_alt:,.2f} (Delta vs Cal Base: +${tot_alt - tot_cal_base:,.2f})")
print(f"Censor Upper Bound (16.21% LGD): ${tot_upper:,.2f} (Delta vs Cal Base: +${tot_upper - tot_cal_base:,.2f})")
print(f"Censor Upper Bound (16.28% LGD): ${tot_upper_1628:,.2f} (Delta vs Cal Base: +${tot_upper_1628 - tot_cal_base:,.2f})")
print(f"Regime-Calibrated Scenario:      ${tot_regime:,.2f}")
