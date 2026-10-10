import duckdb
import pandas as pd
import numpy as np
import statsmodels.api as sm
import statsmodels.formula.api as smf

con = duckdb.connect('mortgage_risk.duckdb')
q_vc = """
WITH snaps AS (
    SELECT p.loan_id, CAST(SUBSTRING(p.loan_id, 2, 2) AS INT) + 2000 as vintage,
           CAST(SUBSTRING(CAST(p.monthly_reporting_period AS VARCHAR), 1, 4) AS INT) + 1 as calendar_year,
           CASE WHEN p.loan_age <= 24 THEN '<=24' WHEN p.loan_age <= 48 THEN '25-48' ELSE '>48' END as age_bucket
    FROM clean_monthly_performance p
    WHERE SUBSTRING(CAST(p.monthly_reporting_period AS VARCHAR), 5, 2) = '12' AND p.loan_state = 'Current' AND p.zero_balance_code IS NULL
),
defaults AS (
    SELECT DISTINCT loan_id, CAST(SUBSTRING(CAST(monthly_reporting_period AS VARCHAR), 1, 4) AS INT) as def_year
    FROM clean_monthly_performance WHERE loan_state = 'Default'
)
SELECT s.vintage, s.calendar_year, s.age_bucket, COUNT(DISTINCT s.loan_id) as obs_count, COUNT(DISTINCT d.loan_id) as default_count
FROM snaps s
LEFT JOIN defaults d ON s.loan_id = d.loan_id AND s.calendar_year = d.def_year
WHERE s.calendar_year BETWEEN 2014 AND 2019
GROUP BY s.vintage, s.calendar_year, s.age_bucket
"""
df_vc = con.execute(q_vc).df()
df_fit = df_vc[df_vc['obs_count'] >= 1000].copy()
df_fit['log_obs'] = np.log(df_fit['obs_count'])
model = smf.glm('default_count ~ C(vintage) + C(calendar_year) + C(age_bucket)', data=df_fit, family=sm.families.Poisson(), offset=df_fit['log_obs'])
print(model.fit().summary().tables[1])
