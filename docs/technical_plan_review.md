# Technical Plan Review: Residential Mortgage Credit Risk Engine

Based on the empirical findings and methodological corrections from Phases 1–3, the following requirements must be integrated into the implementation plan for the final, verified model build. 

## 1. Modification Handling (Pop 2 & Tail)
*   **Censoring, Not Purging:** Modified loans must not be purged from the panel. They must be censored precisely at the date of first modification, treating 'Modified' as a distinct, absorbing exit state.
*   **Re-Default Tail:** Modified loans must be followed through LGD by adding a re-default tail. This tail evaluates the expected future modification risk of the currently performing population (Pop 1).
*   **Snapshot Restriction:** Every lookup related to modifications (e.g., identifying Pop 2 loans or measuring the modification share) must strictly utilize information available *as-of the snapshot date* to prevent forward-looking data leakage.

## 2. As-Of Rules & Population Logic
*   **Strict Timeline Enforcement:** All population definitions, staging assignments, and hazard calculations must use information available strictly at or before the snapshot date (e.g., `201912`). 
*   **Mutation Testing:** The test suite must include a mutation test that explicitly removes the temporal filter on modifications or defaults, asserting that the pipeline fails the test when future data is leaked backward.

## 3. Loss Given Default (LGD) Bounds
*   **Sensitivity Reporting:** Given the wide uncertainty in LGD bounds (e.g., base liquidations vs. full non-performing cohorts), LGD outputs must be reported as a set of sensitivities (e.g., Censor Lower bound, Impute Upper bound) rather than a single definitive scalar.
*   **Dollar-Weighted Inputs:** The components of the re-default tail—Probability of Liquidation, Severity, and Modified Share—must be derived on the exact same dollar basis (UPB at the time of first default).
*   **No Double Counting:** The re-default tail must only be added once (to Pop 1). Pop 2 (already active modified loans) must use the strict censor-only base LGD to prevent double-charging them for future modifications.

## 4. Staging (IFRS 9 vs. CECL)
*   **Standard Nuances:** The plan must explicitly acknowledge that IFRS 9 dictates distinct 12-month (Stage 1) vs. Lifetime (Stage 2/3) staging, whereas CECL requires Lifetime ECL for all loans. 
*   **Probation Logic:** A strict 12-month probation period rule must be codified to properly segment recently cured Pop 1 loans, recognizing that their empirically observed decay hazard (~10% lifetime PD) greatly exceeds pristine clean loans, even when currently in the '00' state. 
*   **Pop 2 Staging:** Pop 2 loans must be explicitly isolated and their staging definitions clarified, utilizing their own empirically measured hazard rates.

## 5. Model Gates and Acceptance Rules
*   **Calibrated Gates:** Hardcoded heuristic gates (such as the `> 0.99` threshold for Current $\rightarrow$ Current retention) must be replaced with a statistically calibrated, empirically justified range based on the matrix bootstrap.
*   **Count Reconciliation:** The row-sum check on the transition matrix (verifying probabilities sum to 1) must be augmented with a rigorous loan count reconciliation, ensuring the sum of all states strictly equals the total portfolio entry count.
*   **Backtest Acceptance Rule:** The plan must define a stated acceptance rule (e.g., maximum tolerance error) for the Out-of-Sample backtest.

## 6. Backtest Design
*   **Granular Testing:** The model backtest cannot rely on a single portfolio-level metric. It must test default predictions by individual state (Current, 30, 60), by population (Pop 1 vs. Pop 2), and in aggregate.
*   **Offsetting Errors:** The backtest report must transparently identify and report offsetting errors (e.g., Stage 1 under-prediction masking Stage 2 over-prediction) rather than allowing them to net to zero.
*   **Out-of-Time Testing:** The primary matrix validation must be executed via an out-of-time vintage test (e.g., predicting 2019 performance using a 2018 snapshot trained strictly on 2010–2017 transitions).

## 7. Data Scope & Content Assertions
*   **Multi-Vintage Minimum:** The ingestion pipeline and transition matrix must utilize a multi-vintage minimum (e.g., 2010–2016 cohorts) to stabilize event counts and evaluate seasoning.
*   **Calendar Effects:** A calendar-effect screen must be built in (e.g., disaster flags) to explicitly isolate macroeconomic or geographical anomalies, such as the 2017 hurricanes in FL/TX/PR which drastically distort baseline PDs.
*   **Raw Content Assertions:** The pipeline must enforce strict content assertions directly on the raw files for both Origination (checking trailing fields to catch mid-row shifts) and Performance (verifying valid delinquency and modification flags).

## 8. Known Methodological Limitations
The architecture carries inherent limitations that must be acknowledged prior to deployment:
1.  **Memoryless Matrix:** The Markov transition matrix inherently ignores loan history, artificially elevating the Stage 1 PD for pristine loans by averaging in recently cured loans.
2.  **60 DPD Reversal:** Risk ranking monotonicity empirically fails at the 60 DPD state (where High-FICO loans systematically default at higher rates than Lower-FICO loans).
3.  **Level Calibration:** PDs are calibrated solely to the average level observed in the training window, lacking the ability to forecast shifting macroeconomic scenarios without explicit scalar overlays.
