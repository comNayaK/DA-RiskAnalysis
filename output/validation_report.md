# Validation Report and Sensitivities

## 1. Purge & Gap Stats
- Total Loans Originated: 221,854
- Loans Purged due to Modification (<=202002): 1,429 (0.64%)
- Uncertain_Quarantine (Reporting Gap) Share: 0 / 11,066,308 (0.000%, target <1%)

## 2. LGD Outcome Buckets (24m & 36m)
### 24-Month Follow-Up
- Liquidated: 661
- Cured_Active: 540
- Still_In_Default: 247
- Paid_Off: 551
- Admin_Removed: 58
Severity 24m: 0.2915

### 36-Month Follow-Up
- Liquidated: 582
- Still_In_Default: 81
- Cured_Active: 280
- Paid_Off: 386
- Admin_Removed: 46
Severity 36m: 0.3145

- Sum of actual_loss_calculation: 37,466,952.56 (Positive means loss)

## 3. FICO Monotonicity & Cell Count Audit
**Portfolio Counts:**
Current: 10718750, 30_DPD: 65785, 60_DPD: 10123

**High-FICO** (Counts - Cur: 6306482, 30: 14124, 60: 2103)
- 12m PD (Current): 0.0013
- Lifetime PD (Current): 0.0121
- Lifetime PD (30 DPD): 0.0932
- Lifetime PD (60 DPD): 0.5317

**Mid-FICO** (Counts - Cur: 3093407, 30: 23407, 60: 3489)
- 12m PD (Current): 0.0032
- Lifetime PD (Current): 0.0330
- Lifetime PD (30 DPD): 0.1090
- Lifetime PD (60 DPD): 0.4855

**Lower-FICO** (Counts - Cur: 1315451, 30: 28252, 60: 4531)
- 12m PD (Current): 0.0072
- Lifetime PD (Current): 0.0913
- Lifetime PD (30 DPD): 0.1580
- Lifetime PD (60 DPD): 0.4697

## 4. Vintage Curve Shape & Snapshot Reconciliation
- Snapshot Loan Count at 201912: 101239
- Vintage Curve Sample:
   orig_year  loan_age  cumulative_default_rate_pct
0       2014        12                       0.1565
1       2014        24                       0.4219
2       2014        36                       0.6814
3       2014        48                       0.9922
4       2014        60                       1.2013

## 5. Backtest Breakdown (2018 -> 2019)
- Overall Z-Score (Poisson): 1.61 std devs
- FICO Breakdown:
  * High-FICO: Expected=81.2, Actual=95
  * Mid-FICO: Expected=101.7, Actual=120
  * Lower-FICO: Expected=100.6, Actual=103
  * Total Expected (FICO-Bucketed): 283.4 vs Actual: 318
- Age Breakdown:
  * Age Bucket <=24: Expected=0.0, Actual=0
  * Age Bucket 25-48: Expected=0.4, Actual=0
  * Age Bucket >48: Expected=329.4, Actual=318
  * Total Expected (Age-Bucketed): 329.8 vs Actual: 318
  * Age-Bucketed Z-Score (Poisson): -0.65 std devs

## 6. Bias Sensitivities
- Censoring Modifications vs Purging: Retained 221,854 unique loans up to modification date (vs ~220,425 purged).
- LGD Outcomes treating 15/16 as Liquidated: [('Other', 1357), ('Liquidated_or_Sale', 700)]
- Snapshot loans that previously defaulted (Cured): 1159 / 101239
- P(liq) Upper Bound (Count-weighted): 0.6793 (N=1999)
- P(liq) Upper Bound (Dollar-weighted): 0.3009 (Dol=124,605,313)
