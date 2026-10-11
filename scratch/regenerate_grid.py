import pandas as pd
import numpy as np

# Script to rigorously regenerate all scenario grid rows and master table from code

# Segments and UPBs at 201912:
segments = [
    # name, stage, loans, upb
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

# LGD parameters:
# 48m Headline Pop 1: 14.18% (11.50% base + 2.68% tail)
# 36m Sensitivity Pop 1: 14.00% (11.50% base + 2.50% tail)
# Censor Upper Pop 1: 16.28% (13.60% upper base + 2.68% tail)
# Pop 2 Base: 11.50%
# Pop 2 Upper: 13.60%
# Pop 3 equals Pop 1 LGD

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

# 1. Calibrated Reference Baseline (No Probation: all Current @ 0.1560% Clean PD, 14.18% LGD)
pds_no_prob = pds_headline.copy()
pds_no_prob["Pop 1: Current (Probation)"] = 0.001560
tot_cal_base, det_cal_base = calc_ecl(pds_no_prob, 0.1418, 0.1150, 0.1418)

# 2. Uncalibrated Baseline (No Probation: all Current @ 0.2180% Unsegmented PD, 14.18% LGD)
pds_uncal = pds_no_prob.copy()
pds_uncal["Pop 1: Current (Clean)"] = 0.002180
pds_uncal["Pop 1: Current (Probation)"] = 0.002180
tot_uncal_base, det_uncal_base = calc_ecl(pds_uncal, 0.1418, 0.1150, 0.1418)

# 3. 36m Tail Sensitivity (14.00% Pop 1 LGD, 9.510% Probation PD)
tot_36m, det_36m = calc_ecl(pds_headline, 0.1400, 0.1150, 0.1400)

# 4. Headline Scenario (48m Tail, 14.18% Pop 1 LGD, 9.510% Probation PD, 10.48% Pop 2 Mod Floor)
tot_headline, det_headline = calc_ecl(pds_headline, 0.1418, 0.1150, 0.1418)

# 5. Alternative Cohort (4,606 probation loans, 165,717 clean loans @ 14.18% LGD)
ecl_clean_alt = 27293055342.19 * 0.001560 * 0.1418
ecl_prob_alt = 742803118.96 * 0.095100 * 0.1418
tot_alt = (tot_headline - det_headline["Pop 1: Current (Clean)"] - det_headline["Pop 1: Current (Probation)"]) + ecl_clean_alt + ecl_prob_alt

# 6. Censor Upper Bound (16.28% Pop 1 / 13.60% Pop 2 LGD)
tot_upper, det_upper = calc_ecl(pds_headline, 0.1628, 0.1360, 0.1628)

# 7. Regime-Calibrated Scenario (scaling non-Stage-3 provisions by 0.88)
ecl_s3 = det_headline["Pop 3: Active Default"]
ecl_non_s3 = tot_headline - ecl_s3
tot_regime = (ecl_non_s3 * 0.88) + ecl_s3

print("=== REGENERATED SCENARIO GRID (Code Output) ===")
print(f"1. Calibrated Base (No Probation):  ${tot_cal_base:>12,.2f} | Reference Baseline")
print(f"2. Uncalibrated Base (No Probation):${tot_uncal_base:>12,.2f} | Delta vs Cal Base: +${tot_uncal_base - tot_cal_base:>10,.2f} (+{(tot_uncal_base - tot_cal_base)/tot_cal_base*100:5.2f}%)")
print(f"3. 36m Tail Sensitivity (14.00%):   ${tot_36m:>12,.2f} | Delta vs Cal Base: +${tot_36m - tot_cal_base:>10,.2f} (+{(tot_36m - tot_cal_base)/tot_cal_base*100:5.2f}%)")
print(f"4. HEADLINE SCENARIO (48m Tail):    ${tot_headline:>12,.2f} | Delta vs Cal Base: +${tot_headline - tot_cal_base:>10,.2f} (+{(tot_headline - tot_cal_base)/tot_cal_base*100:5.2f}%)")
print(f"5. Alternative Cohort (4,606):      ${tot_alt:>12,.2f} | Delta vs Cal Base: +${tot_alt - tot_cal_base:>10,.2f} (+{(tot_alt - tot_cal_base)/tot_cal_base*100:5.2f}%)")
print(f"6. Censor Upper Bound (16.28% LGD): ${tot_upper:>12,.2f} | Delta vs Cal Base: +${tot_upper - tot_cal_base:>10,.2f} (+{(tot_upper - tot_cal_base)/tot_cal_base*100:5.2f}%)")
print(f"7. Regime-Calibrated (0.88x non-S3):${tot_regime:>12,.2f} | Delta vs Headline: -${tot_headline - tot_regime:>10,.2f} (-{(tot_headline - tot_regime)/tot_headline*100:5.2f}%)")
