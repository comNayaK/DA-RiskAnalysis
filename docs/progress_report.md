# Progress Report: Residential Mortgage Credit Risk Engine (Verified Outputs)

*Note: This report is compiled strictly from empirical runs, system logs, and current codebase configuration (as of October 11, 2026).*

## 1. Schema & Data Ingestion
The raw data ingestion utilizes dynamic schema padding/truncation rather than a strict 32-column validation. 
*   **Sample Origination File (`sample_orig_2014.txt`)**: Contains 31 fields. The `ORIG_COLUMNS_32` mapping in `src/config.py` contains 32 fields. 
*   **Sample Performance File (`sample_perf_2014.txt`)**: Contains 35 fields. The `PERF_COLUMNS_32` mapping contains 32 fields.
*   **Ingestion Logic (`src/ingestion.py`)**: The system dynamically appends `extra_orig_col_N` or truncates the dictionary to match the detected `awk -F'|' '{print NF}'` field counts prior to DuckDB insertion.
*   **Content Assertions Added**: The ingestion pipeline strictly asserts the 12-digit `F`-prefixed `loan_id` pattern and trailing fields (e.g., `property_state`), 6-digit `monthly_reporting_period`, constrained `modification_flag` values (`Y`, `P`, `N`, blank), valid `zero_balance_code` sets, and numeric structure for loss calculation columns. (Negative testing confirms that invalid variants trigger explicit `AssertionError` exceptions on raw tables).

## 2. Layer 1 Modification Policy & Population Counts
The model **censors** (rather than purges) modified loans in Layer 1. 
*   **1,956** is the precise count of unique loans censored in Layer 1 (having hit the 'Modified' state strictly before the 202002 cutoff).

**The Re-default Tail & 36m LGD Cohort Mod Share**:
Based on the 36-month LGD cohort (loans where first default $\le 201612$):
*   Total Defaults: **3,276**
*   Modified Defaults (modified $\le 202002$): **958**
*   **Modified Share**: **29.24%**

Using this empirical 29.2% share applied against the total Modified UPB ($201.2M), with a 60% probability of liquidation upon re-default and 31.3% severity, the precise absolute **LGD Tail Add-on** evaluates to **\$11.05M**. (Earlier runs erroneously treated this as a flat 2.6% scalar added to the base rate based on an invalid 34.8% share).

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
A fixed-LGD bootstrap was executed to isolate transition matrix uncertainty. 
*   **Inputs**: LGD held fixed at 12.57%, Stage 3 excluded (PD fixed at 100%), and an uncalibrated Stage 1 PD. 
*   **Resulting Band**: **\$31.36M — \$32.04M**. 
*   *Note: This isolates matrix sampling error only and is separate from the headline ECL.*

## 6. The Stage 1 Over-prediction & Proposed Probation Rule
The memoryless matrix structure artificially elevates 12m PD for clean loans by averaging in loans with recent delinquencies. **Hypothesis Tested (2015–2019, Ex-Hurricane)**:
*   **2015**: Clean: 0.213% | Recent Delq: 3.698%
*   **2016**: Clean: 0.167% | Recent Delq: 3.455%
*   **2017**: Clean: 0.165% | Recent Delq: 3.428%
*   **2018**: Clean: 0.156% | Recent Delq: 3.224%
*   **2019**: Clean: 0.126% | Recent Delq: 3.738%

**Proposed Probation Rule**: 
Imposing a 12-month Stage 2 probation period for any loan with a recent delinquency shifts 4,606 loans (\$742.8M UPB) into Stage 2. These 4,606 loans have **zero overlap** with Pop 2. 
Applying the Stage 2 Lifetime PD (**12.24%**) to this cohort is justified because this lifetime metric accurately integrates the ~3.5% annualized short-term PD over the remaining weighted average life ($1 - (1 - 0.035)^{3.5} \approx 11.7\%$). Under this rule, the ECL for the Current cohort alone expands to **\$19.69M**.

## 7. Pop 2 Reconciliation & Delinquent Backtest
*   **True Active Pop 2 (201912)**: 1,964 loans.
*   **Pop 2 Delinquent Backtest**: Measuring 12m direct PD on the 201712 active modified cohort proves they default significantly faster than Pop 1 expectations. 
    *   **30 DPD**: 52.0% actual (vs 29.6% Pop 1 matrix PD).
    *   **60 DPD**: 77.4% actual (vs 66.7% Pop 1 matrix PD).

## 8. Headline ECL Calculation (11.5% Base LGD)
The model adopts a single, unified LGD basis (the 11.5% Censor Lower bound) across all stages, applying the recomputed absolute Mod Re-default Tail addition purely at the portfolio level.
*   *Headline 12m PD for Stage 1: 0.218%*

| Segment | UPB | Lifetime PD | LGD Base | ECL |
|---|---|---|---|---|
| Pop 1 Stage 1 | $28,137,473,427 | 0.218% | 11.5% | $7,054,065 |
| Pop 1 Stage 2 (30 DPD) | $208,914,436 | 12.24% | 11.5% | $2,940,680 |
| Pop 1 Stage 2 (60 DPD) | $43,259,255 | 52.59% | 11.5% | $2,616,255 |
| Pop 2 Current | $164,566,546 | 12.24% | 11.5% | $2,316,439 |
| Pop 2 30 DPD | $28,304,669 | 73.38% | 11.5% | $2,388,546 |
| Pop 2 60 DPD | $8,357,824 | 84.50% | 11.5% | $812,172 |
| Pop 3 (Default) | $117,265,323 | 100.0% | 11.5% | $13,485,512 |
| Mod Re-default Tail | - | - | - | $11,050,034 |
| **Total** | **$28,708,141,480** | | | **$42,663,702** |

---
*Missing Data Note: The 2014Q1 raw files have been deleted and remain unrecovered.*
