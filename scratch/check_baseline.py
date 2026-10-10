import duckdb
from src.layers import build_layer1_clean_performance, build_layer2_truncated_performance, build_layer3_transitions, build_ecl_snapshot
from src.lgd import build_lgd_views, compute_lgd_bounds
from src.markov import compute_fico_segmented_ecl

con = duckdb.connect('mortgage_risk.duckdb')

# Use PURGE
build_layer1_clean_performance(con, mod_policy='purge')
build_layer2_truncated_performance(con)
build_layer3_transitions(con)
build_ecl_snapshot(con)
build_lgd_views(con)

l36, u36, m36 = compute_lgd_bounds(con)
print(f"Purge LGD 36m Midpoint: {m36:.4f}")

snapshot, pds, c_port = compute_fico_segmented_ecl(con, m36)
print(f"Purge Baseline ECL: ${snapshot['ecl'].sum():,.2f}")
