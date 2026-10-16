# Tableau Public Build Specification: Residential Mortgage Credit Risk Engine
## 4-Tab Executive Dashboard Construction & Schema Catalog Guide

**Target Canvas:** Tableau Public Desktop / Web Authoring  
**Dashboard Sizing:** Fixed Size: `1440 x 900 px` (Standard Desktop / Presentation Display)  
**Data Directory:** `output/tableau/` (7 aggregated, tidy CSV files generated via `scratch/export_tableau.py`)  
**Data Privacy:** Zero loan-level identifiers or non-aggregated PII (Aggregated cohorts & census totals only)  
**Synchronized Remote Repo:** [https://github.com/comNayaK/DA-RiskAnalysis](https://github.com/comNayaK/DA-RiskAnalysis) (Release Tag: `v0.4-dashboard-data`)

---

## 1. Schema Catalog & Scale Reference (The Critical Scale Rule)

> [!WARNING]
> ### The 100× Scale Trap: Fraction vs. Percentage Points
> In Tableau, formatting a raw number stored as **percentage points** (`14.18` or `0.2034`) using default **Percentage (`0.0%`)** multiplies the value by 100, displaying **`1418%`** or **`20.34%`**!
> Always inspect the scale classification below before formatting measures:
> * **Fraction (`0.00156` to `1.0`):** Use default Tableau **Percentage** format (`0.00%`).
> * **Percentage Points (`0.01` to `79.49`):** Use Tableau **Number (Custom)** with suffix `"%"` (e.g., `0.00"%"`), OR divide by 100 in a Calculated Field before using Percentage formatting.

### Comprehensive Catalog of All 7 CSV Datasets

| File Name | Field Name | Data Type | Scale Classification | Raw Sample Value | Tableau Default Format | Formatted Display |
|---|---|---|---|---|---|---|
| **`ecl_master.csv`** | `segment` | String (Dim) | Categorical State | `'Pop 1: Current (Clean)'` | None | Default |
| | `stage` | String (Dim) | IFRS 9 Stage | `'Stage 1'` | None | Default |
| | `loan_count` | Integer (Measure) | Count | `166009` | Number (Whole) | `166,009` |
| | `total_upb` | Float (Measure) | Currency ($) | `27336521237.52` | Currency (Custom) | `$27.34B` / `$#,##0` |
| | `pd` | Float (Measure) | **Fraction** | `0.00156` | **Percentage** (`0.0000%`) | `0.1560%` |
| | `lgd` | Float (Measure) | **Fraction** | `0.1418` | **Percentage** (`0.00%`) | `14.18%` |
| | `calculated_ecl` | Float (Measure) | Currency ($) | `6047057.19` | Currency (Custom) | `$6,047,057` |
| | `ecl_share_pct` | Float (Measure) | **Points** | `13.4161` | **Number (Custom)** (`0.00"%"`) | `13.42%` |
| **`ecl_scenarios.csv`** | `scenario_id` | String (Dim) | Identifier | `'SCEN_04'` | None | Default |
| | `scenario_name` | String (Dim) | Scenario Title | `'Headline Scenario (48m Tail, 14.18% LGD)'` | None | Default |
| | `total_ecl` | Float (Measure) | Currency ($) | `45073223.87` | Currency (Custom) | `$45,073,224` |
| | `description` | String (Dim) | Methodology Note | `'Single headline reserve basis...'` | None | Default |
| | `delta_vs_headline` | Float (Measure) | Currency ($) | `0.0` / `-9275989.35` | Currency (Custom) | `+$#,##0;-$#,##0;$0` |
| | `pct_delta_vs_headline`| Float (Measure) | **Points** | `-20.5798` / `+15.2770` | **Number (Custom)** (`+0.0"%";-0.0"%";0.0"%"`) | `-20.6%` / `+15.3%` |
| **`lgd_bounds.csv`** | `specification` | String (Dim) | Specification | `'Pop 1 Headline (48m Re-default Tail)'` | None | Default |
| | `category` | String (Dim) | Bound Grouping | `'Model Specification'` | None | Default |
| | `horizon_months` | Integer (Dim) | Horizon Months | `48` | Number (Whole) | `48m` |
| | `p_liquidation_lower` | Float (Measure) | **Fraction** | `0.355463` | **Percentage** (`0.0%`) | `35.5%` |
| | `p_liquidation_upper` | Float (Measure) | **Fraction** | `0.447483` | **Percentage** (`0.0%`) | `44.7%` |
| | `severity` | Float (Measure) | **Fraction** | `0.3132` | **Percentage** (`0.00%`) | `31.32%` |
| | `lgd_lower` / `lgd_upper`| Float (Measure) | **Fraction** | `0.1150` / `0.1360` | **Percentage** (`0.00%`) | `11.50%` / `13.60%` |
| | `base_lgd` | Float (Measure) | **Fraction** | `0.1150` | **Percentage** (`0.00%`) | `11.50%` |
| | `tail_addon` | Float (Measure) | **Fraction** | `0.0268` | **Percentage** (`0.00%`) | `2.68%` |
| | `modeled_lgd` | Float (Measure) | **Fraction** | `0.1418` | **Percentage** (`0.00%`) | `14.18%` |
| **`vintage_curves.csv`** | `orig_year` | Integer (Dim) | Cohort Vintage | `2010` (to `2016`) | Number (Whole, no comma) | `2010` |
| | `loan_age` | Integer (Dim) | Age in Months | `24` (0 to 121) | Number (Whole) | `24m` |
| | `new_defaults_at_age`| Integer (Measure) | Cohort Defaults | `29` | Number (Whole) | `29` |
| | `observable_loans` | Integer (Measure) | Observable Exposure| `50000` | Number (Whole) | `50,000` |
| | `cumulative_defaults`| Float (Measure) | Cumulative Count | `343.0` | Number (Whole) | `343` |
| | `loans_originated` | Integer (Measure) | Fixed Origination | `50000` | Number (Whole) | `50,000` |
| | `per_original_loan_incidence_pct` | Float (Measure) | **Points** | `0.0580` | **Number (Custom)** (`0.000"%"`) | `0.058%` |
| | `monthly_hazard_pct` | Float (Measure) | **Points** | `0.0580` | **Number (Custom)** (`0.000"%"`) | `0.058%` |
| | `cumulative_incidence_per_observable_pct` | Float (Measure) | **Points** | `0.6838` | **Number (Custom)** (`0.000"%"`) | `0.684%` |
| | `cumulative_default_rate_pct` | Float (Measure) | **Points** | `0.6838` | **Number (Custom)** (`0.000"%"`) | `0.684%` |
| **`backtest_rolling.csv`**| `snapshot` | Integer (Dim) | As-Of Snapshot | `201812` (201512–201812) | Number (Whole, no comma) | `201812` |
| | `eval_year` | Integer (Dim) | Outcome Year | `2019` (2016–2019) | Number (Whole, no comma) | `2019` |
| | `parameterization_mode`| String (Dim) | Model Mode | `'trailing'` / `'pooled'` | None | Default |
| | `segment` | String (Dim) | Risk State | `'Pop 1: Current (Clean)'` | None | Default |
| | `loans_n` | Integer (Measure) | Evaluated Loans | `187493` | Number (Whole) | `187,493` |
| | `actual_defaults` | Integer (Measure) | Realized Defaults | `218` | Number (Whole) | `218` |
| | `model_pd` | Float (Measure) | **Fraction** | `0.001513` | **Percentage** (`0.0000%`) | `0.1513%` |
| | `pd_basis` | String (Dim) | Historical Source | `'0.1513% (313/206839 trailing)'`| None | Default |
| | `expected_defaults` | Float (Measure) | Forecasted Count | `283.72` | Number (Decimal `0.0`) | `283.7` |
| | `z_score` | Float (Measure) | Standard Errors | `-3.90` | Number (Custom) (`0.00"σ"`) | `-3.90σ` |
| | `relative_error_pct` | Float (Measure) | **Points** | `23.16` | **Number (Custom)** (`+0.0"%";-0.0"%";0.0"%"`) | `+23.2%` |
| | `status` | String (Dim) | Test Verdict | `'PASS'` / `'FAIL'` | None | Default |
| | `is_failure` | Boolean (Dim) | Failure Tripwire | `True` / `False` | Boolean | True / False |
| **`transition_matrix_fico.csv`** | `fico_band` | String (Dim) | FICO Segment | `'High-FICO'` / `'Lower-FICO'` | None | Default |
| | `state_t` | String (Dim) | Origin State | `'Current'`, `'30_DPD'`, `'60_DPD'` | None | Default |
| | `state_t_plus_1` | String (Dim) | Transition Dest | `'Default'`, `'Paid_Off'`, etc. | None | Default |
| | `transition_count` | Integer (Measure) | Monthly Transitions| `12284407` | Number (Whole) | `12,284,407` |
| | `transition_prob` | Float (Measure) | **Fraction** | `0.988976` | **Percentage** (`0.00%`) | `98.90%` |
| | `pd_12m_from_state_t` | Float (Measure) | **Fraction** | `0.001324` | **Percentage** (`0.00%`) | `0.13%` |
| | `pd_lifetime_from_state_t` | Float (Measure) | **Fraction** | `0.015056` | **Percentage** (`0.00%`) | `1.51%` |
| **`clean_default_rate_by_year.csv`** | `eval_year` | Integer (Dim) | Calendar Year | `2015` to `2019` | Number (Whole, no comma) | `2015` |
| | `age_bucket` | String (Dim) | Seasoning Cohort | `'01-12m'`, `'25-36m'`, `'85m+'` | None | Default |
| | `active_loans` | Integer (Measure) | Active Census | `50142` | Number (Whole) | `50,142` |
| | `defaults` | Float (Measure) | Realized Defaults | `102.0` | Number (Whole) | `102` |
| | `default_rate_pct` | Float (Measure) | **Points** | `0.2034` | **Number (Custom)** (`0.0000"%"`) | `0.2034%` |

---

## 2. Global Workbook Setup & Essential Calculated Fields

### Importing Data into Tableau Public
1. Open Tableau Public $\rightarrow$ **Connect to Data** $\rightarrow$ **Text file**.
2. Connect to `output/tableau/ecl_master.csv` as the Primary Data Source for Tab 1.
3. For additional tabs, navigate to **Data** $\rightarrow$ **New Data Source** $\rightarrow$ **Text file** and add each CSV independently:
   * Data Source 2: `ecl_scenarios.csv`
   * Data Source 3: `lgd_bounds.csv`
   * Data Source 4: `vintage_curves.csv`
   * Data Source 5: `backtest_rolling.csv`
   * Data Source 6: `transition_matrix_fico.csv`
   * Data Source 7: `clean_default_rate_by_year.csv`

### Standard Calculated Fields to Create

#### In Data Source 1: `ecl_master`
* **`Population Segment`** (Dimension):
  ```tableau
  IF STARTSWITH([segment], 'Pop 1') THEN 'Pop 1: Unmodified / Clean'
  ELSEIF STARTSWITH([segment], 'Pop 2') THEN 'Pop 2: Active Modified'
  ELSEIF STARTSWITH([segment], 'Pop 3') THEN 'Pop 3: Active Default'
  ELSE 'Other'
  END
  ```
* **`UPB Share (Fraction)`** (Measure):
  ```tableau
  [total_upb] / { FIXED : SUM([total_upb]) }
  ```
  *(Format as Percentage: `0.00%`)*
* **`ECL Share (Fraction)`** (Measure):
  ```tableau
  [calculated_ecl] / { FIXED : SUM([calculated_ecl]) }
  ```
  *(Format as Percentage: `0.00%`)*

#### In Data Source 4: `vintage_curves`
* **`Age Bin Label`** (Dimension for 6-Month Hazard Aggregation):
  ```tableau
  CASE INT(([loan_age] - 1) / 6)
      WHEN 0 THEN '01-06m'
      WHEN 1 THEN '07-12m'
      WHEN 2 THEN '13-18m'
      WHEN 3 THEN '19-24m'
      WHEN 4 THEN '25-30m'
      WHEN 5 THEN '31-36m'
      WHEN 6 THEN '37-42m'
      WHEN 7 THEN '43-48m'
      WHEN 8 THEN '49-54m'
      WHEN 9 THEN '55-60m'
      ELSE '60m+'
  END
  ```

#### In Data Source 5: `backtest_rolling`
* **`Tripwire Status Color`** (Dimension):
  ```tableau
  IF [is_failure] = True OR [is_failure] = 'True' THEN 'Fail (Tripwire Breached)'
  ELSE 'Pass (Within Band)'
  END
  ```
* **`Is Portfolio Total`** (Filter Dimension):
  ```tableau
  IF [segment] = 'PORTFOLIO TOTAL' THEN 'Total'
  ELSE 'State-Level'
  END
  ```

#### In Data Source 7: `clean_default_rate_by_year`
* **`Yearly Clean Default Rate (Fraction)`** (Measure):
  ```tableau
  [default_rate_pct] / 100.0
  ```
  *(Format as Percentage: `0.0000%`)*

---

## 3. Step-by-Step Dashboard Build Specification

---

### TAB 1: Portfolio Staged Provisions & Sensitivity Bounds
* **Dashboard Title:** `PORTFOLIO STAGED PROVISIONS & POLICY BOUNDS (DECEMBER 2019)`
* **Canvas Size:** Fixed `1440 x 900 px`
* **Background Color:** `#F8F9FA` (Clean Slate Light)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│  KPI 1: ACTIVE PORTFOLIO     KPI 2: HEADLINE IFRS 9 ECL   KPI 3: STAGE 2 PROBATION   KPI 4: POP 2 ASYMMETRY  │
│  $28.71B UPB (174,293 Loans) $45.07M (0.1560% Clean PD)   +$9.28M (+25.9% Reserve)   13.54% ECL on 1.16% UPB │
├──────────────────────────────────────────────────────────┬───────────────────────────────────────┤
│  SHEET 1.1: 9-SEGMENT MASTER PROVISIONING TABLE          │  SHEET 1.2: EXPOSURE VS RESERVE SHARE │
│  (Cross-Tab with Segment, UPB, PD, LGD, ECL, Share)      │  (100% Stacked Bar comparing UPB vs ECL)│
├──────────────────────────────────────────────────────────┼───────────────────────────────────────┤
│  SHEET 1.3: POLICY & PARAMETER SENSITIVITY GRID          │  SHEET 1.4: BOUNDED LGD & TAIL CHAIN  │
│  (Horizontal Bar Chart bounded $35.80M – $51.96M)        │  (Step-down Bar: 11.50% Base + 2.68% Tail)│
└──────────────────────────────────────────────────────────┴───────────────────────────────────────┘
```

#### Top KPI Banner (4 Tiled Text/Metric Cards Across Top: Height 90px)
1. **Card 1 (Portfolio Scale):**  
   Header: `ACTIVE PORTFOLIO (201912)` $\rightarrow$ Metric: **`$28.71B`** $\rightarrow$ Subtext: `174,293 Active Loans ($28,708,141,481 UPB)`
2. **Card 2 (Headline Provision):**  
   Header: `HEADLINE IFRS 9 RESERVE` $\rightarrow$ Metric: **`$45.07M`** $\rightarrow$ Subtext: `$45,073,224 (0.1560% Stage 1 Clean PD)`
3. **Card 3 (Isolated Probation Charge):**  
   Header: `STAGE 2 PROBATION IMPACT` $\rightarrow$ Metric: **`+$9.28M`** $\rightarrow$ Subtext: `+$9,275,977 across 4,314 Probation Loans (9.510% PD)`
4. **Card 4 (Pop 2 Risk Asymmetry):**  
   Header: `POP 2 RISK CONCENTRATION` $\rightarrow$ Metric: **`13.54%`** $\rightarrow$ Subtext: `$6.10M ECL concentrated in 1.16% of UPB ($334.14M)`

#### Sheet 1.1: `T1_Master_Provisioning_Table`
* **Data Source:** `ecl_master`
* **Rows:** `Population Segment`, `stage`, `segment`
* **Columns:** `Measure Names`
* **Measure Values Shelf:**
  * `SUM(loan_count)` $\rightarrow$ Format: `#,##0`
  * `SUM(total_upb)` $\rightarrow$ Format: Currency `$#,##0`
  * `AGG(UPB Share (Fraction))` $\rightarrow$ Format: Percentage `0.00%`
  * `AVG(pd)` $\rightarrow$ Format: Percentage `0.0000%`
  * `AVG(lgd)` $\rightarrow$ Format: Percentage `0.00%`
  * `SUM(calculated_ecl)` $\rightarrow$ Format: Currency `$#,##0`
  * `SUM(ecl_share_pct)` $\rightarrow$ Format: Number (Custom) `0.00"%"`
* **Marks:** Square / Text Table
* **Color Shelf:** `SUM(calculated_ecl)` on Color $\rightarrow$ Palette: **Orange-Blue Diverging** (Reversed: Blue low, Amber/Orange high for elevated reserves).
* **Tooltip:**  
  ```text
  Segment: <segment>
  IFRS 9 Stage: <stage>
  Active UPB: <SUM(total_upb)> (<AGG(UPB Share (Fraction))>)
  Assigned PD: <AVG(pd)> | Assigned LGD: <AVG(lgd)>
  Calculated ECL: <SUM(calculated_ecl)> (<SUM(ecl_share_pct)> of Total)
  ```

#### Sheet 1.2: `T1_Exposure_vs_Reserve_Concentration`
* **Data Source:** `ecl_master`
* **Rows:** `Measure Names` (Filtered to `AGG(UPB Share (Fraction))` and `AGG(ECL Share (Fraction))`)
* **Columns:** `Measure Values`
* **Marks:** Bar (100% Stacked)
* **Color Shelf:** `Population Segment`
  * `Pop 1: Unmodified / Clean`: Slate Blue (`#2B4C7E`)
  * `Pop 2: Active Modified`: Vivid Amber (`#D9822B`)
  * `Pop 3: Active Default`: Crimson (`#C23934`)
* **Label Shelf:** `AGG(UPB Share (Fraction))` and `AGG(ECL Share (Fraction))` with `Population Segment`.
* **Visual Takeaway:** Highlights that Pop 2 accounts for **1.16% of UPB but 13.54% of ECL**, while Pop 3 accounts for **0.41% of UPB but 36.89% of ECL**.

#### Sheet 1.3: `T1_Policy_Sensitivity_Grid`
* **Data Source:** `ecl_scenarios`
* **Rows:** `scenario_name` (Sorted descending by `SUM(total_ecl)`)
* **Columns:** `SUM(total_ecl)`
* **Marks:** Bar
* **Color Shelf:** `SUM(pct_delta_vs_headline)` on Color $\rightarrow$ Diverging Red-Green (Red for elevated reserves, Green for reserve releases, Grey for Headline).
* **Reference Line (Analytics Pane):**  
  * Add Reference Line on `SUM(total_ecl)` $\rightarrow$ Value: Constant **`45073224`**  
  * Label: Custom $\rightarrow$ `Headline: $45.07M`  
  * Line formatting: Bold Black Dashed line.
* **Label Shelf:** `SUM(total_ecl)` (Format: Currency Millions `$0.00M`) and `SUM(pct_delta_vs_headline)` (Format: `+0.0"%";-0.0"%"`).

#### Sheet 1.4: `T1_LGD_Bounds_and_Tail_Chaining`
* **Data Source:** `lgd_bounds`
* **Filter:** `category = 'Model Specification'`
* **Rows:** `specification`
* **Columns:** `AVG(modeled_lgd)`
* **Marks:** Bar
* **Color Shelf:** `AVG(modeled_lgd)` (Sequential Blue ramp).
* **Reference Line 1:** Constant `0.1150` $\rightarrow$ Label: `Base Resolved LGD (11.50%)`.
* **Reference Line 2:** Constant `0.1418` $\rightarrow$ Label: `Pop 1 Headline LGD (14.18%)`.
* **Annotation Callout Box:**  
  > `"Latent Re-Default Tail Formula: 33.24% Mod × 42.94% Re-Def × 60.00% Liq × 31.32% Severity = +2.68% Add-on. Pop 2 receives base 11.50% LGD to avoid tail double-counting."`

---

### TAB 2: Vintage Hazard & Seasoning Curves
* **Dashboard Title:** `VINTAGE HAZARD CURVES & SYMMETRIC SEASONING (2010–2016 COHORTS)`
* **Canvas Size:** Fixed `1440 x 900 px`

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│  CALLOUT BANNER: SYMMETRIC DENOMINATOR INTEGRITY & OBSERVABLE COHORT CONTROLS                    │
│  "Cumulative default rates at age 'a' are strictly anchored to initial origination UPB_0         │
│  observable at age 'a' (6,009 defaults retained across 350,000 loans vs 4,164 under naive drop)" │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│  SHEET 2.1: SYMMETRIC CUMULATIVE DEFAULT INCIDENCE BY COHORT (2010–2016)                         │
│  (Continuous Line Chart: Age 0–120m, colored by Origination Vintage 2010–2016)                  │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│  SHEET 2.2: 6-MONTH BINNED MARGINAL HAZARD PROFILE (ACROSS ALL COHORTS)                          │
│  (Stepped Bar/Area Chart showing default acceleration peaking at 13–30m before decelerating)     │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### Top Callout Banner (Directly on Canvas)
* **Background:** Pale Blue-Grey (`#EEF3F8`), Border: `#3B6998`
* **Text (Bold 11pt):**  
  `"Symmetric Denominator Control: Cumulative default rates at age 'a' are strictly anchored to initial origination UPB_0 observable at age 'a' (month_idx(202002) - month_idx(first_payment_date) + 1 >= a), retaining loans that modified after default (6,009 total defaults vs 4,164 under naive drop) to eliminate prepayment division bias."`

#### Sheet 2.1: `T2_Cumulative_Default_Incidence_Curves`
* **Data Source:** `vintage_curves`
* **Columns:** `loan_age` (Continuous Dimension, Range: `0` to `120`)
* **Rows:** `AVG(cumulative_incidence_per_observable_pct)`
* **Marks:** Line (Size: Medium-Thin)
* **Color Shelf:** `orig_year` (Dimension) $\rightarrow$ Palette: **Tableau 10** or **Viridis / Blue-Teal** (Ensure vintage 2010 contrasts against 2016).
* **Tooltip:**  
  ```text
  Origination Vintage: <orig_year>
  Loan Age: <loan_age> Months
  Cumulative Defaults: <SUM(cumulative_defaults)>
  Observable Exposure: <SUM(observable_loans)>
  Cumulative Incidence: <AVG(cumulative_incidence_per_observable_pct)>%
  ```

#### Sheet 2.2: `T2_Binned_Marginal_Hazard_Profile`
* **Data Source:** `vintage_curves`
* **Columns:** `Age Bin Label` (Dimension: `'01-06m'`, `'07-12m'`, ..., `'55-60m'`)
* **Rows:** `SUM(new_defaults_at_age)`
* **Marks:** Bar
* **Color Shelf:** `SUM(new_defaults_at_age)` (Teal-to-Dark Blue sequential).
* **Annotation on Month 13–30 Bins:**  
  > `"Peak Hazard Window: Monthly default incidence accelerates from 0.052% at 1–6m to peak at 0.190%–0.200% during months 13–30 before seasoning down to 0.121% at 60m."`

---

### TAB 3: Rolling Backtest Diagnostics
* **Dashboard Title:** `OUT-OF-SAMPLE BACKTEST DIAGNOSTICS & MULTI-YEAR ROLLING ORIGIN`
* **Canvas Size:** Fixed `1440 x 900 px`

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│  VERDICT BANNER: PRE-SET DUAL TRIPWIRE RULE (|Z| <= 2.0 AND |REL ERR| <= 15%)                    │
│  "FINDING: Fails per-state rule in all 4 snapshots. 2017 under-predicted (-42.9% hurricane shock);│
│   2016, 2018, 2019 over-predicted (+4.8% aggregate, failing on Pop 1 Clean at +23.2%, Z = -3.90σ)"│
├──────────────────────────────────────────────────────────┬───────────────────────────────────────┤
│  SHEET 3.1: 201812 SPECIFICATION COMPARISON              │  SHEET 3.2: STATE-LEVEL SCORECARD     │
│  (Grouped Bar: Expected vs 912 Actual across Specs A–D)  │  (Diverging Z-Scores with [-2, +2] Band)│
├──────────────────────────────────────────────────────────┴───────────────────────────────────────┤
│  SHEET 3.3: MULTI-YEAR ROLLING BACKTEST TIMELINE (201512–201812 SNAPSHOTS)                       │
│  (Combo Chart: Expected Defaults Bars vs Actual Defaults Line + Hurricane & Lag Annotations)     │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### Top Verdict Banner
* **Background:** Light Amber/Beige (`#FEF9E7`), Border: `#F39C12`
* **Text (Bold 11pt, Navy `#1F3A5F`):**  
  `"GOVERNANCE AUDIT VERDICT: Aggregate PASS, State-Level FAIL. Under measured dynamic trailing parameters (Spec D), 201812 expected defaults are 958.2 vs 912 actual (Z = -1.64σ, +4.8% error), passing total tolerance. However, Pop 1 Clean breaches the pre-set rule (+23.2% error, Z = -3.90σ). Across all 4 rolling snapshots (2015–2018), models fail due to macro shocks and trailing phase lag."`

#### Sheet 3.1: `T3_201812_Specification_Comparison`
* **Data Source:** `backtest_rolling`
* **Filter:** `snapshot = 201812`, `segment = 'PORTFOLIO TOTAL'`
* **Columns:** `parameterization_mode`
* **Rows:** `SUM(expected_defaults)`
* **Marks:** Bar
* **Reference Line:** Constant **`912`** $\rightarrow$ Label: `Realized Actual Defaults = 912`.
* **Tooltip / Labels:**  
  * `Trailing Mode`: 958.2 expected ($Z = -1.64\sigma$, Rel Err = +4.8%)
  * `Pooled Mode`: 1,124.7 expected ($Z = -6.92\sigma$, Rel Err = +18.9%)

#### Sheet 3.2: `T3_State_Level_Tripwire_Scorecard`
* **Data Source:** `backtest_rolling`
* **Filter:** `snapshot = 201812`, `parameterization_mode = 'trailing'`, `Is Portfolio Total = 'State-Level'`
* **Rows:** `segment` (Sorted ascending by `z_score`)
* **Columns:** `AVG(z_score)`
* **Marks:** Bar
* **Color Shelf:** `Tripwire Status Color`  
  * `Pass (Within Band)`: Forest Green (`#2CA02C`)  
  * `Fail (Tripwire Breached)`: Firebrick Red (`#D62728`)
* **Analytics Pane Shaded Band:**  
  * Add Reference Band on `AVG(z_score)` $\rightarrow$ From `-2.0` to `+2.0`  
  * Shading: Light Olive Green (`#E8F5E9`), Border: `#4CAF50`  
  * Label: `Acceptance Band (-2.0σ to +2.0σ)`
* **Annotation on `Pop 1: Current (Clean)` Bar:**  
  > `"Clean Breach: Z = -3.90σ, Rel Err = +23.2% (283.7 expected vs 218 actual). Triggers state-level FAIL."`

#### Sheet 3.3: `T3_Multi_Year_Rolling_Timeline`
* **Data Source:** `backtest_rolling`
* **Filter:** `segment = 'PORTFOLIO TOTAL'`, `parameterization_mode = 'trailing'`
* **Columns:** `eval_year` (Discrete: `2016`, `2017`, `2018`, `2019`)
* **Rows:** `SUM(expected_defaults)` and `SUM(actual_defaults)` $\rightarrow$ Dual Axis
  * Axis 1 (`expected_defaults`): Bar Mark, Slate Grey
  * Axis 2 (`actual_defaults`): Line Mark with Circle Data Points, Crimson
* **Callout Annotations:**
  * **Above 2017:** `"2017 Hurricane Shock: 1,366 Actual vs 955.7 Expected (Z = +14.55σ, -42.9% Error). Severe under-prediction in FL/TX/PR."`
  * **Above 2018:** `"Mechanical Phase-Lag: 1,011 Actual vs 1,427.5 Expected (Z = -12.05σ, +29.2% Error). Trailing model absorbed 2017 hurricane spike into base rate."`
  * **Above 2019:** `"Aggregate PASS: 912 Actual vs 958.2 Expected (Z = -1.64σ, +4.8% Error), but state-level breach in Pop 1 Clean."`

---

### TAB 4: FICO Monotonicity & Pop 1 Clean Trends
* **Dashboard Title:** `FICO MONOTONICITY AUDIT & DEMOGRAPHIC VS CALENDAR TRENDS`
* **Canvas Size:** Fixed `1440 x 900 px`

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│  SHEET 4.1: MULTI-VINTAGE MARKOV TRANSITION MATRIX (HEATMAP)                                      │
│  (Origin State_t Rows x Destination State_t+1 Columns, toggle for FICO Band)                     │
├──────────────────────────────────────────────────────────┬───────────────────────────────────────┤
│  SHEET 4.2: HIGH-FICO 60 DPD MONOTONICITY REVERSAL       │  SHEET 4.3: CALENDAR VS AGE DOMINANCE │
│  (Grouped Bar: High-FICO 61.5% vs Lower-FICO 53.05%)     │  (Highlight Table: 2015–2019 by Age)  │
└──────────────────────────────────────────────────────────┴───────────────────────────────────────┘
```

#### Sheet 4.1: `T4_Markov_Transition_Matrix_Heatmap`
* **Data Source:** `transition_matrix_fico`
* **Filter:** `fico_band` (Expose Single-Value Dropdown filter on dashboard: `All-FICO`, `High-FICO`, `Mid-FICO`, `Lower-FICO`)
* **Rows:** `state_t` (`Current`, `30_DPD`, `60_DPD`)
* **Columns:** `state_t_plus_1` (`Current`, `30_DPD`, `60_DPD`, `Default`, `Paid_Off`)
* **Marks:** Square
* **Color Shelf:** `AVG(transition_prob)` $\rightarrow$ Palette: Sequential Blue
* **Label Shelf:** `AVG(transition_prob)` (Format: Percentage `0.00%`).

#### Sheet 4.2: `T4_High_FICO_60_DPD_Reversal`
* **Data Source:** `transition_matrix_fico`
* **Filter:** `fico_band` IN (`High-FICO`, `Lower-FICO`), `state_t_plus_1 = 'Default'`
* **Columns:** `state_t` (`Current`, `30_DPD`, `60_DPD`)
* **Rows:** `AVG(pd_12m_from_state_t)`
* **Marks:** Bar
* **Color Shelf:** `fico_band` (High-FICO: `#1F77B4` Blue; Lower-FICO: `#FF7F0E` Amber)
* **Annotation on 60 DPD Cluster:**  
  > `"60 DPD Non-Monotonicity Reversal: High-FICO loans at 60 DPD roll to default at 61.50% vs 53.05% for Lower-FICO loans. Working hypothesis: Prime borrowers at 60+ DPD represent catastrophic life shocks (divorce, business failure) with accelerated foreclosure, whereas subprime borrowers enter workout cure cycles."`

#### Sheet 4.3: `T4_Calendar_Dominance_vs_Age_Heatmap`
* **Data Source:** `clean_default_rate_by_year`
* **Filter:** Exclude `'Total'` from `age_bucket`
* **Rows:** `age_bucket` (`'01-12m'`, `'13-24m'`, `'25-36m'`, `'37-48m'`, `'49-60m'`, `'61-84m'`, `'85m+'`)
* **Columns:** `eval_year` (`2015`, `2016`, `2017`, `2018`, `2019`)
* **Marks:** Square
* **Color Shelf:** `AVG(default_rate_pct)` $\rightarrow$ Palette: **Red-Yellow-Green** (Reversed: Red high default rate, Green low default rate).
* **Label Shelf:** `AVG(default_rate_pct)` (Format: Number Custom `0.0000"%"`, e.g., `0.3725%`).
* **Takeaway Banner (Add Below Table):**  
  `"CALENDAR REGIME DOMINATES LOAN AGE: Pop 1 Clean default rates fell across every single age bucket from 2017 to 2019 (by 49%–70%). A mild 2015 age gradient (0.20% at 1–12m rising to 0.26% at 49–60m) proves the age effect is small but non-zero, and cannot be separated from calendar effects because all cohorts moved synchronously with macro years."`

---

## 4. Typography, Palette & Formatting Standard

* **Dashboard Sizing:** Fixed Size `1440 x 900 px`.
* **Standard Typography:**
  * Dashboard Title: `Trebuchet MS` or `Arial`, Bold, 16pt, Navy `#1F3A5F`
  * Section Headers / Subtitles: Bold, 12pt, Charcoal `#2C3E50`
  * Sheet Titles: Bold, 10pt, Navy `#1F3A5F`
  * KPI Metric Numbers: Bold, 22pt, Charcoal `#1A1A1A`
  * KPI Metric Labels: Regular, 9pt, Dark Slate `#555555`
  * Data Labels / Marks: Regular, 8pt–9pt
* **Color Standards:**
  * Pass Indicator: Forest Green `#2CA02C`
  * Fail / Breach Indicator: Crimson `#D62728`
  * Pop 1 Prime / Clean: Steel Blue `#2B4C7E`
  * Pop 2 Modified / High Risk: Amber `#D9822B`
  * Pop 3 Default: Dark Red `#C23934`
  * Neutral / Reference Lines: Dark Grey `#333333` (Dashed)

---

## 5. Pre-Publish Verification Checklist

Before publishing the workbook to **Tableau Public**:
1. [ ] **Scale Check:** Verify that no percentage measure displays as `1418%` or `2316%`. All percentage points are formatted as Number Custom `0.00"%"` or divided by 100.
2. [ ] **Headline Check:** Tab 1 Headline ECL matches `$45,073,224` across 174,293 loans.
3. [ ] **Backtest Status Check:** Tab 3 scorecard displays **Aggregate PASS, State-Level FAIL** (Pop 1 Clean breaching at $Z = -3.90\sigma$).
4. [ ] **Exposure Anchor Check:** Tab 2 title explicitly confirms symmetric denominator anchors against initial origination $UPB_0$.
5. [ ] **FICO Reversal Check:** Tab 4 displays High-FICO 60 DPD (61.50%) vs Lower-FICO 60 DPD (53.05%).
6. [ ] **GitHub Link Check:** Embed the GitHub repository URL in the dashboard footer:  
   [https://github.com/comNayaK/DA-RiskAnalysis](https://github.com/comNayaK/DA-RiskAnalysis) (Release Tag: `v0.4-dashboard-data`).
