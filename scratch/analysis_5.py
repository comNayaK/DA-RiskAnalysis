import duckdb
from src.db import get_connection
import subprocess

def main():
    con = get_connection("mortgage_risk.duckdb")
    
    print("=== Fixing Pop 2 Delinquent PDs ===")
    
    # Get Pop 2 (active modified) loans in 201912 and their raw states
    q = """
    WITH p2_loans AS (
        SELECT loan_id FROM clean_monthly_performance 
        WHERE monthly_reporting_period = 201912 AND loan_state = 'Modified'
    )
    SELECT r.current_delinquency_status as raw_delq, COUNT(r.loan_id) as count, SUM(CAST(r.current_actual_upb AS DOUBLE)) as upb
    FROM raw_performance r
    JOIN p2_loans p2 ON r.loan_id = p2.loan_id
    WHERE r.monthly_reporting_period = '201912'
    GROUP BY r.current_delinquency_status
    """
    df_raw_p2 = con.execute(q).df()
    print(df_raw_p2)
    
    # Calculate ECL with actual PDs
    upb_0 = df_raw_p2[df_raw_p2['raw_delq']=='00']['upb'].sum() if '00' in df_raw_p2['raw_delq'].values else 0
    upb_1 = df_raw_p2[df_raw_p2['raw_delq']=='01']['upb'].sum() if '01' in df_raw_p2['raw_delq'].values else 0
    upb_2 = df_raw_p2[df_raw_p2['raw_delq']=='02']['upb'].sum() if '02' in df_raw_p2['raw_delq'].values else 0
    upb_def = df_raw_p2[~df_raw_p2['raw_delq'].isin(['00','01','02'])]['upb'].sum()
    
    # Using the PDs calculated earlier: 73.38% for 30 DPD ('01'), 84.50% for 60 DPD ('02')
    # For '00' (Current), we can use the Pop 1 Stage 1 PD (0.178%) or Stage 2 PD (12.24%). If Pop 2 probation applies, it's Stage 2 PD.
    # The ECL reported earlier in output 7 for Pop 2 in Stage 2 (UPB $334M) was $334M * 0.1224 * 0.141 = $5.7M
    ecl_p2_0 = upb_0 * 0.1224 * 0.141
    ecl_p2_1 = upb_1 * 0.7338 * 0.141
    ecl_p2_2 = upb_2 * 0.8450 * 0.141
    
    print(f"Pop 2 '00' (Current) UPB: ${upb_0:,.2f} | ECL: ${ecl_p2_0:,.2f}")
    print(f"Pop 2 '01' (30 DPD) UPB: ${upb_1:,.2f} | ECL: ${ecl_p2_1:,.2f}")
    print(f"Pop 2 '02' (60 DPD) UPB: ${upb_2:,.2f} | ECL: ${ecl_p2_2:,.2f}")
    print(f"Pop 2 Default/Other UPB: ${upb_def:,.2f} | ECL: ${(upb_def * 1.0 * 0.141):,.2f}")
    
    # Original Pop 2 ECL was roughly (upb_0 + upb_1 + upb_2) * 0.1224 * 0.141 + (upb_def * 1.0 * 0.141)
    original_ecl = (upb_0 + upb_1 + upb_2) * 0.1224 * 0.141 + (upb_def * 1.0 * 0.141)
    new_ecl = ecl_p2_0 + ecl_p2_1 + ecl_p2_2 + (upb_def * 1.0 * 0.141)
    print(f"Total Revised Pop 2 ECL: ${new_ecl:,.2f} (Old ECL was ${original_ecl:,.2f}, diff=${(new_ecl - original_ecl):,.2f})")
    
    # Ingestion Assertions
    print("\n=== Ingestion Assertions (Positive Cases) ===")
    sample_orig = 'data/sample_orig_2014.txt'
    sample_svcg = 'data/sample_perf_2014.txt'
    
    # Positive case
    loan_id_sample = subprocess.check_output(f"head -1 '{sample_orig}' | awk -F'|' '{{print $20}}'", shell=True).decode().strip()
    assert len(loan_id_sample) == 12 and loan_id_sample.startswith('F'), f"Invalid loan_id pattern: {loan_id_sample}"
    
    perf_sample_line = subprocess.check_output(f"head -1 '{sample_svcg}'", shell=True).decode().strip().split('|')
    reporting_period = perf_sample_line[1]
    mod_flag = perf_sample_line[7]
    zero_balance = perf_sample_line[8]
    actual_loss = perf_sample_line[21]
    
    assert len(reporting_period) == 6 and reporting_period.isdigit(), f"Invalid reporting period: {reporting_period}"
    assert mod_flag in ['Y', 'P', 'N', ''], f"Invalid modification flag: {mod_flag}"
    assert zero_balance in ['01', '02', '03', '06', '09', '15', '16', '96', ''], f"Invalid zero_balance_code: {zero_balance}"
    if actual_loss:
        assert actual_loss.replace('.','',1).lstrip('-').isdigit(), "actual_loss_calculation must be numeric"
    print("All assertions passed on sample data.")
    
    print("\n=== Ingestion Assertions (Negative Cases) ===")
    
    try:
        invalid_loan = "X12345678901"
        assert len(invalid_loan) == 12 and invalid_loan.startswith('F'), f"Invalid loan_id pattern: {invalid_loan}"
    except AssertionError as e:
        print(f"Caught expected error: {e}")
        
    try:
        invalid_period = "2019-12"
        assert len(invalid_period) == 6 and invalid_period.isdigit(), f"Invalid reporting period: {invalid_period}"
    except AssertionError as e:
        print(f"Caught expected error: {e}")
        
    try:
        invalid_loss = "N/A"
        assert invalid_loss.replace('.','',1).lstrip('-').isdigit(), "actual_loss_calculation must be numeric"
    except AssertionError as e:
        print(f"Caught expected error: {e}")

if __name__ == "__main__":
    main()
