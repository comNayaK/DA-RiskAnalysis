"""
Residential Mortgage Credit Risk Engine - Configuration & Schema Definitions
Phases 1-3: Panel Construction, Absorbing Markov ECL & FICO Risk Segmentation
"""

# State Space Definitions
TRANSIENT_STATES = ['Current', '30_DPD', '60_DPD']
ABSORBING_STATES = ['Paid_Off', 'Default']
ALL_STATES = TRANSIENT_STATES + ABSORBING_STATES

STATE_INDEX = {s: i for i, s in enumerate(TRANSIENT_STATES)}
ALL_STATE_INDEX = {s: i for i, s in enumerate(ALL_STATES)}

# FICO Stratification Bands
FICO_BANDS = ['High-FICO', 'Mid-FICO', 'Lower-FICO']

# Temporal Milestones & Cutoffs
PRE_COVID_CUTOFF = 202002       # Hard cutoff to avoid pandemic forbearance / CARES Act distortion
LGD_24M_COHORT_CUTOFF = 201712  # Guarantees full 24m follow-up before 202002
LGD_36M_COHORT_CUTOFF = 201612  # Guarantees full 36m follow-up before 202002
ECL_SNAPSHOT_PERIOD = 201912    # Latest clean pre-COVID snapshot
BACKTEST_TRAIN_CUTOFF = 201812  # Out-of-sample estimation cutoff
BACKTEST_SNAPSHOT = 201812      # Out-of-sample snapshot
BACKTEST_EVAL_YEAR = 2019       # Out-of-sample default evaluation horizon

# Modern 32-Column Freddie Mac Origination File Schema
ORIG_COLUMNS_32 = {
    'credit_score': 'VARCHAR',
    'first_payment_date': 'VARCHAR',
    'first_time_homebuyer_flag': 'VARCHAR',
    'maturity_date': 'VARCHAR',
    'msa': 'VARCHAR',
    'mi_percentage': 'VARCHAR',
    'number_of_units': 'VARCHAR',
    'occupancy_status': 'VARCHAR',
    'orig_cltv': 'VARCHAR',
    'orig_dti': 'VARCHAR',
    'orig_upb': 'VARCHAR',
    'orig_ltv': 'VARCHAR',
    'orig_interest_rate': 'VARCHAR',
    'channel': 'VARCHAR',
    'ppm_flag': 'VARCHAR',
    'amortization_type': 'VARCHAR',
    'property_state': 'VARCHAR',
    'property_type': 'VARCHAR',
    'postal_code': 'VARCHAR',
    'loan_id': 'VARCHAR',
    'loan_purpose': 'VARCHAR',
    'orig_loan_term': 'VARCHAR',
    'number_of_borrowers': 'VARCHAR',
    'seller_name': 'VARCHAR',
    'servicer_name': 'VARCHAR',
    'super_conforming_flag': 'VARCHAR',
    # Expanded 32-column modern release fields
    'pre_harp_loan_id': 'VARCHAR',
    'program_indicator': 'VARCHAR',
    'harp_indicator': 'VARCHAR',
    'property_valuation_method': 'VARCHAR',
    'interest_only_indicator': 'VARCHAR',
    'mortgage_insurance_cancellation_indicator': 'VARCHAR'
}

# Modern 32-Column Freddie Mac Performance / Servicing File Schema
PERF_COLUMNS_32 = {
    'loan_id': 'VARCHAR',
    'monthly_reporting_period': 'VARCHAR',
    'current_actual_upb': 'VARCHAR',
    'current_delinquency_status': 'VARCHAR',
    'loan_age': 'VARCHAR',
    'remaining_months_to_maturity': 'VARCHAR',
    'defect_settlement_date': 'VARCHAR',
    'modification_flag': 'VARCHAR',
    'zero_balance_code': 'VARCHAR',
    'zero_balance_effective_date': 'VARCHAR',
    'current_interest_rate': 'VARCHAR',
    'current_deferred_upb': 'VARCHAR',
    'ddlpi': 'VARCHAR',
    'mi_recoveries': 'VARCHAR',
    'net_sales_proceeds': 'VARCHAR',
    'non_mi_recoveries': 'VARCHAR',
    'expenses': 'VARCHAR',
    'legal_costs': 'VARCHAR',
    'maintenance_costs': 'VARCHAR',
    'taxes_and_insurance': 'VARCHAR',
    'misc_expenses': 'VARCHAR',
    'actual_loss_calculation': 'VARCHAR',
    'modification_cost': 'VARCHAR',
    'step_modification_flag': 'VARCHAR',
    'deferred_payment_plan': 'VARCHAR',
    'eltv': 'VARCHAR',
    'zero_balance_removal_upb': 'VARCHAR',
    'delinquent_accrued_interest': 'VARCHAR',
    # Expanded 32-column modern release fields
    'delinquency_due_to_disaster': 'VARCHAR',
    'borrower_assistance_status': 'VARCHAR',
    'current_month_modification_cost': 'VARCHAR',
    'interest_bearing_upb': 'VARCHAR'
}
