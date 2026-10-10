import duckdb
import pandas as pd
import numpy as np
import math
import statsmodels.api as sm
import statsmodels.formula.api as smf
import sys, os
sys.path.append(os.getcwd())

con = duckdb.connect('mortgage_risk.duckdb')
from src.lgd import get_horizon_stats

print("\n" + "="*80)
print("(3) Recompute Purge LGD (Multi-Vintage), 24m/36m buckets/bounds")
print("="*80)
def do_lgd(h):
    lgd_l, lgd_u, lgd_m, p_l, p_u, sev, ci_l, ci_u, ci_s, dir_c, p_ex_l, p_ex_u = get_horizon_stats(h)
    print(f"LGD {h}:")
    print(f"  P(Liq) [Censor, includes Mods] = [{p_l:.4f}, {p_u:.4f}]")
    print(f"  P(Liq) [Purge, excludes Mods]  = [{p_ex_l:.4f}, {p_ex_u:.4f}]")
    print(f"  Severity = {sev:.4f} (±{ci_s:.4f})")
    print(f"  Purge LGD Bounds = [{p_ex_l*sev:.4f}, {p_ex_u*sev:.4f}] (Midpoint: {(p_ex_l*sev + p_ex_u*sev)/2:.4f})")

do_lgd("24m")
print("")
do_lgd("36m")
