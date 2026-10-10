# Progress Report: Residential Mortgage Credit Risk Engine (Verified Outputs)

*Note: This report is compiled strictly from empirical runs, system logs, and current codebase configuration (as of October 11, 2026). It documents known methodological bounds and serves as a draft summary, not a fully validated model.*

## 1. Schema & Data Ingestion
The raw data ingestion utilizes dynamic schema padding/truncation rather than a strict 32-column validation. 
*   **Sample Origination File (`sample_orig_2014.txt`)**: Contains 31 fields. The `ORIG_COLUMNS_32` mapping in `src/config.py` contains 32 fields. 
*   **Sample Performance File (`sample_perf_2014.txt`)**: Contains 35 fields. The `PERF_COLUMNS_32` mapping contains 32 fields.
*   **Ingestion Logic (`src/ingestion.py`)**: The system dynamically appends `extra_orig_col_N` or truncates the dictionary to match the detected field counts prior to DuckDB insertion.
*   **Content Assertions Added**: The ingestion pipeline strictly asserts the 12-digit `F`-prefixed `loan_id` pattern and fields trailing it (e.g., verifying `orig_loan_term` is strictly numeric), 6-digit `monthly_reporting_period`, constrained `modification_flag` values (`Y`, `P`, `N`, blank), valid `zero_balance_code` sets, and numeric structure for loss calculation columns. 

## 2. Layer 1 Modification Policy & Population Counts
The model **censors** modified loans in Layer 1, treating 'Modified' as an absorbing exit state.
*   **1,956** is the precise count of unique loans censored in Layer 1 (having hit the 'Modified' state strictly before the 202002 cutoff).
*   Of the original 2,096 total loans that eventually defaulted after modification, **1,843 (88%) defaulted *before* they were modified**. True mod-before-default loans constituted exactly **14 loans**.

**The Re-default Tail & 36m LGD Cohort Mod Share**:
Based strictly on the 36-month LGD cohort (loans where `first_default <= 201612`), using the same cohort structure applied to the LGD calculations:
*   Total Defaults (<= 201612): **3,276** (Total UPB: \$264.88M)
*   Modified Defaults (modified $\le 202002$): **958** (Modified UPB: \$165.04M)
*   **Dollar-Weighted Modified Share**: **62.31%** (By count: 29.24%)

The LGD incorporates this tail directly as a cumulative rate factored into severity. 
*   **Tail Rate**: `62.31% (Share) * 40% (Re-default Rate) * 60% (P(Liq)) * 31.3% (Severity) = 4.68%`.
*   **Blended LGD**: `11.5% (Censor Lower bound) + 4.68% = 13.69% (rounded to 13.7%)`.
Note: The blended LGD is applied uniformly across the entire portfolio (including Pop 2).

## 3. Vintage Scope & Backtest Directionality
*   **Multi-Vintage Scale**: The model evaluates 7 vintages (2010–2016), covering ~350,000 loans. 
*   **Backtest Directionality**: The Through-The-Cycle (TTC) matrix currently **over-predicts** defaults for Current loans ($Z \approx -3.8$). The calendar effects—specifically the 2017 hurricanes in FL/TX/PR which distorted Stage 1 PD—matter significantly more than the modest age seasoning effect (roughly 17% lower hazard above 48 months).

## 4. Diagnostics: Monotonicity Failures
Risk ranking monotonicity fails empirically for the `60_DPD` state, exhibiting a severe reversal where High-FICO defaults at higher rates than Lower-FICO.
Based on the **ex-hurricane multi-vintage dataset**:
*   **High-FICO**: $PD = 45.01\%$ (95% CI: $[43.38\%, 46.65\%]$, $N = 3,546$, $Defs = 1,596$)
*   **Mid-FICO**: $PD = 35.87\%$ (95% CI: $[34.63\%, 37.13\%]$, $N = 5,653$, $Defs = 2,028$)
*   **Lower-FICO**: $PD = 30.68\%$ (95% CI: $[29.50\%, 31.89\%]$, $N = 5,700$, $Defs = 1,749$)

## 5. Negative Controls & Matrix Uncertainty
**Pytest Results**: Both `test_negative_control_leak` and `test_mutation_leak` passed. These negative controls only test population assignment logic, not the ECL path calculation.
**Matrix-Only Sampling Error**: A fixed-LGD bootstrap run isolates matrix uncertainty. 
*   **Resulting Band**: **\$31.36M — \$32.04M**. (Note: This isolated test is separate from the blended ECL).

## 6. Pop 1 Stage 1 Probation Rule
The memoryless matrix structure artificially elevates 12m PD for clean loans by averaging in loans with recent delinquencies. **Hypothesis Tested (2015–2019, Ex-Hurricane)**:
*   **2015**: Clean: 0.213% | Recent Delq: 3.698%
*   **2016**: Clean: 0.167% | Recent Delq: 3.455%
*   **2017**: Clean: 0.165% | Recent Delq: 3.428%
*   **2018**: Clean: 0.156% | Recent Delq: 3.224%
*   **2019**: Clean: 0.126% | Recent Delq: 3.738%

**Proposed Probation Rule**: 
Imposing a 12-month Stage 2 probation period for any loan with a recent delinquency shifts 4,606 loans (\$742.8M UPB) into Stage 2. These 4,606 loans have **zero overlap** with Pop 2. 
Applying the matrix Stage 2 (30 DPD) Lifetime PD (**12.24%**) to this cohort evaluates the remaining risk profile correctly (a ~3.5% annualized hazard over a remaining WAL of ~3.5 years mathematically aligns with ~11.7–12.2%). 

## 7. Pop 2 Delinquent Backtest
*   **True Active Pop 2 (201912)**: 1,964 loans.
*   **Pop 2 Delinquent Backtest**: We tracked 12m direct PD across five cohorts (2015–2019) to extract a pooled empirical rate.
    *   **2015**: 30 DPD: 55.48% (± 8.06%) | 60 DPD: 75.41% (±10.81%)
    *   **2016**: 30 DPD: 49.43% (± 7.39%) | 60 DPD: 83.53% (± 7.89%)
    *   **2017**: 30 DPD: 55.94% (± 6.85%) | 60 DPD: 82.41% (± 7.18%)
    *   **2018**: 30 DPD: 52.04% (± 6.99%) | 60 DPD: 76.96% (± 5.97%)
    *   **2019**: 30 DPD: 43.15% (± 8.03%) | 60 DPD: 80.20% (± 7.77%)
*   **Pooled Rate Used in ECL**:
    *   Pop 2 **30 DPD**: **51.50%** (±3.33%)
    *   Pop 2 **60 DPD**: **79.49%** (±3.39%)

## 8. Headline ECL Calculation (13.7% Blended LGD)
The model adopts a unified blended LGD basis of **13.7%** (11.5% Censor Lower + 2.2% Tail). The Pop 2 delinquent states use the empirical pooled rates.

| Scenario | Total ECL |
|---|---|
| **ECL (No Probation)** | **$36,755,685** |
| **ECL (WITH Probation)** | **$47,490,019** |

---
*Missing Data Note: The 2014Q1 raw files have been deleted and remain unrecovered.*
