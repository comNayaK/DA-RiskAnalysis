# Progress Report: Residential Mortgage Credit Risk Engine (Verified Outputs)

*Note: This report is compiled strictly from empirical runs, system logs, and current codebase configuration (as of October 10, 2026).*

## 1. Schema & Data Ingestion
The raw data ingestion utilizes dynamic schema padding/truncation rather than a strict 32-column validation. 
*   **Sample Origination File (`sample_orig_2014.txt`)**: Contains 31 fields. The `ORIG_COLUMNS_32` mapping in `src/config.py` contains 32 fields. 
*   **Sample Performance File (`sample_perf_2014.txt`)**: Contains 35 fields. The `PERF_COLUMNS_32` mapping contains 32 fields.
*   **Ingestion Logic (`src/ingestion.py`)**: The system dynamically appends `extra_orig_col_N` or truncates the dictionary to match the detected `awk -F'|' '{print NF}'` field counts prior to DuckDB insertion.
*   **Content Assertions Added**: The ingestion pipeline now strictly asserts the 12-digit `F`-prefixed `loan_id` pattern, 6-digit `monthly_reporting_period`, constrained `modification_flag` values (`Y`, `P`, `N`, blank), valid `zero_balance_code` sets, and numeric structure for loss calculation columns.

## 2. Layer 1 Modification Policy & Population Counts
The model **censors** (rather than purges) modified loans.
*   **Censoring Path**: In `src/layers.py`, `clean_monthly_performance` maps the modification flag to `loan_state = 'Modified'`. `truncated_performance` explicitly truncates history via `WHERE c.monthly_reporting_period <= COALESCE(f.terminal_period, 999999)` (terminal period is the *first* Default or Modified).
*   **Reconciliation of 1,956 vs 2,096**: 
    *   **1,956** is the precise count of unique loans censored in Layer 1 (having hit the 'Modified' state strictly before the 202002 cutoff).
    *   **2,096** was derived in earlier LGD runs that evaluated *all* historically modified-defaulted loans without the strict active snapshot filter (mixing in post-cutoff cures and un-censored timeline noise). 

## 3. Vintage Scope & Backtest Directionality
*   **Multi-Vintage Scale**: The model evaluates 7 vintages (2010–2016), covering ~350,000 loans. The underlying `loan_level_transitions` table confirms ~50,000 loans per origination year spanning 2010 to 2016.
*   **Backtest Directionality**: The Through-The-Cycle (TTC) matrix currently **over-predicts** defaults for Current loans ($Z \approx -3.8$). The calendar effects—specifically the 2017 hurricanes in FL/TX/PR which distorted Stage 1 PD—matter significantly more than the modest age seasoning effect (roughly 17% lower hazard above 48 months).

## 4. Diagnostics: Monotonicity Failures (Multi-Vintage)
Risk ranking monotonicity is **not** resolved; it fails empirically for the `60_DPD` state, exhibiting a severe reversal where High-FICO defaults at higher rates than Lower-FICO.
Based on the **ex-hurricane multi-vintage dataset**:
*   **High-FICO**: $PD = 45.01\%$ (95% CI: $[43.38\%, 46.65\%]$, $N = 3,546$, $Defs = 1,596$)
*   **Mid-FICO**: $PD = 35.87\%$ (95% CI: $[34.63\%, 37.13\%]$, $N = 5,653$, $Defs = 2,028$)
*   **Lower-FICO**: $PD = 30.68\%$ (95% CI: $[29.50\%, 31.89\%]$, $N = 5,700$, $Defs = 1,749$)

## 5. Negative Controls & Matrix Uncertainty Bootstrap
**Pytest Results**: Both `test_negative_control_leak` and `test_mutation_leak` passed. These negative controls only test **population assignment** (verifying that a future modification does not leak backward to infect past state), but **do not** validate the ECL path calculation itself.

**Matrix-Only Sampling Error**:
A fixed-LGD bootstrap was executed to isolate matrix uncertainty from LGD boundaries. 
*   **Inputs**: LGD held fixed at 12.57%, Stage 3 excluded (PD fixed at 100%), and uncalibrated Stage 1 PD. 
*   **Resulting Band**: **\$31.36M — \$32.04M** (Median: \$31.71M). 
*   *Note: This isolates matrix sampling error only and is separate from the headline ECL.*

## 6. LGD Basis Derivation & Headline ECL
**LGD Basis Definitions**:
*   **11.5%**: The 36m follow-up *Censor Lower Bound* (purely $P(\text{Liquidation}) \times \text{Severity}$).
*   **13.6%**: The 36m follow-up *Censor Upper Bound*.
*   **16.7%**: The 36m follow-up *Purge Lower Bound*.
*   *(The 14.1%, 16.2%, and 19.3% figures previously quoted applied a 2.61% Tail Add-on for modified re-defaults, which has been separated here. The 12.57% bootstrap input was a raw midpoint devoid of strict exclude-modified logic).*

**Headline ECL Range**:
The total portfolio exposure is **\$28.7B**. Using the **ex-hurricane matrix (recalibrated to 0.178% for Stage 1)**, the ECL spans from a floor of **~\$29M** (using the 11.5% base LGD) up to **\$41.6M** (using the 16.7% Purge Lower bound). With the 14.1% All-In LGD, the central estimate is **\$35.2M** (~0.123% of UPB).

## 7. Pop 2 Reconciliation & All-Population Z-Score
The previously reported fluctuating Pop 2 counts (e.g., 2,661 dropped to 1,964; 353 defaults dropped to 147) were the artifact of an un-bounded event table mixing post-cutoff cures with active snapshot loans.
*   **True Active Pop 2 (201912)**: 1,964 loans.
*   **True Pop 2 Defaults**: 266 (147 non-modified delinquencies + 119 modified).
*   **Corrected All-Population Z-Score**: $Obs = 194,925$, $Act = 912$, $Exp = 895.5 \Rightarrow Z = +0.55$.
*   *Note*: A Green Z-score (+0.55) artificially balances out major sub-population failures (Pop 1 sits at $\approx -1.65\sigma$ while Pop 2 delinquent is heavily understated at $\approx +8\sigma$).

## 8. Known Issues
1. **Stage 1 Over-prediction**: The memoryless matrix structure artificially elevates 12m PD for clean loans by averaging in loans with recent delinquencies. **Hypothesis Tested**: Loans with a recent delinquency (trailing 12m) defaulted at **3.22%**, whereas clean-history loans defaulted at **0.156%**. The blended matrix heavily overstates risk for the clean majority.
2. **Pop 2 Hazard Outliers**: Pop 2 delinquent PDs remain severely understated ($Z = +8.3$ in specific buckets). The $35.2M headline ECL thus contains an estimated $1–2M understatement.
3. **Missing Data**: The 2014Q1 raw files have been deleted and remain unrecovered in the current data directory structure.
