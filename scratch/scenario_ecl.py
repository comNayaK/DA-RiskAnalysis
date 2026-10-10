import duckdb
import pandas as pd
import numpy as np

con = duckdb.connect('mortgage_risk.duckdb')
con.execute("""
CREATE OR REPLACE MACRO month_idx(yyyymm) AS 
CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 1, 4) AS INT) * 12 + CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 5, 2) AS INT);
""")

from src.layers import build_layer1_clean_performance, build_layer2_truncated_performance, build_layer3_transitions, build_ecl_snapshot
from src.lgd import build_lgd_views, compute_lgd_bounds
from src.markov import counts_df_to_array, build_markov_matrices, compute_fico_segmented_ecl

def get_base_pd(mod_policy):
    build_layer1_clean_performance(con, mod_policy=mod_policy)
    build_layer2_truncated_performance(con, mod_policy=mod_policy)
    build_layer3_transitions(con)
    df_port = con.execute("SELECT state_t, state_t_plus_1, COUNT(*) as n FROM loan_level_transitions WHERE monthly_reporting_period <= 202002 GROUP BY 1,2").df()
    C = counts_df_to_array(df_port)
    Q, R, _, _, _ = build_markov_matrices(C)
    
    # Also get FICO segmented PDs for ECL calculation
    snapshot, pds, c_port = compute_fico_segmented_ecl(con, 0.1) # dummy LGD
    return pds

def get_lgd(policy):
    build_layer1_clean_performance(con, mod_policy=policy)
    build_lgd_views(con)
    l36, u36, m36 = compute_lgd_bounds(con)
    return m36

print("--- Computing Base PDs ---")
pds_purge = get_base_pd('purge')
pds_censor = get_base_pd('censor')

print("--- Computing LGDs ---")
lgd_purge = get_lgd('purge')
lgd_censor = get_lgd('censor')
lgd_keep = get_lgd('keep')

print("\nLGD Scenario Table (Midpoints 36m):")
print(f"Purge  (Exclude Mod): 36m={lgd_purge:.4f}")
print(f"Censor (Assume $0)  : 36m={lgd_censor:.4f}")
print(f"Keep   (Empirical)  : 36m={lgd_keep:.4f}")

# Backtest base models on Pop1
print("\n--- Backtest Base Models on Pop1 ---")
# Pop1 = never modified, never defaulted prior to 201812
q_oos = """
SELECT 
    s.loan_id, p.loan_state, o.credit_score,
    (SELECT COUNT(*) FROM clean_monthly_performance d 
     WHERE d.loan_id = s.loan_id AND d.loan_state = 'Default' 
       AND d.monthly_reporting_period BETWEEN 201901 AND 201912) > 0 as actual_default
FROM oos_snapshot_201812 s
INNER JOIN clean_monthly_performance p ON s.loan_id = p.loan_id AND p.monthly_reporting_period = 201812
INNER JOIN raw_origination o ON s.loan_id = o.loan_id
LEFT JOIN (SELECT loan_id, MIN(CAST(monthly_reporting_period AS INT)) as mod_period FROM raw_performance WHERE COALESCE(modification_flag, '') IN ('Y', 'P') GROUP BY loan_id) m ON s.loan_id = m.loan_id
LEFT JOIN (SELECT loan_id, MIN(monthly_reporting_period) as def_period FROM clean_monthly_performance WHERE loan_state = 'Default' GROUP BY loan_id) d ON s.loan_id = d.loan_id
WHERE (m.mod_period IS NULL OR m.mod_period > 201812)
  AND (d.def_period IS NULL OR d.def_period > 201812)
"""
build_layer1_clean_performance(con, mod_policy='keep')
df_pop1 = con.execute(q_oos).df()

def apply_pd(row, pds_dict):
    cs = row['credit_score']
    if pd.isna(cs): band = 'Unknown'
    else:
        try:
            cs = int(cs)
            if cs == 9999: band = 'Unknown'
            elif cs >= 740: band = 'High-FICO'
            elif cs >= 680: band = 'Mid-FICO'
            else: band = 'Lower-FICO'
        except:
            band = 'Unknown'
    
    st = row['loan_state']
    if st == 'Current': return pds_dict[band]['pd_12m']
    elif st == '30_DPD': return pds_dict[band]['pd_lifetime_30dpd']
    elif st == '60_DPD': return pds_dict[band]['pd_lifetime_60dpd']
    return pds_dict[band]['pd_12m']

for name, pd_dict in [('Purge Matrix', pds_purge), ('Censor Matrix', pds_censor)]:
    exp = df_pop1.apply(lambda r: apply_pd(r, pd_dict), axis=1).sum()
    act = df_pop1['actual_default'].sum()
    z = (act - exp) / np.sqrt(exp)
    print(f"{name} -> Expected: {exp:.1f}, Actual: {act}, Z: {z:.2f}")

