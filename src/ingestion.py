"""
Layer 0: Ingestion and Audit Module
Supports both 26/28-column legacy releases and modern 32-column Freddie Mac releases.
"""
import glob
import os
import subprocess
import duckdb
from src.config import ORIG_COLUMNS_32, PERF_COLUMNS_32

def audit_files(orig_pattern: str, svcg_pattern: str):
    """
    Performs Pre-Run File Audit (Section 0 of Implementation Plan).
    Checks column counts and loan ID format before ingestion.
    """
    orig_files = glob.glob(orig_pattern)
    svcg_files = glob.glob(svcg_pattern)
    
    if not orig_files:
        raise FileNotFoundError(f"No origination files matched: {orig_pattern}")
    if not svcg_files:
        raise FileNotFoundError(f"No performance files matched: {svcg_pattern}")
        
    print(f"[Audit] Found {len(orig_files)} origination file(s) and {len(svcg_files)} performance file(s).")
    
    # Check field count on first origination file
    sample_orig = orig_files[0]
    sample_svcg = svcg_files[0]
    
    orig_cols = int(subprocess.check_output(f"head -1 '{sample_orig}' | awk -F'|' '{{print NF}}'", shell=True).decode().strip())
    svcg_cols = int(subprocess.check_output(f"head -1 '{sample_svcg}' | awk -F'|' '{{print NF}}'", shell=True).decode().strip())
    
    print(f"[Audit] Origination columns detected: {orig_cols} (Sample file: {os.path.basename(sample_orig)})")
    print(f"[Audit] Performance columns detected: {svcg_cols} (Sample file: {os.path.basename(sample_svcg)})")
    
    # Check loan ID format (field 20 for origination)
    loan_id_sample = subprocess.check_output(f"head -1 '{sample_orig}' | awk -F'|' '{{print $20}}'", shell=True).decode().strip()
    print(f"[Audit] Sample Loan ID: {loan_id_sample} -> Orig Year: 2000 + {loan_id_sample[1:3]} = {2000 + int(loan_id_sample[1:3])}")
    
    # Assertions
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
    
    return orig_cols, svcg_cols

def ingest_raw_data(con: duckdb.DuckDBPyConnection, orig_path: str, svcg_path: str, orig_cols: int, svcg_cols: int):
    """
    Ingests flat files into raw_origination and raw_performance tables
    using safe dynamic schema definitions based on detected column counts.
    """
    # Dynamically adjust Origination schema
    orig_schema = list(ORIG_COLUMNS_32.keys())
    while len(orig_schema) < orig_cols:
        orig_schema.append(f'extra_orig_col_{len(orig_schema)}')
    orig_schema = orig_schema[:orig_cols]
    orig_dict = {col: 'VARCHAR' for col in orig_schema}

    # Dynamically adjust Performance schema
    perf_schema = list(PERF_COLUMNS_32.keys())
    while len(perf_schema) < svcg_cols:
        perf_schema.append(f'extra_perf_col_{len(perf_schema)}')
    perf_schema = perf_schema[:svcg_cols]
    perf_dict = {col: 'VARCHAR' for col in perf_schema}

    print(f"[Ingestion] Loading raw_origination from: {orig_path} with {orig_cols} columns")
    con.execute(f"""
    CREATE OR REPLACE TABLE raw_origination AS
    SELECT * FROM read_csv(
        '{orig_path}',
        delim='|',
        header=False,
        all_varchar=True,
        columns={orig_dict}
    );
    """)
    orig_count = con.execute("SELECT COUNT(*) FROM raw_origination").fetchone()[0]
    print(f"[Ingestion] raw_origination loaded: {orig_count:,} rows.")

    print(f"[Ingestion] Loading raw_performance from: {svcg_path} with {svcg_cols} columns")
    con.execute(f"""
    CREATE OR REPLACE TABLE raw_performance AS
    SELECT * FROM read_csv(
        '{svcg_path}',
        delim='|',
        header=False,
        all_varchar=True,
        columns={perf_dict}
    );
    """)
    perf_count = con.execute("SELECT COUNT(*) FROM raw_performance").fetchone()[0]
    print(f"[Ingestion] raw_performance loaded: {perf_count:,} rows.")

    return orig_count, perf_count
