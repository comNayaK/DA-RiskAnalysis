# Technical Plan Review: Residential Mortgage Credit Risk Engine
## Errata Addendum & Updated Development Roadmap

**Document Type:** Errata Addendum to the Original Technical Implementation Plan  
**Target Context:** Internal Model Development, Governance Review & Phase 4 Roadmap  
**Status:** Working Development Plan (Phases 1–3 Complete; Phase 4 Scope Frozen)  
**Governance Notice:** This document serves as an errata addendum to the original technical plan. It codifies the econometric corrections, data schema lessons, and staging distinctions discovered during Phases 1–3 model development. This is an internal development document; formal model validation requires independent review under SR 11-7 / OCC 2011-12 standards.

---

## 1. Modification Handling & Population Segmentation (Pop 2 & Tail)

*   **Exit State, Not True Absorption:** In Layer 1, 'Modified' represents an absorbing exit from the **contractual Pop 1 Markov matrix**, but it is **not truly absorbing across the borrower lifecycle**. Empirical survival analysis proves that modified loans re-default at elevated rates (~40% cumulative re-default at 36 months, ~43% at 48 months). They must be modeled via a **separate post-event hazard sub-model** rather than treated as terminal cures or purged records.
*   **Freddie Mac Modification Flag Specification:**
    *   `modification_flag = 'Y'`: Loan modified in the **current monthly reporting period**.
    *   `modification_flag = 'P'`: Loan modified in a **prior reporting period** (permanent previous modification).
    *   Both values indicate an active modified status and must trigger Layer 1 censoring and Pop 2 segmentation.
*   **SQL Anti-Pattern Fix (`NOT IN` $\rightarrow$ `NOT EXISTS`):** All population segmentation, cohort identification, and transition extraction queries must strictly utilize `NOT EXISTS` or anti-joins instead of `NOT IN`. A single `NULL` value in a subquery target column causes standard SQL three-valued logic (`UNKNOWN`) to fail the predicate for all candidate records, silently producing empty result sets or corrupted loan classification.
*   **Strict As-Of Snapshot Restrictions:** Identification of Pop 2 loans and historical modification metrics must strictly use data available on or before the snapshot date (`monthly_reporting_period <= as_of_date`) to prevent forward-looking data leakage.
*   **Re-Default Tail Derivation:** The Pop 1 re-default tail evaluates latent modification risk for currently performing prime loans, factoring dollar-weighted modification share, cumulative re-default hazard, liquidation probability, and empirical loss severity.

---

## 2. As-Of Rules, Population Logic & Mutation Testing

*   **Strict Timeline Enforcement:** All population partitions, staging assignments, transition counting, and hazard models must be bounded by the reporting date of the analysis snapshot (e.g., `201912` for portfolio provisioning, `201812` for out-of-sample backtesting).
*   **Automated Mutation Testing:** The test suite must include continuous regression mutation tests (e.g., `tests/test_negative_control.py`). These tests deliberately omit the temporal filter on modifications or defaults, asserting that the pipeline detects the look-ahead contamination and fails immediately.

---

## 3. Loss Given Default (LGD) Bounds & Re-Default Tail Framework

*   **Sensitivity Bounds Over Scalar Points:** Given liquidation follow-up uncertainty in judicial foreclosure states (e.g., NY, NJ, FL), LGD outputs must be reported across empirical bounds rather than as an unjustified single scalar:
    1.  **Censor Lower Bound (11.50% Base):** Assumes unresolved non-performing loans cure with zero loss.
    2.  **Censor Upper Bound (13.60% Base):** Treats lingering non-performing loans as full liquidations.
    3.  **Purge Cohort (16.70% Base):** Baseline from legacy purged panel for benchmark sensitivity.
*   **Headline Re-Default Tail (48-Month Horizon):**
    *   **Headline Horizon Selection:** The engine adopts the **48-month horizon** as the single headline parameter for portfolio provisioning, with the 36-month horizon retained strictly as an empirical sensitivity.
    *   **Empirical Hazard Chaining Method:** Computed by chaining discrete 12-month conditional non-re-default survival rates:
        *   Window 1 ($0\text{--}12\text{m}$): $S_1 = 0.7780 \implies h_1 = 22.20\%$ hazard.
        *   Window 2 ($12\text{--}24\text{m}$): $S_2 = 0.8610 \implies h_2 = 13.90\%$ hazard.
        *   Window 3 ($24\text{--}36\text{m}$): $S_3 = 0.9050 \implies h_3 = 9.50\%$ hazard.
        *   *36-Month Cumulative Hazard:* $1 - (0.7780 \times 0.8610 \times 0.9050) = 1 - 0.6062 = \mathbf{39.38\% \approx 40.0\%}$.
        *   Window 4 ($36\text{--}48\text{m}$): $S_4 = 0.9413 \implies h_4 = 5.87\%$ hazard.
        *   *48-Month Cumulative Hazard (Headline):* $1 - (0.6062 \times 0.9413) = 1 - 0.5706 = \mathbf{42.94\% \approx 43.0\%}$.
    *   **Tail Add-on Formula:**
        $$\text{Tail} = P(\text{Mod} \mid \text{Def}) \times P(\text{Re-Def} \mid \text{Mod}) \times P(\text{Liq} \mid \text{Re-Def}) \times \text{Severity}$$
        *   Headline 48m Tail: $33.24\% \times 42.94\% \times 60.0\% \times 31.32\% = \mathbf{2.68\%} \implies \text{Pop 1 LGD} = 11.50\% + 2.68\% = \mathbf{14.18\%}$.
        *   Sensitivity 36m Tail: $33.24\% \times 39.38\% \times 60.0\% \times 31.32\% = \mathbf{2.46\% \approx 2.50\%} \implies \text{Pop 1 LGD} = 11.50\% + 2.50\% = \mathbf{14.00\%}$.
*   **Methodological Caveats:**
    1.  *Discrete Chaining vs Continuous Kaplan-Meier:* Chaining conditional annual discrete survival rates approximates empirical survival; formal continuous-time Kaplan-Meier curve validation with Greenwood standard error bounds remains unverified.
    2.  *Assumed Liquidation Share:* The 60.0% parameter is an assumed liquidation share applied conditional on re-defaults, based on long-horizon empirical resolution benchmarks ($P(\text{Liquidation} \mid 90+)$).
*   **Dollar-Weighted Basis:** All components of the re-default tail (modified share, liquidation probability, loss severity) must be derived on the identical dollar basis: **UPB at First Default**.
*   **"No Double Counting" as an Open Design Question:**
    *   *Current Engine Implementation:* Assigns Pop 2 the base 11.50% censor-only LGD (without adding the Pop 1 modification tail), preventing double-charging for future modification risk.
    *   *Design Trade-Off Disclosure:* This is an open design choice and sensitivity assumption. Because Pop 2's PD represents a re-default hazard, its LGD should arguably be conditional on re-default. Applying the Censor Lower bound (11.50%) dilutes Pop 2 LGD with zero-loss modified loans. Future iterations should explore a dedicated conditional re-default LGD sub-model.

---

## 4. Staging Framework: IFRS 9 vs. CECL Accounting Distinctions

*   **Accounting Standard Separation:**
    *   **IFRS 9 Standard (Current Engine Basis):** Implements dual-horizon staging: 12-month PD for Stage 1 loans (clean, performing), and Lifetime PD for Stage 2 (significant increase in credit risk / probation) and Stage 3 (default).
    *   **CECL Standard (US GAAP):** Mandates **Lifetime ECL for all loans from origination**, including Stage 1 clean loans.
*   **CECL Order-of-Magnitude Benchmark & Caveat:**
    *   Under CECL lifetime requirements, Stage 1 clean UPB ($27.34B) evaluated at an uncalibrated lifetime PD (~2.47%) and 14.18% LGD yields approximately **~$96M – $97M** ($90M+) for Stage 1 alone.
    *   Adding Stage 2 (~$22M across Pop 1 probation, Pop 1 delinquent, and Pop 2) and Stage 3 ($16.6M) brings total portfolio CECL reserves to approximately **~$135M**.
    *   *Critical Caveat:* Because the out-of-sample backtest demonstrates that the uncalibrated transition matrix systematically over-predicts defaults in benign macroeconomic regimes, this ~2.47% lifetime PD and resulting ~$135M reserve figure must be understood strictly as an uncalibrated order-of-magnitude ceiling, not a validated provision.
*   **Probation Logic as Policy Parameter:** The 12-month probation period is an internal risk policy parameter, not an explicit accounting mandate. Shifting recently delinquent loans into Stage 2 addresses the memoryless bias of Markov matrices. The elevated Stage 2 lifetime PD must be empirically re-calibrated across vintages rather than hardcoded.
*   **EAD, Amortization & Discounting:** The current engine uses snapshot UPB as Exposure at Default (EAD). A production-grade build requires contractual amortization schedules, voluntary prepayment SMM curves, and effective interest rate (EIR) discounting to present value.

---

## 5. Model Gates, Acceptance Rules & Statistical Credibility

*   **Pre-Determined Dual Acceptance Rule:**
    *   Acceptance criteria must be locked *ex-ante* before execution to prevent post-hoc boundary manipulation.
    *   $$\text{\textbf{Dual Acceptance Gate: Fail if either test fails: }} |z| > 2.0 \quad \text{\textbf{OR}} \quad |\text{Relative Error}| > 15\%$$
    *   This rule is enforced **per risk state** and for the **portfolio total**.
*   **House Convention Justification & Overdispersion Note:**
    *   The 15% relative error threshold is an internal **house convention / engineering heuristic**, not a regulatory standard.
    *   *Overdispersion Note:* In residential mortgage portfolios, loan defaults exhibit spatial, regional, and macroeconomic clustering (overdispersion relative to theoretical independent Poisson/binomial trials). On large portfolios ($N \approx 195,000$), a pure $Z$-score can trigger statistical rejection on economically immaterial shifts. Pairing a 15% percentage error tolerance with the statistical $Z$-score prevents premature rejection driven solely by large-sample sensitivity, while the dual requirement ensures that models exhibiting severe statistical drift or large percentage errors fail.
*   **Application to Current Engine (Specification D):**
    *   Portfolio Total: Expected = 1,024.7, Actual = 912.
    *   $Z = -3.94\sigma$ (FAILS $|z| > 2.0$). Relative error = 11.0% (PASSES $\le 15\%$).
    *   **Verdict: 🔴 FAIL / RED** (fails the statistical significance test).
    *   Pop 1 Current Clean: Exp = 292.5, Act = 218 ($Z = -4.36\sigma$, Err = 25.5%) $\rightarrow$ 🔴 **FAIL**.
    *   Pop 2 30 DPD: Exp = 61.2, Act = 34 ($Z = -5.08\sigma$, Err = 44.4%) $\rightarrow$ 🔴 **FAIL**.
    *   Pop 2 60 DPD: Exp = 69.0, Act = 58 ($Z = -2.91\sigma$, Err = 15.9%) $\rightarrow$ 🔴 **FAIL**.
    *   Pop 1 Probation: Exp = 128.4, Act = 122 ($Z = -0.57\sigma$, Err = 5.0%) $\rightarrow$ 🟢 **PASS**.
*   **Vintage-Curve Denominator Integrity:**
    *   When constructing cumulative default rate (CDR) / vintage curves over loan seasoning ($a$), two mathematical integrity principles must be enforced:
        1.  **Symmetric Exclusions:** Any cohort filter applied to the default numerator (e.g., censoring loans modified prior to default, or isolating disaster-impacted loans) must be applied identically to the origination denominator.
        2.  **Observable-at-Age Denominators:** Denominators at age $a$ must be restricted to loans that are *observable at age $a$* (loans whose origination period allows observation up to age $a$ prior to the sample cutoff date / censorship, `month_idx(cutoff) - month_idx(orig_period) >= a`). Dividing cumulative defaults by loans that have not reached age $a$ understates default rates, while dividing new defaults by surviving active loans creates a severe upward denominator bias as prepayments shrink the surviving panel.
*   **Rigorous Transition Count Reconciliation:**
    *   Transition matrix auditing must compare the sum of matrix transition counts ($C_{\text{portfolio}}$) directly against the exact row count of `loan_level_transitions` (verifying all 18,587,123 rows match exactly).
    *   *Exact Extraction Query Generating 18,587,123 Rows:*
    ```sql
    CREATE OR REPLACE TABLE loan_level_transitions AS
    WITH State_Sequencing AS (
        SELECT
            p.loan_id,
            p.monthly_reporting_period,
            p.current_actual_upb,
            p.loan_age,
            p.modification_flag,
            p.loan_state AS state_t,
            LEAD(p.loan_state) OVER (
                PARTITION BY p.loan_id ORDER BY p.monthly_reporting_period
            ) AS raw_next_state,
            LEAD(p.monthly_reporting_period) OVER (
                PARTITION BY p.loan_id ORDER BY p.monthly_reporting_period
            ) AS next_period
        FROM truncated_performance p
    ),
    Continuity_Validated AS (
        SELECT
            *,
            CASE
                WHEN month_idx(next_period) - month_idx(monthly_reporting_period) = 1
                THEN raw_next_state
                ELSE NULL
            END AS state_t_plus_1
        FROM State_Sequencing
    )
    SELECT
        t.loan_id,
        t.monthly_reporting_period,
        t.current_actual_upb,
        t.loan_age,
        t.modification_flag,
        t.state_t,
        t.state_t_plus_1,
        2000 + CAST(SUBSTRING(o.loan_id, 2, 2) AS INT) AS orig_year,
        CASE
            WHEN TRY_CAST(o.credit_score AS INT) BETWEEN 740 AND 850 THEN 'High-FICO'
            WHEN TRY_CAST(o.credit_score AS INT) BETWEEN 680 AND 739 THEN 'Mid-FICO'
            WHEN TRY_CAST(o.credit_score AS INT) BETWEEN 300 AND 679 THEN 'Lower-FICO'
            ELSE 'Unknown'
        END AS fico_band
    FROM Continuity_Validated t
    INNER JOIN raw_origination o ON t.loan_id = o.loan_id
    WHERE t.state_t_plus_1 IS NOT NULL
      AND t.state_t IN ('Current', '30_DPD', '60_DPD');

    -- Audit verification query:
    SELECT COUNT(*) FROM loan_level_transitions; -- Yields exactly 18,587,123
    ```
*   **Event-Count Credibility over Heuristics:** Replace arbitrary heuristics (e.g., `n < 100`) with **Wilson score intervals** and formal actuarial credibility weighting to govern state transition fallbacks.

---

## 6. Backtest Design & Out-of-Sample Methodology

*   **Consistent In-Sample vs Backtest Parameters:** Clean-history Stage 1 PD must be unified at **0.1560%** across both the Master Table and out-of-sample backtesting (derived from 323 / 207,061 in the trailing 201712 $\rightarrow$ 2018 window).
*   **Consistent Out-of-Time Training:** Matrix parameters for out-of-sample testing must be trained on all transitions observed strictly on or before the snapshot date (`monthly_reporting_period <= snapshot_date`), eliminating temporal mismatch.
*   **Rolling-Origin Multi-Year Backtests:** Validating on a single benign year (2019) creates regime bias and over-prediction. The testing suite must implement rolling-origin backtests across snapshots 2015, 2016, 2017, and 2018 to evaluate model performance across both normal and stressed years prior to the 202002 pre-COVID cutoff.
*   **Transparent Offsetting Error Disclosure:** Backtest reporting must present granular results by sub-segment (Pop 1 Current, 30 DPD, 60 DPD; Pop 2 Current, 30 DPD, 60 DPD, Modified). Offsetting errors (e.g., Stage 1 under-prediction masking Pop 2 over-prediction) must be documented explicitly.
*   **Consistent 12-Month PD Input:** Backtest predictions must strictly evaluate 12-month default probabilities against 12-month realized outcomes, avoiding the misapplication of lifetime PDs to single-year backtests.

---

## 7. Data Ingestion, Macro Screens & Administrative Removals

*   **Multi-Vintage Minimum:** Production model training requires ingesting multiple cohorts spanning across business cycles (minimum 2010–2016 cohorts) to stabilize delinquency event counts and model seasoning.
*   **Macroeconomic Conditioning / Stress Overlays:** Because all available sample cohorts (2010–2016) reflect post-crisis economic expansion, the baseline matrix cannot forecast stressed conditions without explicit macro overlays or historical stress benchmarks (e.g., 2008 crisis proxy).
*   **Disaster & Calendar Effect Screens:** The pipeline must incorporate Freddie Mac disaster tracking flags or state-by-year screens to isolate catastrophic weather events (e.g., 2017 hurricanes Harvey/Irma in FL/TX/PR) from core underwriting credit risk.
*   **Explicit Schema Mapping & Audit Status:**
    *   *Current Implementation:* Basic sample-line field assertions and 32-column padded schema mapping are implemented in `src/ingestion.py`.
    *   *Remaining Gap:* Automated dynamic schema switching across historical variable-width releases (legacy 26/28-column vs modern 32-column flat files) remains a partial implementation requiring automated delimiter parsing across all ingested chunks.
*   **Freddie Mac Zero Balance Removal Codes (Administrative Exits):**
    *   `01`: Prepaid or Matured (neutral borrower payoff).
    *   `02`: Third-Party Sale (credit liquidation).
    *   `03`: Short Sale / Charge-off (credit liquidation).
    *   `06`: Repurchase (administrative repurchase).
    *   `09`: REO Disposition (credit liquidation).
    *   `15`: Whole Loan Sale / Note Sale (secondary market portfolio sale).
    *   `16`: **Reperforming Loan (RPL) Securitization / RPL Sale** (bulk transfer exit).
    *   *Informative Censoring:* Codes `15` and `16` must be treated as informative censoring rather than neutral borrower payoffs (`01`), because secondary market loan sales select for non-performing or reperforming assets.

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
| **Gate 1** | Raw Ingestion & Schema Defense | Padded 32-column mappings; pre-run sample assertions in `src/ingestion.py` | Automated assertion test passes; variable-width dynamic parser pending | 🟡 **Partial** |
| **Gate 2** | Layer 1 Absorbing Censoring | Censor loans at first modification; `NOT EXISTS` query logic | 1,956 loans censored; zero post-mod transitions in Pop 1 | 🟢 **Done** |
| **Gate 3** | Two-Factor Bounded LGD & Tail | Discrete hazard chaining; 48m headline (43% re-def $\rightarrow$ 14.18% LGD) & 36m sensitivity | Dollar-weighted first default UPB; explicit liquidation share caveat | 🟢 **Done** |
| **Gate 4** | Pop 2 Segmentation & Staging | Active modified cohort isolation; double-count LGD protection | Active modified loans isolated; 11.50% base LGD; 10.48% hazard floor | 🟢 **Done** |
| **Gate 5** | IFRS 9 Probation Staging | 12m probation for recent delinquencies; empirical ex-hurricane lifetime PD | Performing loans with recent delinquency reclassified to Stage 2 | 🟢 **Done** |
| **Gate 6** | Out-of-Sample Backtesting | Frozen parameter scoring; transparent offsetting error disclosure | Dual Acceptance Gate: Uncalibrated matrix fails ($Z = -3.94\sigma$, Err = 11.0%) | 🔴 **Done–FAILED** |
| **Gate 7** | Master Table Reconciliation | Mutually exclusive census; exact row-by-row $\text{UPB} \times \text{PD} \times \text{LGD}$ tie | Exact portfolio UPB and loan count match; penny-accurate ECL sum | 🟢 **Done** |
| **Gate 8** | Rolling-Origin Backtesting & Dual Gate | Multi-year backtests (2015–2018 snapshots); observable-at-age denominators | Dual Rule: Fail if $|z| > 2.0$ OR error > 15% (per state and total) | ⏸️ **Frozen (Phase 4)** |
| **Gate 9** | EAD Amortization & Cash Flow | CPR/SMM prepayment curves; EIR cash flow discounting | Discounted cash flow engine reconciling to UPB | ⏸️ **Frozen (Phase 4)** |
| **Gate 10** | Macroeconomic Conditioning | Cox hazard overlays conditioned on state unemployment / HPI | CCAR/DFAST stress scenario forecasting capabilities | ⏸️ **Frozen (Phase 4)** |
