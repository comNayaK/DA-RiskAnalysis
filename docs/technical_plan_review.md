# Technical Plan Review: Residential Mortgage Credit Risk Engine
## Errata Addendum & Updated Development Roadmap

**Document Type:** Errata Addendum to the Original Technical Implementation Plan  
**Target Context:** Internal Model Development, Governance Review & Phase 4 Roadmap  
**Status:** Working Development Plan (Phases 1–3 Complete; Phase 4 Scope Frozen)  
**Governance Notice:** This document serves as an errata addendum to the original technical plan. It codifies the econometric corrections, data schema lessons, and staging distinctions discovered during Phases 1–3 model development. This is an internal development document; formal model validation requires independent review under SR 11-7 / OCC 2011-12 standards.

---

## 1. Modification Handling & Population Segmentation (Pop 2 & Tail)

*   **Exit State, Not True Absorption:** In Layer 1, 'Modified' represents an absorbing exit from the **contractual Pop 1 Markov matrix**, but it is **not truly absorbing across the borrower lifecycle**. Empirical survival analysis proves that modified loans re-default at high rates (~43% cumulative re-default over 36 months). They must be modeled via a **separate post-event hazard sub-model** rather than treated as terminal cures or purged records.
*   **Modification Flag Standards:** The ingestion and cohort identification logic must evaluate both `modification_flag = 'Y'` (permanent modifications) and `modification_flag = 'P'` (trial/provisional modifications).
*   **SQL Anti-Pattern Fix (`NOT IN` $\rightarrow$ `NOT EXISTS`):** All population segmentation and modification queries must strictly utilize `NOT EXISTS` or anti-joins instead of `NOT IN`. A single `NULL` value in a subquery target column silently breaks `NOT IN` evaluation in standard SQL/DuckDB, leading to empty result sets or catastrophic loan misclassification.
*   **Strict As-Of Snapshot Restrictions:** Identification of Pop 2 loans and historical modification metrics must strictly use data available on or before the snapshot date (`monthly_reporting_period <= as_of_date`) to prevent forward-looking data leakage.
*   **Re-Default Tail Derivation:** The Pop 1 re-default tail evaluates latent modification risk for currently performing prime loans, factoring dollar-weighted modification share, cumulative re-default hazard, liquidation probability, and empirical loss severity.

---

## 2. As-Of Rules, Population Logic & Mutation Testing

*   **Strict Timeline Enforcement:** All population partitions, staging assignments, transition counting, and hazard models must be bounded by the reporting date of the analysis snapshot (e.g., `201912` for portfolio provisioning, `201812` for out-of-sample backtesting).
*   **Automated Mutation Testing:** The test suite must include continuous regression mutation tests (e.g., `tests/test_negative_control.py`). These tests deliberately omit the temporal filter on modifications or defaults, asserting that the pipeline detects the look-ahead contamination and fails immediately.

---

## 3. Loss Given Default (LGD) Bounds & Tail Framework

*   **Sensitivity Bounds Over Scalar Points:** Given liquidation follow-up uncertainty in judicial foreclosure states (e.g., NY, NJ, FL), LGD outputs must be reported across empirical bounds rather than as an unjustified single scalar:
    1.  **Censor Lower Bound (11.5% Base):** Assumes unresolved non-performing loans cure with zero loss.
    2.  **Censor Upper Bound (13.6% Base):** Treats lingering non-performing loans as full liquidations.
    3.  **Purge Cohort (16.7% Base):** Baseline from legacy purged panel for benchmark sensitivity.
*   **Derivation of Tail Multipliers:**
    *   **43.0% Cumulative Re-Default Hazard:** Empirically derived by integrating the Kaplan-Meier survival curves of modified loans over the 36-month follow-up window.
    *   **60.0% Liquidation Share:** Derived from the long-horizon benchmark liquidation cohort ($P(\text{Liquidation} \mid 90+)$), not an arbitrary assumption.
*   **Dollar-Weighted Basis:** All components of the re-default tail (modified share, liquidation probability, loss severity) must be derived on the identical dollar basis: **UPB at First Default**.
*   **"No Double Counting" as an Open Design Question:**
    *   *Current Engine Implementation:* Assigns Pop 2 the base 11.5% censor-only LGD (without adding the 2.68% Pop 1 modification tail), preventing double-charging for future modification risk.
    *   *Design Trade-Off Disclosure:* This is an open design choice and sensitivity assumption, not a dogmatic rule. Because Pop 2's PD represents a re-default hazard, its LGD should arguably be conditional on re-default. Applying the Censor Lower bound (11.5%) dilutes Pop 2 LGD with zero-loss modified loans, paradoxically assigning the riskiest population the lowest LGD. Future iterations should explore a dedicated conditional re-default LGD sub-model.

---

## 4. Staging Framework: IFRS 9 vs. CECL Accounting Distinctions

*   **Standard Nuances:** The development plan must explicitly distinguish the regulatory accounting standard implemented:
    *   **IFRS 9 Standard (Current Engine Basis):** Implements dual-horizon staging: 12-month PD for Stage 1 loans (clean, performing), and Lifetime PD for Stage 2 (significant increase in credit risk / probation) and Stage 3 (default). Yields the headline **~$45.2M scenario**.
    *   **CECL Standard (US GAAP):** Mandates **Lifetime ECL for all loans from origination**, including Stage 1 clean loans. Because the lifetime PD of clean Current loans is ~2.5% (vs 0.16% 12-month PD), applying CECL lifetime expectations to the entire $28.04B Current portfolio would elevate Stage 1 provisions alone from ~$6.2M to **over $90M+**, resulting in a portfolio ECL exceeding $120M+.
*   **Probation Logic as Policy Parameter:** The 12-month probation period is an internal risk policy parameter, not an explicit accounting mandate. Shifting recently delinquent loans into Stage 2 addresses the memoryless bias of Markov matrices. However, the ~9.5%–10.1% lifetime PD must not be hardcoded; it was derived from an empirical 3,415-loan tracking cohort and must be re-calibrated across vintages.
*   **EAD, Amortization & Discounting:** The current engine uses snapshot UPB as Exposure at Default (EAD). A production-grade build requires contractual amortization schedules, voluntary prepayment SMM curves, and effective interest rate (EIR) discounting to present value.

---

## 5. Model Gates, Acceptance Rules & Statistical Credibility

*   **Bootstrap Interpretation:** Bootstrap resampling provides parameter confidence intervals (sampling uncertainty), not model acceptance gate ranges. Acceptance gates must be statistically calibrated across historical vintages or calendar years.
*   **Rigorous Count Reconciliation:** Transition matrix auditing must compare the sum of matrix transition counts ($C_{\text{portfolio}}$) directly against the exact row count of `loan_level_transitions` (e.g., verifying 18,587,123 rows match to the single record).
*   **Pre-Determined Backtest Acceptance Rules:** Acceptance criteria must be locked *ex-ante* before execution. Because residential mortgage defaults exhibit spatial and vintage clustering, a pure Poisson or binomial normal score ($Z$-score) understates empirical variance. The acceptance rule should combine:
    $$\text{Tolerance Band} = \text{Expected Defaults} \pm \max(2.0\sigma, 15\% \times \text{Expected Defaults})$$
*   **Event-Count Credibility over Heuristics:** Replace arbitrary heuristics (e.g., `n < 100`) with **Wilson score intervals** and formal actuarial credibility weighting to govern state transition fallbacks.

---

## 6. Backtest Design & Out-of-Sample Methodology

*   **Consistent Out-of-Time Training:** Matrix parameters for out-of-sample testing must be trained on all transitions observed strictly on or before the snapshot date (`monthly_reporting_period <= snapshot_date`), eliminating temporal mismatch.
*   **Rolling-Origin Multi-Year Backtests:** Validating on a single benign year (2019) creates regime bias and over-prediction. The testing suite must implement rolling-origin backtests across snapshots 2015, 2016, 2017, and 2018 to evaluate model performance across both normal and stressed years.
*   **Transparent Offsetting Error Disclosure:** Backtest reporting must present granular results by sub-segment (Pop 1 Current, 30 DPD, 60 DPD; Pop 2 Current, 30 DPD, 60 DPD, Modified). Offsetting errors (e.g., Stage 1 under-prediction masking Pop 2 over-prediction) must be documented explicitly.
*   **Consistent 12-Month PD Input:** Backtest predictions must strictly evaluate 12-month default probabilities against 12-month realized outcomes, avoiding the misapplication of lifetime PDs to single-year backtests.

---

## 7. Data Ingestion, Macro Screens & Administrative Removals

*   **Multi-Vintage Minimum:** Production model training requires ingesting multiple cohorts spanning across business cycles (minimum 2010–2016 cohorts) to stabilize delinquency event counts and model seasoning.
*   **Macroeconomic Conditioning / Stress Overlays:** Because all available sample cohorts (2010–2016) reflect post-crisis economic expansion, the baseline matrix cannot forecast stressed conditions without explicit macro overlays or historical stress benchmarks (e.g., 2008 crisis proxy).
*   **Disaster & Calendar Effect Screens:** The pipeline must incorporate Freddie Mac disaster tracking flags or state-by-year screens to isolate catastrophic weather events (e.g., 2017 hurricanes Harvey/Irma in FL/TX/PR) from core underwriting credit risk.
*   **Explicit Schema Mapping:** Positional padding or truncation of variable-width raw files (e.g., 31 vs 32 columns, 35 vs 32 columns) must fail the ingestion load unless column-by-column mapping is explicitly validated.
*   **Informative Censoring (Admin Removals):** Zero balance removal codes `15` (Note Sales) and `16` (Third-Party Sales) must be treated as informative censoring rather than neutral clean pay-offs.

---

## 8. Summary of Known Methodological Limitations

Prior to any deployment or external review, the following core limitations must be explicitly disclosed:
1.  **Single Benign Regime:** The engine is calibrated on post-crisis historical data (2010–2019), representing a continuous credit expansion. Uncalibrated matrices over-predict defaults in benign years.
2.  **Small LGD Sample Size:** Empirical liquidation severity is based on approximately 1,000 liquidations, creating wide confidence intervals in LGD point estimates.
3.  **Absence of Cash Flow Discounting & EAD Amortization:** Assumes constant snapshot UPB and scalar LGDs without modeling prepayment decay or cash flow present value.
4.  **Stationary Markov Memorylessness:** First-order transition matrices ignore prior delinquency path dependence, requiring manual probation rule overlays.
5.  **Unresolved 60 DPD Non-Monotonicity:** High-FICO loans reaching 60 DPD default at higher rates than Lower-FICO loans; borrower selection and servicer velocity remain unproven working hypotheses.
6.  **Independent Validation Prerequisite:** Self-validation by model developers is not independent model validation under SR 11-7 standards.

---

## 9. Updated Development Roadmap & Phase Gate Table

The scope for Phases 1–3 is strictly frozen. The following gate table governs Phase 4 architectural enhancements:

| Gate | Development Milestone | Implementation Standard | Acceptance / Verification Gate | Status |
|---|---|---|---|---|
| **Gate 1** | Raw Ingestion & Schema Defense | Padded 32-column mappings; positive/negative shift assertions | Automated assertion test passes; 0 quarantine rows | ✅ **COMPLETE** |
| **Gate 2** | Layer 1 Absorbing Censoring | Censor loans at first modification; `NOT EXISTS` query logic | 1,956 loans censored; zero post-mod transitions | ✅ **COMPLETE** |
| **Gate 3** | Two-Factor Bounded LGD & Tail | 36m follow-up window; dollar-weighted first default UPB | 33.24% mod share, 2.68% tail $\rightarrow$ 14.18% Pop 1 LGD | ✅ **COMPLETE** |
| **Gate 4** | Pop 2 Segmentation & Staging | Active modified cohort isolation; double-count LGD protection | 1,964 loans ($334.14M UPB); 11.5% base LGD | ✅ **COMPLETE** |
| **Gate 5** | IFRS 9 Probation Staging | 12m probation for recent delinquencies; ex-hurricane PD | 4,314 loans ($699.34M UPB) @ 9.51% PD; +$9.27M reserve | ✅ **COMPLETE** |
| **Gate 6** | Out-of-Sample Backtesting | Frozen parameter scoring; transparent offsetting error disclosure | Documented RED uncalibrated backtest (+11.8% over-prediction) | ✅ **COMPLETE** |
| **Gate 7** | Master Table Reconciliation | Mutually exclusive 174,293 loan census; $28.71B UPB match | Row-by-row $\text{UPB} \times \text{PD} \times \text{LGD}$ exact sum ($45.23M) | ✅ **COMPLETE** |
| **Gate 8** | Rolling-Origin Backtesting | Multi-year backtests (2015–2019 snapshots) | Max prediction error within $\pm 15\%$ tolerance band | ⏸️ **FROZEN (Phase 4)** |
| **Gate 9** | EAD Amortization & Cash Flow | CPR/SMM prepayment curves; EIR cash flow discounting | Discounted cash flow engine reconciling to UPB | ⏸️ **FROZEN (Phase 4)** |
| **Gate 10** | Macroeconomic Conditioning | Cox hazard overlays conditioned on state unemployment / HPI | CCAR/DFAST stress scenario forecasting capabilities | ⏸️ **FROZEN (Phase 4)** |
