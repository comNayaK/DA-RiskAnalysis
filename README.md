# Residential Mortgage Credit Risk Engine (Phases 1–3)

An institutional-grade credit risk modeling and portfolio provisioning engine developed for GCC risk analytics contexts (e.g., Barclays, JPMC, Standard Chartered). 

The engine implements **First-Default Truncation** to enforce absorbing Markov properties, a **Two-Factor Bounded LGD Framework**, **FICO-Stratified Staged ECL Provisioning**, **Multinomial Bootstrapped Uncertainty** (with LGD sensitivity framing), and **Out-of-Sample Backtesting** using **DuckDB** and **NumPy**.

---

## 🏛️ Methodological Defenses & Institutional Governance

When presenting or defending this architecture before model validation committees or GCC credit risk technical interviewers:

### 1. The Modification Purge Bias Defense
* **The Challenge:** *"By dropping all loans with `modification_flag = 'Y'`, you are purging the highest-risk borrowers right before default, systematically deflating default probabilities (PD) and portfolio ECL."*
* **The Institutional Defense:**
  1. **Contractual Baseline Model:** This engine models the **pure contractual credit risk** of prime residential mortgages under original underwriting standards.
  2. **Markov Stationarity & Memorylessness Violation:** In an absorbing Markov chain, treating a loan modification as a normal "cure" back to `Current` introduces non-Markovian history and creates synthetic cures that corrupt transition probabilities.
  3. **Dual Architecture / TDR Sub-Model:** In Tier-1 bank production environments, modified loans are segregated into a dedicated **Troubled Debt Restructuring (TDR) / Forbearance Sub-Model** with specialized transition matrices, modified cash-flow discount rates, and elevated lifetime default expectations.

### 2. REO Timeline Horizons & Judicial Foreclosure Defense
* **The Challenge:** *"A 24-month post-default follow-up window is too short for judicial foreclosure states (e.g., NY, NJ, FL) where foreclosure proceedings can take 36 to 48 months. Your LGD will miscalculate unresolved foreclosures."*
* **The Institutional Defense:**
  1. **Two-Factor Bounded LGD Framework:** This is precisely why the engine computes a **bounded LGD sensitivity** rather than an unjustified point estimate:
     $$LGD = P(\text{Liquidation} \mid 90+) \times \text{Loss Severity}$$
  2. **Upper Bound Treatment:** Unresolved REOs and lingering delinquent loans (`RA` and `Default`) are explicitly tracked as `Still_In_Default` and included in the numerator of $P(\text{liq})_{\text{upper}}$. This accounts for delayed liquidation as a worst-case loss scenario.
  3. **Dual-Window Cohort Benchmarking:** The engine evaluates both the primary 24-month window ($\le 201712$) and a 36-month sensitivity window ($\le 201612$) to empirically demonstrate how much the bound narrows as judicial resolutions materialize.

---

## ⚠️ Known Limitations & Framing

* **ECL Interval Framing:** The bootstrapped ECL interval is not a pure sampling distribution. Because it incorporates an arbitrary uniform draw between LGD lower and upper bounds, it should be treated as a **sensitivity assumption** mapping the matrix uncertainty combined with LGD bounds.
* **Single Vintage Limitation:** Analyzing a single vintage (e.g., `2014Q1`) artificially tightens the matrix and hides seasoning effects. Macroeconomic conditioning and true vintage analysis require ingesting multiple cohorts spanning across business cycles (e.g., 2010–2018).
* **Backtest Directionality:** The backtest results should be treated as an explicit acceptance gate (e.g., traffic-light band). Currently, a TTC homogeneous matrix ignores loan age seasoning, which can systematically underpredict realized defaults. Passing the backtest requires analyzing age-bucketed gaps.

---

## ⚙️ Critical Execution Optimizations

This codebase incorporates three critical execution and architecture fixes:

1. **FICO-Stratified ECL Vectorization (Section 4.4):**
   * *Problem:* Applying a single portfolio-wide Markov PD to the snapshot and grouping by FICO merely shows exposure-weighted portfolio averages.
   * *Resolution:* The engine builds segmented absorbing Markov matrices for each FICO band (`High-FICO`, `Mid-FICO`, `Lower-FICO`), extracts band-specific 12-month and Lifetime PD vectors, and maps them to each individual loan before ECL calculation.
2. **High-Speed DuckDB 3D Tensor Construction (Section 5.2):**
   * *Problem:* Constructing an $(n\_loans, 3, 5)$ transition count tensor via Python/Pandas `iterrows()` over millions of rows causes CPU throttling and Out-Of-Memory (OOM) crashes.
   * *Resolution:* Pushes transition count aggregation down into DuckDB first (`GROUP BY loan_id, state_t, state_t_plus_1`), then performs vectorized index population directly into a dense NumPy array.
3. **Padded 32-Column Freddie Mac Schema (Section 2.1):**
   * *Problem:* Modern Freddie Mac flat files contain 32 pipe-delimited columns. Using legacy 26/28-column schemas with `header=False` triggers hard DuckDB parsing errors.
   * *Resolution:* Both `ORIG_COLUMNS_32` and `PERF_COLUMNS_32` explicitly define all 32 fields.

---

## 📁 Repository Structure

```
├── data/                  # Freddie Mac raw pipe-delimited files (.txt)
├── src/
│   ├── config.py          # State space, FICO bands, temporal cutoffs & schemas
│   ├── db.py              # DuckDB connection & month_idx integer-division macro
│   ├── ingestion.py       # Section 0 pre-run audit & Layer 0 ingestion
│   ├── layers.py          # Clean panel, truncation, transitions, vintages, snapshot
│   ├── lgd.py             # Two-Factor Bounded LGD (24m & 36m follow-up)
│   ├── markov.py          # Absorbing Markov engine & FICO-stratified ECL
│   ├── diagnostics.py     # Wilson intervals, monotonicity & fast 3D tensor bootstrap
│   └── backtest.py        # Out-of-sample forward-looking model validation (2018 -> 2019)
├── main.py                # End-to-end execution pipeline
├── requirements.txt       # Python library dependencies
└── README.md              # Project documentation
```

---

## 🚀 Quickstart

### 1. Set Up Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Place Freddie Mac Data
Place your origination and performance files in `./data/`:
* Sample files: `data/sample_orig_2014.txt`, `data/sample_svcg_2014.txt`
* Or full research files: `data/historical_data_2014Q1.txt`, `data/historical_data_time_2014Q1.txt`

### 3. Run Pipeline
```bash
# Run on sample files
python3 main.py --orig "data/sample_orig_*.txt" --svcg "data/sample_svcg_*.txt"

# Run on historical research files
python3 main.py --orig "data/historical_data_????Q?.txt" --svcg "data/historical_data_time_????Q?.txt"
```
