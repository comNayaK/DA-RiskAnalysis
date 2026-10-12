import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import duckdb
con = duckdb.connect('mortgage_risk.duckdb', read_only=True)
from scratch.regenerate_grid import load_ecl_snapshot_segments, PARAMS

df_snap = load_ecl_snapshot_segments(con)
base_ecl = 45073223.87

def calc_ecl(pd_override_dict, lgd_p1=PARAMS["lgd_p1_headline_48m"], lgd_p2=PARAMS["lgd_p2_base"], lgd_p3=PARAMS["lgd_p3_headline"]):
    tot = 0
    details = {}
    for _, r in df_snap.iterrows():
        seg = r["segment"]
        upb = r["total_upb"]
        pd_val = pd_override_dict[seg]
        lgd_val = lgd_p2 if seg.startswith("Pop 2") else (lgd_p3 if seg.startswith("Pop 3") else lgd_p1)
        e = upb * pd_val * lgd_val
        details[seg] = e
        tot += e
    return tot, details

pd_base = {
    'Pop 1: Current (Clean)': 0.001560,
    'Pop 1: Current (Probation)': 0.095100,
    'Pop 1: 30_DPD': 0.156800,
    'Pop 1: 60_DPD': 0.601000,
    'Pop 2: Current': 0.122400,
    'Pop 2: Modified (Clean)': 0.104800,
    'Pop 2: 30_DPD': 0.515000,
    'Pop 2: 60_DPD': 0.794900,
    'Pop 3: Active Default': 1.000000
}

# 1. Strict Clean Only (313/206839 = 0.001513254)
pd_sc = pd_base.copy()
pd_sc['Pop 1: Current (Clean)'] = 313.0 / 206839.0
tot_sc, det_sc = calc_ecl(pd_sc)

# 2. Measured Trailing Pop 2 Only (201812 snapshot, evaluated from 201712 -> 2018):
pd_tr_only = pd_base.copy()
pd_tr_only['Pop 2: Current'] = 36.0 / 423.0            # 8.5106% vs 12.24%
pd_tr_only['Pop 2: 30_DPD'] = 25.0 / 87.0             # 28.7356% vs 51.50%
pd_tr_only['Pop 2: 60_DPD'] = 49.0 / 76.0             # 64.4737% vs 79.49%
pd_tr_only['Pop 2: Modified (Clean)'] = 91.0 / 740.0   # 12.2973% vs 10.48%
tot_tr_only, det_tr_only = calc_ecl(pd_tr_only)

# 3. Measured Trailing Pop 2 + Strict Clean
pd_tr = pd_sc.copy()
pd_tr['Pop 2: Current'] = 36.0 / 423.0
pd_tr['Pop 2: 30_DPD'] = 25.0 / 87.0
pd_tr['Pop 2: 60_DPD'] = 49.0 / 76.0
pd_tr['Pop 2: Modified (Clean)'] = 91.0 / 740.0
tot_tr, det_tr = calc_ecl(pd_tr)

# 4. Measured Pooled Pop 2 + Strict Clean (<= 201712 outcomes)
pd_pool = pd_sc.copy()
pd_pool['Pop 2: Current'] = 141.0 / 1396.0          # 10.1003%
pd_pool['Pop 2: 30_DPD'] = 105.0 / 306.0            # 34.3137%
pd_pool['Pop 2: 60_DPD'] = 138.0 / 213.0            # 64.7887%
pd_pool['Pop 2: Modified (Clean)'] = 321.0 / 2199.0 # 14.5975%
tot_pool, det_pool = calc_ecl(pd_pool)

print(f"Headline v0.1 ECL:                      ${base_ecl:12,.2f}")
print(f"1. Strict Clean Only (0.1513%):         ${tot_sc:12,.2f} | Delta: -${base_ecl - tot_sc:10,.2f} (-{(base_ecl - tot_sc)/base_ecl*100:5.2f}%)")
print(f"2. Measured Trailing Pop 2 Only:        ${tot_tr_only:12,.2f} | Delta: -${base_ecl - tot_tr_only:10,.2f} (-{(base_ecl - tot_tr_only)/base_ecl*100:5.2f}%)")
print(f"3. Measured Trailing Pop 2 + Str Clean: ${tot_tr:12,.2f} | Delta: -${base_ecl - tot_tr:10,.2f} (-{(base_ecl - tot_tr)/base_ecl*100:5.2f}%)")
print(f"4. Measured Pooled Pop 2 + Str Clean:   ${tot_pool:12,.2f} | Delta: +${tot_pool - base_ecl:10,.2f} (+{(tot_pool - base_ecl)/base_ecl*100:5.2f}%)")
