import duckdb
import pandas as pd
import numpy as np

def build_grid():
    con = duckdb.connect('mortgage_risk.duckdb')
    con.execute("CREATE OR REPLACE MACRO month_idx(yyyymm) AS CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 1, 4) AS INT) * 12 + CAST(SUBSTRING(CAST(yyyymm AS VARCHAR), 5, 2) AS INT);")
    
    # 1. 48+ age bucket diagnostic
    print("--- 1. Age Bucket Diagnostic (including 48+) ---")
    con.execute("""
    CREATE OR REPLACE VIEW v_age_buckets AS
    SELECT 
        CASE 
            WHEN loan_age < 12 THEN 0 
            WHEN loan_age < 24 THEN 12 
            WHEN loan_age < 36 THEN 24 
            WHEN loan_age < 48 THEN 36 
            ELSE 48 
        END as age_bucket,
        COUNT(*) as obs_count,
        SUM(CASE WHEN loan_state = 'Default' THEN 1 ELSE 0 END) as default_count
    FROM truncated_performance
    WHERE monthly_reporting_period <= 201812
    GROUP BY age_bucket ORDER BY age_bucket;
    """)
    df_age = con.execute("SELECT *, default_count * 1.0 / obs_count as pd_12m FROM v_age_buckets").df()
    print(df_age.to_string())

    # 2. Get matrix parameters for Purge and Censor
    # To do Purge vs Censor, we can just look at loan_level_transitions vs loan_level_transitions_censor
    # Wait, the pipeline only builds one matrix using `truncated_performance`.
    # Let's just create a `P_base_purge` and `P_base_censor` manually if needed, 
    # but the user said "The PD matrix (purge/censor)...". 
    # The current pipeline uses `truncated_performance` which truncates AFTER modification. That is "Censor"!
    # "Purge" means we delete the entire loan if it ever modifies.
    con.execute("""
    CREATE OR REPLACE TABLE loan_level_transitions_purge AS
    SELECT * FROM loan_level_transitions
    WHERE loan_id NOT IN (
        SELECT loan_id FROM clean_monthly_performance WHERE loan_state = 'Modified'
    );
    """)
    
    def get_matrices(table_name):
        df_port_train = con.execute(f"SELECT state_t, state_t_plus_1, COUNT(*) as n FROM {table_name} WHERE monthly_reporting_period <= 201812 GROUP BY 1,2").df()
        states_order = ['Current', '30_DPD', '60_DPD', 'Default', 'Paid_Off', 'Admin_Removal', 'Modified']
        state_to_idx = {s: i for i, s in enumerate(states_order)}
        C_train = np.zeros((len(states_order), len(states_order)))
        for _, r in df_port_train.iterrows():
            s_t = r['state_t']
            s_next = r['state_t_plus_1']
            if s_t in state_to_idx and s_next in state_to_idx:
                C_train[state_to_idx[s_t], state_to_idx[s_next]] += r['n']
        
        transient = [0, 1, 2]
        absorbing = [3, 4, 5, 6]
        Q_train = np.zeros((3, 3))
        R_train = np.zeros((3, 4))
        for i in range(3):
            row_sum = C_train[i].sum()
            if row_sum > 0:
                for j in range(3):
                    Q_train[i, j] = C_train[i, j] / row_sum
                for j, a_idx in enumerate(absorbing):
                    R_train[i, j] = C_train[i, a_idx] / row_sum
                    
        P_12 = np.zeros((3, 4))
        for t in range(12):
            P_12 += np.linalg.matrix_power(Q_train, t) @ R_train
            
        I = np.eye(3)
        P_life = np.linalg.inv(I - Q_train) @ R_train
        return P_12, P_life
        
    P_12_censor, P_life_censor = get_matrices('loan_level_transitions')
    P_12_purge, P_life_purge = get_matrices('loan_level_transitions_purge')
    
    # Grid computation...
    # We will compute the total ECL on the snapshot.
    # Snapshot:
    q_ecl = """
    WITH snap_events AS (
        SELECT loan_id, MAX(event_date) as last_event_date, MAX(event_type) as last_event_type
        FROM event_tracking e
        WHERE event_date <= 201912
        GROUP BY loan_id
    )
    SELECT 
        s.loan_id, s.loan_state, s.snapshot_upb,
        se.last_event_type as event_type, 
        month_idx(201912) - month_idx(se.last_event_date) as months_since_event
    FROM ecl_snapshot s
    LEFT JOIN snap_events se ON s.loan_id = se.loan_id
    """
    df_ecl = con.execute(q_ecl).df()
    
    # Calibrated Stage 1 PD
    STAGE_1_PD_CALIBRATED = 0.00283
    
    # 3. Calculate grids
    results = []
    
    # To simplify hazard, I will use flat values for pooled/conditional just to demonstrate total ECL variation.
    # For a real implementation, I'd query haz_cure etc. Let's just fetch pooled mod hazard.
    haz_pooled = 0.3204
    # For conditional, we can just use 0.28 on average for simplicity, or actually fetch it...
    # I will fetch it properly.
    df_haz = con.execute("""
    WITH first_events AS (
        SELECT loan_id, MIN(event_date) as event_date, MAX(event_type) as event_type
        FROM event_tracking
        GROUP BY loan_id
    ),
    survived_t AS (
        SELECT s.loan_id, s.event_type, s.event_date, t.t_months
        FROM first_events s
        CROSS JOIN (SELECT UNNEST(GENERATE_SERIES(0, 48)) as t_months) t
        WHERE s.event_date <= 201812
          AND month_idx(s.event_date) + t.t_months <= month_idx(201812)
          AND NOT EXISTS (
              SELECT 1 FROM clean_monthly_performance p
              WHERE p.loan_id = s.loan_id
                AND p.loan_state = 'Default'
                AND month_idx(p.monthly_reporting_period) > month_idx(s.event_date)
                AND month_idx(p.monthly_reporting_period) <= month_idx(s.event_date) + t.t_months
          )
    ),
    defaulted_next_12 AS (
        SELECT s.loan_id, s.t_months
        FROM survived_t s
        WHERE EXISTS (
            SELECT 1 FROM clean_monthly_performance p
            WHERE p.loan_id = s.loan_id
              AND p.loan_state = 'Default'
              AND month_idx(p.monthly_reporting_period) > month_idx(s.event_date) + s.t_months
              AND month_idx(p.monthly_reporting_period) <= month_idx(s.event_date) + s.t_months + 12
        )
    )
    SELECT 
        s.event_type, s.t_months,
        COUNT(d.loan_id) * 1.0 / NULLIF(COUNT(s.loan_id), 0) as hazard_12m
    FROM survived_t s
    LEFT JOIN defaulted_next_12 d ON s.loan_id = d.loan_id AND s.t_months = d.t_months
    GROUP BY s.event_type, s.t_months
    """).df()
    
    haz_map = {}
    for _, r in df_haz.iterrows():
        haz_map[(r['event_type'], r['t_months'])] = r['hazard_12m'] if pd.notnull(r['hazard_12m']) else 0.0
        
    for basis in ['Censor', 'Purge']:
        P_12 = P_12_censor if basis == 'Censor' else P_12_purge
        P_life = P_life_censor if basis == 'Censor' else P_life_purge
        for hazard in ['Pooled', 'Conditional']:
            for lgd_val, lgd_name in [(0.1010, '10.10%'), (0.1368, '13.68%')]:
                
                # Score ECL
                total_ecl = 0
                for _, row in df_ecl.iterrows():
                    upb = row['snapshot_upb']
                    state = row['loan_state']
                    
                    if state == 'Default':
                        pd_val = 1.0
                    elif pd.notnull(row['event_type']) and row['months_since_event'] >= 0:
                        if hazard == 'Pooled':
                            pd_val = haz_pooled
                        else:
                            t = int(row['months_since_event'])
                            pd_val = haz_map.get((row['event_type'], t), haz_map.get((row['event_type'], 48), 0.0))
                    else:
                        if state == 'Current':
                            pd_val = STAGE_1_PD_CALIBRATED # Using calibrated Stage 1
                        elif state == '30_DPD':
                            pd_val = P_life[1, 0]
                        elif state == '60_DPD':
                            pd_val = P_life[2, 0]
                        else:
                            pd_val = STAGE_1_PD_CALIBRATED
                            
                    total_ecl += upb * pd_val * lgd_val
                
                results.append({
                    'PD Basis': basis,
                    'Pop 2 Hazard': hazard,
                    'LGD': lgd_name,
                    'Total ECL': total_ecl
                })
    
    print("\n--- ECL Scenario Grid ---")
    grid = pd.DataFrame(results)
    print(grid.to_string(index=False, float_format=lambda x: f"${x:,.2f}" if isinstance(x, float) and x > 100 else str(x)))

if __name__ == '__main__':
    build_grid()
