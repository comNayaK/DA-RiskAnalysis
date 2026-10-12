# Residential Mortgage Credit Risk Engine (Phases 1–3)

An econometric credit risk modeling and staged provisioning engine developed on multi-vintage prime residential mortgage cohorts from Freddie Mac Single-Family Loan-Level Datasets.

The engine replaces naive accounting heuristics with an **absorbing Markov transition framework**, a **two-factor bounded LGD model with an empirical re-default tail**, a **three-population segmentation (Pop 1 Unmodified, Pop 2 Active Modified, Pop 3 Default)**, and an **IFRS 9 / CECL stage probation mechanism**.

---

## ⚠️ Model Governance & "Not Validated" Notice

> **IMPORTANT NOTICE:** This repository contains an **internal model development draft** and sensitivity analysis. It has **NOT been independently validated** by an uninvolved Model Risk Management (MRM) function, external auditors, or regulatory review teams under Federal Reserve SR 11-7, OCC 2011-12, or EBA guidelines. Self-development analysis cannot constitute independent validation. 
> 
> The engine is **NOT claimed as production-ready, validated, or regulatory-compliant**. The reported figures (headline ECL of ~$45.07M / $45.23M sensitivity, illustrative scaling of ~$41.80M, and upper bound of ~$51.96M) represent development sensitivity scenarios within an empirical range ($35.80M – $52.00M), not certified provisioning requirements. Crucially, the model **fails its locked ex-ante backtesting acceptance gate** across out-of-time evaluation windows. Scope for Phases 1–3 is strictly frozen.

---

## 📚 Core Documentation

The repository includes two exhaustive governance, econometric, and diagnostic documents:

1. **[`docs/progress_report.md`](docs/progress_report.md): Model Development & Diagnostics Report**
   * Complete portfolio reconciliation ($28.71B UPB, 174,293 active loans at December 2019 `201912`).
   * Master Staged Provisioning Table with exact loan count, UPB, PD, LGD, and ECL breakdowns.
   * Out-of-sample backtest diagnostics (Specifications A–D, binomial variance, relative error formulas).
   * Rolling-origin multi-year backtest results (201512–201812 snapshots).
   * Discrete annual hazard chaining for LGD re-default tails (36m vs 48m horizons).
   * 8-scenario policy sensitivity grid and methodological disclosures.

2. **[`docs/technical_plan_review.md`](docs/technical_plan_review.md): Technical Plan Review & Governance Addendum**
   * Systematic phase gate audit (`Done`, `Done–FAILED`, `Partial`).
   * Locked *ex-ante* acceptance rules: Fail if EITHER $|z| > 2.0$ OR $|\text{Relative Error}| > 15\%$, where $\text{Rel Error} = \frac{\text{Expected} - \text{Actual}}{\text{Expected}}$.
   * Scoped SQL anti-pattern rules (`NOT IN` $\rightarrow$ `NOT EXISTS` across `src/` and committed reproduction scripts).
   * Symmetric vintage curve denominator rules (observable-at-age denominators, origination cohorts).
   * 14-loan reconciliation between raw (`1,970`) and censored (`1,956`) modified loan censuses.

---

## 📊 Headline Numbers & Reproduction Scripts

All headline findings in the reports are strictly reproducible from committed, standalone scripts querying `mortgage_risk.duckdb`:

### 1. Headline ECL ($45.07M) and Sensitivity Grid ($35.80M – $51.96M)
* **Script:** `python3 scratch/regenerate_grid.py`
* **What it reproduces:**
  * Reconciles the 9-row Master Table from `ecl_snapshot`: Total ECL = **$45,073,223.87** (at 0.1560% Clean PD) / **$45,228,278.45** (at 0.1600% sensitivity basis).
  * Stage 1 ECL: $6,047,057.19 (13.42%); Stage 2 ECL: $22,397,943.84 (49.69%); Stage 3 ECL: $16,628,222.83 (36.89%).
  * Pop 2 Provision Burden: $6,103,776.53 (13.54% of total reserve driven by 1.16% of UPB).
  * 8-scenario policy sensitivity grid, including Calibrated Baseline ($35.80M), Censor Upper Bound ($51.96M), and the Recomputed Trailing Scaling Scenario (**$43,701,736.66 / ~$43.7M** via 0.9518x non-Stage-3 scaling; legacy 0.885x / $41.8M noted as erratum).

### 2. 201812 Out-of-Sample Backtest (Specifications A–D)
* **Script:** `python3 scratch/reproduce_backtest.py`
* **What it reproduces:**
  * Measures empirical 2015–2017 historical Pop 2 Current 12-month default rates (2015: 9.71%, 2016: 11.04%, 2017: 8.51%; pooled: **9.64%** [99 / 1,027]).
  * Evaluates Specifications A, B, C, and D against 2019 realized outcomes (194,925 loans, 912 defaults) using exact binomial variance throughout.
  * Demonstrates that **Measured Trailing Spec D yields aggregate pass, state-level FAIL ($Z = -1.64\sigma$, Rel Err = +4.8%)**, failing the locked gate due to a state-level breach in Pop 1 Clean ($Z = -3.90\sigma$, Err = +23.2%). *(Erratum: Legacy frozen Spec D with biased Pop 2 parameters failed at total level: $Z = -4.15\sigma$, Rel Err = +11.5%; fixing Pop 2 moved ECL by only ~2%, with aggregate over-prediction hinging on Pop 1 Clean parameterization).*
  * Demonstrates that **Specs B and C are aggregate passes that FAIL at the state level (🔴 RED)** due to offsetting errors (Pop 2 delinquent buckets breach in all specifications).

### 3. Multi-Year Rolling-Origin Backtest (201512–201812 Snapshots)
* **Script:** `python3 scratch/rolling_backtest.py`
* **What it reproduces:**
  * Dynamically computes Pop 2 empirical PDs (Current, 30 DPD, 60 DPD, Modified) for all four snapshots strictly from data $\le \text{snapshot}$ under both Trailing and Pooled parameterizations.
  * Scores four consecutive annual out-of-time evaluation windows using parameters strictly frozen on data prior to each snapshot date:
    * **Trailing Parameterization:**
      * **201512 $\rightarrow$ 2016:** Actual = 843, Expected = 930.3 ($Z = -3.08\sigma$, Err = +9.4%) $\rightarrow$ 🔴 **FAIL**
      * **201612 $\rightarrow$ 2017:** Actual = 1,366, Expected = 955.7 ($Z = +14.55\sigma$, Err = -42.9%) $\rightarrow$ 🔴 **FAIL**
      * **201712 $\rightarrow$ 2018:** Actual = 1,011, Expected = 1,427.5 ($Z = -12.05\sigma$, Err = +29.2%) $\rightarrow$ 🔴 **FAIL**
      * **201812 $\rightarrow$ 2019:** Actual = 912, Expected = 958.2 ($Z = -1.64\sigma$, Err = +4.8%) $\rightarrow$ 🔴 **FAIL** (Aggregate pass, state-level FAIL on Pop 1 Clean)
    * **Pooled-History Parameterization:**
      * **201512 $\rightarrow$ 2016:** Actual = 843, Expected = 936.2 ($Z = -3.27\sigma$, Err = +10.0%) $\rightarrow$ 🔴 **FAIL**
      * **201612 $\rightarrow$ 2017:** Actual = 1,366, Expected = 1,029.0 ($Z = +11.38\sigma$, Err = -32.7%) $\rightarrow$ 🔴 **FAIL**
      * **201712 $\rightarrow$ 2018:** Actual = 1,011, Expected = 1,259.8 ($Z = -7.75\sigma$, Err = +19.7%) $\rightarrow$ 🔴 **FAIL**
      * **201812 $\rightarrow$ 2019:** Actual = 912, Expected = 1,124.7 ($Z = -6.92\sigma$, Err = +18.9%) $\rightarrow$ 🔴 **FAIL**
  * Evaluates Pop 1 Clean sensitivity on 201812 using long-run pooled Clean PD (0.2089% $\rightarrow$ Expected = 1,066.1, $Z = -5.14\sigma$).
  * Produces an age-bucketed realized-rate table for Current loans across years 2015–2019, demonstrating that calendar year dominates; no age effect is detectable in this data.

### 4. Vintage-Curve Denominator Integrity & 6-Month Binned Incidence
* **Script:** `python3 scratch/reproduce_vintage_curves.py`
* **What it reproduces:**
  * Origination cohort denominators (350,000 across 2010–2016).
  * Symmetric inclusion: restores 1,845 modified-after-default loans to default numerators (6,009 total defaults).
  * Validates subset assertion: zero defaults occur beyond observable cohort horizons prior to 202002.
  * Computes 6-month binned empirical default incidence with exposure defined as $\sum \text{observable loans} / 6.0$, verifying default incidence peaks at 13–30 months (0.190%–0.200%) and declines steadily thereafter.

### 5. 14-Loan Census Reconciliation
* **Script:** `python3 scratch/extract_14_loans.py`
* **What it reproduces:**
  * Reconciles the gap between 1,970 raw modification-flagged loans and 1,956 Layer 1 censored modified loans.
  * Identifies the exact 14 loans modified *at or after* terminal status (9 modified at default, 5 modified at payoff).

---

## 🛠️ Required Data Files & Pipeline Execution

### Data Files Required
This project processes Freddie Mac Single-Family Loan-Level Datasets across 7 multi-vintage cohorts (2010–2016). **No proprietary data files are tracked or included in this repository.**

To rebuild the database from scratch, place the following Freddie Mac flat files in `./data/`:
* **Origination Files:** `data/sample_orig_2010.txt` through `data/sample_orig_2016.txt` (or quarterly research files `historical_data_YYYYQ?.txt`).
* **Performance Files:** `data/sample_svcg_2010.txt` through `data/sample_svcg_2016.txt` (or quarterly research files `historical_data_time_YYYYQ?.txt`).
* **Sample Scope:** Minimum 350,000 origination loans, ~26 million performance records spanning up to the pre-COVID cutoff (`202002`).

### How to Rebuild the Database

1. **Environment Setup:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Ingestion & Layer Construction:**
   ```bash
   # Run full end-to-end pipeline (ingestion, filtering, transition extraction, ECL snapshot):
   python3 main.py --orig "data/sample_orig_*.txt" --svcg "data/sample_svcg_*.txt"
   ```

3. **Verify Pipeline Integrity:**
   ```bash
   # Run test suite to verify schema padding and negative control assertions:
   python3 -m pytest
   ```

---

## 🔍 Known Econometric Limitations

1. **Uncalibrated Macro Conditioning:** The absorbing Markov transition matrix is time-homogeneous and lacks macroeconomic conditioning variables (e.g., regional unemployment, HPI shifts). In benign expansionary periods (2016, 2019), the baseline model over-predicts defaults; in shock periods (2017 hurricanes), it under-predicts.
2. **Offsetting Error Dynamics:** Specification B and C aggregate pass scores are masked by severe offsetting errors between performing and delinquent buckets.
3. **Illustrative Scaling Nature of 0.952x (and Legacy 0.885x):** Scaling non-Stage-3 provisions by 0.9518 pulls reserves to ~$43.7M (vs legacy 0.885x pulling to ~$41.8M), but applying a single 12-month portfolio realization ratio uniformly to lifetime ECL across segments is an illustrative scaling heuristic, not an econometric segment calibration.
4. **CECL Order-of-Magnitude:** Stage 1 clean loans require lifetime ECL under US GAAP CECL (~$96M+), bringing total reserves to ~$135M. This figure represents an uncalibrated theoretical ceiling.
5. **Phase Scope Freeze:** Phases 1–3 scope is strictly frozen. EAD contractual amortization schedules, voluntary prepayment SMM curves, and Phase 4 macroeconomic overlays are deferred to future releases.
