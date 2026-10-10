import numpy as np
import duckdb
con = duckdb.connect('mortgage_risk.duckdb')
from src.config import BACKTEST_TRAIN_CUTOFF
df_port_train = con.execute(f"SELECT state_t, state_t_plus_1, COUNT(*) as n FROM loan_level_transitions WHERE monthly_reporting_period <= {BACKTEST_TRAIN_CUTOFF} GROUP BY 1,2").df()

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

def get_12m_probs(Q, R):
    P_12 = np.zeros((3, 4))
    for t in range(12):
        P_12 += np.linalg.matrix_power(Q, t) @ R
    return P_12

def get_lifetime_probs(Q, R):
    I = np.eye(Q.shape[0])
    N = np.linalg.inv(I - Q)
    B = N @ R
    return B

P_12_base = get_12m_probs(Q_train, R_train)
P_lifetime_base = get_lifetime_probs(Q_train, R_train)

print("12m PD (Current, 30_DPD, 60_DPD):")
print(P_12_base[:, 0])
print("Lifetime PD (Current, 30_DPD, 60_DPD):")
print(P_lifetime_base[:, 0])

