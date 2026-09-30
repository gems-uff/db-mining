# Statistical audit: vulnerability severity and temporal outcomes

Audit date: 2026-09-03. Source files were read without modification.

## Data and units of analysis

Question A uses one row per distinct vulnerability `reference` (CVE or GHSA), matching the study count of 62. Although the database can contain several vulnerable releases and, for four references, more than one package association, severity and dates have no within-reference conflicts. Six vulnerabilities lack a numeric CVSS score, but all 62 have a categorical severity, publication date, and resolution date. Categorical severity was encoded as Low=1, Medium=2, High=3, Critical=4.

Question B uses one row per `(project_id, db, cve)`. This is the finest defensible unit retained in `rq4_vulnerable_usage_intervals.csv`; the exact Maven artifact is not retained there, so it should be called a project-DBMS-vulnerability unit rather than an exact project-library-vulnerability unit. The 2,564 segment-CVE rows were consolidated into 620 units by merging overlapping vulnerable-use intervals. Commits were not treated as independent observations.

The existing RQ5 CSV is aggregated by `(project, DBMS)`, merges intervals belonging to multiple vulnerabilities, and uses the earliest resolution date in that group. It is suitable for its DBMS-level descriptive CDF but not for a severity analysis, because one duration cannot then be attributed to one vulnerability severity.

## Question A: resolution timing

`resolution_delay = resolved_at - published_at`. Negative values mean that the first patched release predates public disclosure; they are valid signed observations, not errors or missing values.

| Analysis | n | Statistic | p-value | Result |
|---|---:|---:|---:|---|
| All vulnerabilities, Spearman | 62 | rho = -0.203884 | 0.111957 | Not significant |
| All vulnerabilities, Kruskal-Wallis | 62 | H = 3.420880 | 0.331170 | Not significant |
| Positive delay only, Spearman | 13 | rho = -0.061771 | 0.841116 | Not significant |
| Positive delay only, Kruskal-Wallis | 13 | H = 1.303611 | 0.521104 | Not significant |
| Fixed before disclosure: severity vs. positive prepublication distance | 49 | rho = 0.158362 | 0.277128 | Not significant |
| Fixed before disclosure, Kruskal-Wallis | 49 | H = 2.914577 | 0.404984 | Not significant |

There are 49 negative delays, 13 positive delays, and no exact zero. The supplied values are reproduced within rounding.

### Descriptive statistics for signed resolution delay (days)

| Severity | n | Median | Mean | Minimum | Maximum |
|---|---:|---:|---:|---:|---:|
| Low | 3 | -7.066 | -8.148 | -17.315 | -0.062 |
| Medium | 17 | -0.833 | 12.851 | -34.493 | 213.051 |
| High | 27 | -2.719 | -34.637 | -646.677 | 223.738 |
| Critical | 15 | -4.695 | -79.677 | -983.290 | 1.448 |

### Positive resolution delay only (days)

| Severity | n | Median | Mean | Minimum | Maximum |
|---|---:|---:|---:|---:|---:|
| Low | 0 | NA | NA | NA | NA |
| Medium | 5 | 21.747 | 66.271 | 0.011 | 213.051 |
| High | 7 | 15.835 | 71.978 | 0.011 | 223.738 |
| Critical | 1 | 1.448 | 1.448 | 1.448 | 1.448 |

### Method assessment

Spearman is reasonable as a descriptive monotonic association between an ordered four-level predictor and a highly skewed continuous outcome. Its usual p-value assumes independent vulnerabilities; that is more defensible here than in Question B, although vulnerabilities can still share a library/vendor. Kruskal-Wallis tests any distribution/rank difference, not specifically ordered monotonic trend. Its asymptotic approximation is fragile with only three Low observations and, in the positive-delay subset, one Critical and no Low observations. Exact or permutation inference stratified/clustered by library would be preferable if confirmatory claims are intended.

The positive-delay analysis is explicitly conditional on correction occurring after disclosure. It answers a narrower question and should not replace the signed analysis. Failure to reject the null is not evidence that the effect is exactly zero; confidence intervals and a larger sample would be needed to assess practical equivalence.

## Question B: project exposure after a patched release exists

For each project-DBMS-vulnerability unit, vulnerable-use intervals were merged and clipped at `resolved_at`. `post_resolution_exposure_days` is the sum of observed vulnerable-use time after that date. Units without post-resolution overlap retain zero. A separate response-time cohort includes only projects observed using a vulnerable version at `resolved_at`; its outcome is the duration from `resolved_at` to the end of the continuous vulnerable-use spell containing that date.

There are 620 units, 61 projects, and 62 vulnerabilities. All have categorical severity and resolution dates. Of the 620 units, 463 have positive post-resolution exposure. The response-time cohort has 413 units: 348 observed cessations and 65 right-censored observations.

### All 620 project-DBMS-vulnerability units: observed post-resolution exposure

| Severity | n | Median days | Mean days | Minimum | Maximum |
|---|---:|---:|---:|---:|---:|
| Low | 25 | 249.234 | 575.992 | 0 | 2,684.234 |
| Medium | 204 | 202.610 | 480.371 | 0 | 3,394.545 |
| High | 279 | 50.377 | 303.752 | 0 | 2,746.147 |
| Critical | 112 | 60.160 | 254.689 | 0 | 1,464.130 |

Exploratory naive tests: Spearman rho=-0.148856, p=0.000199; Kruskal-Wallis H=20.429808, p=0.000138. These p-values are not valid as confirmatory inference because observations are repeated within both project and vulnerability.

Zero durations are present in 157 units: Low 8/25, Medium 37/204, High 92/279, and Critical 20/112. A zero can mean that vulnerable use ended before the fix date, not necessarily an instantaneous update response.

### At-risk response-time cohort

| Severity | n | Median days | Mean days | Minimum | Maximum | Right-censored |
|---|---:|---:|---:|---:|---:|---:|
| Low | 16 | 854.734 | 856.549 | 42.234 | 2,684.234 | 3 |
| Medium | 152 | 355.092 | 577.946 | 0.204 | 3,394.545 | 25 |
| High | 165 | 242.542 | 451.689 | 0.381 | 2,746.147 | 22 |
| Critical | 80 | 168.660 | 333.603 | 0.204 | 1,464.130 | 15 |

Naive observed-lower-bound tests: Spearman rho=-0.200594, p=0.0000403; Kruskal-Wallis H=17.501897, p=0.000557. Dropping censored observations gives rho=-0.255665, p=0.00000135, but complete-case deletion is biased and is provided only as a sensitivity check.

There is substantial two-way dependence: 52 projects occur more than once, 44 vulnerabilities occur more than once, the maximum is 28 units for one project and 35 units for one vulnerability. After collapsing each vulnerability to its median across exposed projects, only 43 vulnerabilities remain and the association is no longer statistically distinguishable from zero: Spearman rho=-0.098463, p=0.529893; Kruskal-Wallis H=0.596780, p=0.897169. Low has only two vulnerabilities in this sensitivity analysis. This large change is direct evidence that the naive pair-level significance is sensitive to pseudoreplication.

### Outliers and censoring

No outlier was removed. By the within-severity 1.5-IQR rule in the at-risk cohort, 23 observations are above the upper fences: Medium 7, High 8, Critical 8, Low 0. Maxima range from 1,464 to 3,395 days, so means are much larger than medians.

`right_censored_no_later_version` means that no later dependency version was observed. Such a unit is not treated as having updated: its response duration is retained as a lower bound and it is flagged as censored. The dataset does not establish a common administrative study-end date for every project; censoring occurs at the last observed use of that dependency. Consequently, Spearman and Kruskal-Wallis do not properly use the censoring information.

The preferred confirmatory model is a survival model for the at-risk cohort, with update/cessation as the event, right-censoring retained, severity as an ordered or categorical predictor, and crossed dependence handled by project and vulnerability (for example, a Cox model with crossed frailties, or a parametric accelerated-failure-time mixed model). Library/DBMS and calendar time should be considered as covariates or strata. With only 62 vulnerabilities and very sparse Low severity, cluster bootstrap or randomization inference at the vulnerability level is advisable. A multi-state or recurrent-event design is needed if later adoption of an already-vulnerable release is part of the estimand.

## Conservative conclusions

**RQ4.** The 62-vulnerability analysis does not provide statistically significant evidence that greater severity is associated with earlier availability of a patched release relative to public disclosure. Point estimates weakly favor earlier correction at higher severity, but sparse categories and wide temporal dispersion preclude a claim of no effect or of a meaningful effect.

**RQ5.** Project-level observations show shorter observed post-resolution exposure for higher severities, but naive rank tests are anti-conservative because projects and vulnerabilities repeat and some outcomes are censored. The association disappears in a vulnerability-level sensitivity analysis. Therefore, the current evidence is suggestive and exploratory, not sufficient to conclude that projects update faster for more severe vulnerabilities. A censor-aware crossed-effects model is required for confirmatory inference.

## Suggested paper text

### RQ4

> Across 62 distinct vulnerabilities, severity was weakly and negatively associated with the signed delay between public disclosure and the availability of the first patched release (Spearman's rho = -0.204, p = 0.112). A Kruskal-Wallis test likewise found no statistically significant differences among severity categories (H = 3.421, p = 0.331). Forty-nine vulnerabilities had a patched release available before public disclosure, whereas 13 were patched afterwards. Restricting the analysis to the latter group produced no detectable monotonic association (rho = -0.062, p = 0.841). These non-significant results should not be interpreted as evidence of equivalence, particularly because the Low and post-disclosure Critical groups were sparse.

### RQ5

> At the project-DBMS-vulnerability level, observed post-resolution exposure tended to be shorter for higher-severity vulnerabilities. However, project-vulnerability observations were not independent and 65 of 413 projects that were using a vulnerable release when a patch became available were right-censored. Although naive rank-based tests indicated an association, the result did not persist when exposure was summarized once per vulnerability (rho = -0.098, p = 0.530). We therefore treat this pattern as exploratory rather than evidence that projects update more rapidly in response to higher severity. Confirmatory analysis requires a survival model that preserves right-censored observations and accounts for clustering by both project and vulnerability.

## Reproduction

From the repository root:

```bash
python3 -m py_compile statistical_audit_severity_20260903/audit_severity.py
python3 statistical_audit_severity_20260903/audit_severity.py
```

The script reads:

- `dbmining.sqlite`
- `rqs_data/rq4_vulnerable_usage_intervals.csv`

It writes only beneath `statistical_audit_severity_20260903/results/`. The machine-readable test results are in `audit_results.json`; row-level derived datasets and all descriptive/outlier tables are CSV files in the same directory.
