import duckdb
from src.layers import build_layer1_clean_performance, build_layer2_truncated_performance, build_layer3_transitions, build_ecl_snapshot
from src.lgd import build_lgd_views

con = duckdb.connect('mortgage_risk.duckdb')

def print_buckets(mod_policy):
    print(f"\n================ POLICY: {mod_policy.upper()} ================")
    build_layer1_clean_performance(con, mod_policy=mod_policy)
    build_layer2_truncated_performance(con)
    build_lgd_views(con)
    for hz in ['24m', '36m']:
        print(f"\n[{hz} Buckets]")
        print(con.execute(f"""
            SELECT o.outcome, COUNT(*) as count, SUM(u.default_upb) as dol
            FROM v_default_outcomes_{hz} o
            INNER JOIN v_first_default_upb u ON o.loan_id = u.loan_id
            GROUP BY o.outcome
        """).df())

print_buckets('purge')
print_buckets('censor')
