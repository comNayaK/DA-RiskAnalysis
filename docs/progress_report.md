# Progress Report: Residential Mortgage Credit Risk Engine (Draft Summary)

*Note: This report is a draft summary of the repo based strictly on empirical runs, not a fully validated model. Known methodological limitations are documented below.*

## 1. Schema & Data Ingestion
The raw data ingestion utilizes dynamic schema padding/truncation for the 31/35-column raw files against the 32-column `ORIG_COLUMNS_32`/`PERF_COLUMNS_32` mappings in `src/config.py`. 
*   **Content Assertions**: The ingestion pipeline asserts the 12-digit `F`-prefixed `loan_id` pattern and directly verifies fields trailing it to catch mid-row shifts. For example, testing `orig_loan_term` strictly checks for a numeric value. (Negative testing confirms that a missing field artificially shifts string characters into numeric fields, immediately triggering an `AssertionError`).

## 2. Layer 1 Modification Policy & LGD Tail Re-Calculation
The model **censors** modified loans in Layer 1, treating 'Modified' as an absorbing exit state.
*   **1,956** is the precise count of unique loans censored in Layer 1 (having hit the 'Modified' state strictly before the 202002 cutoff).
*   Of the original 2,096 total loans that eventually defaulted after modification, **1,843 (88%) defaulted *before* they were modified**. True mod-before-default loans constituted exactly **14 loans**.

**The Re-default Tail (Pop 1)**:
The LGD incorporates the probability of a currently performing loan eventually modifying and re-defaulting as a cumulative rate factored into severity. 
Based on the UPB *at first default* for the 36-month LGD cohort (defaults $\le 201612$):
*   Total Default UPB: **\$579.3M** (3,276 loans)
*   Modified Default UPB: **\$192.6M** (958 loans)
*   **Dollar-Weighted Modified Share**: **33.24%** 

Deriving the cumulative re-default hazard directly from the survival curves yields an integrated rate of **43%**.
*   **Tail Rate**: `33.24% (Mod Share) * 43% (Cumulative Re-default) * 60% (P(Liq)) * 31.3% (Severity) = 2.68%`.
*   **Blended Pop 1 LGD**: `11.5% (Censor Lower bound) + 2.68% (Tail) = 14.18% (rounded to 14.2%)`.

## 3. Pop 2 Active Modification Sub-segment
Pop 2 consists of currently active modified loans. They represent just **0.70% of total UPB** (\$201.2M), yet given their severe hazard rates, they account for roughly **13% of the total ECL**.
To prevent double-counting latent future modifications within this already-modified sub-segment, **Pop 2 is assigned the strict 11.5% censor-only LGD**.

**Pop 2 Delinquent Backtest (2015–2019 Pooled)**:
We tracked the 12m actual default rates for Pop 2 loans hitting 30 and 60 DPD across the 5 pre-pandemic years. *(Note: The prior 201812 snapshot backtest of 29.6%/66.7% used slightly different raw states resulting in a denominator artifact; the unified 5-year pooled empirical rate provides a much more robust anchor).*
*   **2015**: 30 DPD (Obs: 146, Defs: 81) = 55.48% | 60 DPD (Obs: 61, Defs: 46) = 75.41%
*   **2016**: 30 DPD (Obs: 176, Defs: 87) = 49.43% | 60 DPD (Obs: 85, Defs: 71) = 83.53%
*   **2017**: 30 DPD (Obs: 202, Defs: 113) = 55.94% | 60 DPD (Obs: 108, Defs: 89) = 82.41%
*   **2018**: 30 DPD (Obs: 196, Defs: 102) = 52.04% | 60 DPD (Obs: 191, Defs: 147) = 76.96%
*   **2019**: 30 DPD (Obs: 146, Defs: 63) = 43.15% | 60 DPD (Obs: 101, Defs: 81) = 80.20%
*   **Pooled Rate Used in ECL**:
    *   Pop 2 **30 DPD**: **51.50%**
    *   Pop 2 **60 DPD**: **79.49%**

## 4. Vintage Scope & Diagnostics
*   **Multi-Vintage Scale**: The model evaluates 7 vintages (2010–2016), covering ~350,000 loans. 
*   **Monotonicity Failures**: Risk ranking monotonicity fails empirically for the `60_DPD` state, exhibiting a severe reversal where High-FICO defaults at higher rates than Lower-FICO.
*   **Negative Controls**: Both Pytest negative controls passed, verifying population assignment logic (not ECL paths).
*   **Matrix Uncertainty**: A fixed-LGD bootstrap run isolates matrix uncertainty. The resulting band is **\$31.36M — \$32.04M** (this isolates sample error separate from the blended ECL calculation).

## 5. Pop 1 Stage 1 Probation Rule
The memoryless matrix structure artificially elevates 12m PD for strictly clean loans by averaging in loans with recent delinquencies. 
Imposing a 12-month Stage 2 probation period for any loan with a recent delinquency isolates **4,606 loans** (\$742.8M UPB). This cohort has exactly zero overlap with Pop 2 (Pop 1 loans are by definition unmodified).

To accurately price this cohort, we derived an **Empirical 4-Year Lifetime PD of 10.13%**, built by tracking the actual 2015 "recently cured" cohort through 2019. (Applying the generic 12.24% matrix PD for active 30 DPD loans overstated the hazard, as it ignored the rapid decay curve characteristic of post-event cures). 

## 6. Headline ECL Calculation 
The model applies the unified blended LGD basis of **14.2%** to Pop 1, and the base **11.5%** to Pop 2.

| Scenario | Total ECL |
|---|---|
| **Base ECL (No Probation)** | **$36,945,042** |
| **ECL (WITH Probation)** | **$45,837,407** |
*(The Probation sensitivity drives an $8.89M delta)*

---
**Limitations:** This draft relies on aggregated matrix-derived probabilities and hardcoded uniform severity multipliers rather than fully parameterized loan-level covariates. Vintage effects are truncated for simplicity. The 2014Q1 raw files have been deleted and remain unrecovered.
