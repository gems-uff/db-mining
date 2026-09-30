# Vulnerability Study — Analyzing Vulnerabilities of Database Management System Libraries in the History of Open Source Java Projects

This is the companion repository for the research *Analyzing Vulnerabilities
of Database Management System Libraries in the History of Open Source Java
Projects*. Its main goal is to investigate how vulnerabilities in DBMS-related
Java libraries propagate across library releases, affect downstream projects,
and persist throughout project histories.

The study treats vulnerability exposure as a multidimensional phenomenon. It
combines library-level evidence, project-level dependency histories, temporal
information about disclosure and patch availability, and qualitative evidence
about dependency update decisions.

# Team

Camila A. Paiva (UFF, Brazil)  
Caio Lopes (UFF, Brazil)  
João Felipe Pimentel (UFF, Brazil)  
Leonardo Murta (UFF, Brazil)  
Vanessa Braganholo (UFF, Brazil)

Contact: `{camila.paiva, conceicaocaio, jpimentel, leomurta, vanessa}@ic.uff.br`

# Selection of the Project Corpus

The vulnerability study reuses the corpus constructed for the Adoption and
Interaction Study. The original corpus contains mature, popular, and actively
maintained open-source Java projects. Because the vulnerability analysis
requires precise dependency and release resolution, this study retains only
projects that:

1. use Maven and contain a root-level `pom.xml`;
2. use at least one reference DBMS-related library; and
3. have a consistent single-module or multi-module Maven structure.

The resulting study snapshot contains:

- 83 open-source Java projects;
- 50 reference DBMS technologies selected from the February 2022 DB-Engines
  ranking;
- 77,918 relevant commits that modified at least one `pom.xml` file;
- 62 distinct vulnerabilities;
- 645 affected DBMS-related library releases; and
- 1,342 vulnerability-library-release records.

The repositories were updated and revalidated in January 2026. These results
characterize the DBMS-related Java libraries observed in this corpus and must
not be interpreted as a security ranking of the underlying DBMS servers.

# Dependency and Vulnerability Extraction

The pipeline reconstructs Maven dependency histories commit by commit. It
analyzes the default branch of each repository and selects every commit that
changes at least one `pom.xml` file. For each relevant commit, it generates a
consolidated Maven dependency tree, identifies DBMS-related libraries and their
releases, converts the releases to Package URLs (PURLs), and associates them
with public vulnerability records.

| Name | Goal | Main input | Main output |
| --- | --- | --- | --- |
| `src/extract_vulnerabilities_parallel.py` | Reconstruct historical Maven dependency trees and identify DBMS-related releases. | `resources/annotated_java_vulnerabilities.xlsx` and local project clones | Project, commit, dependency, release, file/module, and PURL records in the database. |
| `src/search_vulnerabilites.py` | Query, validate, consolidate, and enrich vulnerability records. | Maven PURLs and releases stored in `dbmining.sqlite` | Vulnerability-release associations, CVSS data, publication dates, and patch metadata. |
| `src/extrair_base_rqs.py` | Build the common analysis tables. | `dbmining.sqlite` | Base and deduplicated historical datasets in `rqs_data/`. |

The regular-expression heuristics in
`resources/heuristics/vulnerabilities/` match Maven `groupId` and `artifactId`
values. The heuristics were manually validated using 69 relevant commits from
four projects. After refinement, the reported validation achieved 100%
precision and 81.40% recall. Most remaining false negatives resulted from
historical commits whose Maven dependency trees could not be generated.

## Vulnerability Sources

The pipeline uses three complementary sources:

- **GitHub Advisory Database:** primary source for affected Maven releases and
  first patched releases;
- **OSV.dev:** fallback source for structured vulnerability records; and
- **National Vulnerability Database (NVD):** complementary source for CVE
  publication dates, CVSS information, affected ranges, and missing resolution
  metadata.

A keyword match alone is not sufficient. The package and observed release must
be supported by affected-range evidence. CVE and GHSA aliases are consolidated
to avoid counting the same vulnerability more than once.

# Results Analysis

## Research Questions

| RQ | Research question |
| --- | --- |
| RQ1 | How are vulnerabilities distributed across releases of DBMS-related libraries? |
| RQ2 | Do vulnerabilities in DBMS-related libraries tend to concentrate in specific releases, or propagate across multiple releases? |
| RQ3 | To what extent are projects using DBMS-related libraries affected by known vulnerabilities? |
| RQ4 | How do projects evolve across the pre-disclosure, post-disclosure, and post-resolution phases of their vulnerabilities? |
| RQ5 | For how long did projects remain vulnerable after patched releases became available? |
| RQ6 | Are dependency updates in projects explicitly motivated by vulnerability remediation? |

RQ1 and RQ2 characterize vulnerabilities at the library level. RQ3 through
RQ5 analyze downstream project exposure. RQ6 is an exploratory manual analysis
of commits, pull requests, issue discussions, and release notes. An update is
classified as security-driven only when the available evidence explicitly
mentions a vulnerability, CVE, advisory, or another security reason.

## Quantitative Analysis Workflow

| Analysis | Script | Main outputs |
| --- | --- | --- |
| Common RQ base | `src/extrair_base_rqs.py` | `rqs_data/vulnerability_analysis_base.csv` and deduplicated history tables. |
| RQ1 base tables | `src/gerar_rq1.py` | Vulnerability-release-project associations and exposure summaries. |
| RQ1 and RQ2 | `src/gerar_rq1_rq2_release_distributions.py` | Affected-release and vulnerability-propagation tables and figures. |
| RQ3 | `src/gerar_rq3_project_exposure.py` | Project exposure figure. |
| RQ4 resolution timing | `src/gerar_rq4_release_cve_resolution.py` | Resolution dates, summaries, timing buckets, and figures. |
| RQ4 project activity | `src/gerar_rq4_vulnerable_activity.py` | Pre-disclosure, post-disclosure, and post-resolution activity tables and figures. |
| RQ5 | `src/gerar_rq5_exposure_duration.py` | Project-level exposure durations and cumulative distribution figures. |
| Resolution-time support | `src/gerar_rq5_vulnerability_resolution_time_boxplot.py` | Vulnerability resolution-time data and boxplots. |
| Integrated profiles | `src/gerar_radar_dbms_metrics.py` | Cross-RQ metrics and vulnerability-profile radar charts. |

## Temporal Definitions

For every vulnerability that reports a first patched release, the pipeline
retrieves that release's publication timestamp from the Maven Central Search
API. This timestamp represents the earliest date on which a downstream project
could migrate to a safe release. Together with the CVE publication date, it
defines the three phases used in RQ4:

- `published_at`: date on which the vulnerability was publicly disclosed;
- `first_patched_version`: first reported patched library release;
- `resolved_at`: Maven Central publication date of that patched release;
- **Pre-disclosure:** project activity involving vulnerable releases before the
  vulnerability was publicly disclosed;
- **Post-disclosure (pre-resolution):** project activity involving vulnerable
  releases after public disclosure but before a patched release became
  available; and
- **Post-resolution:** project activity involving vulnerable releases after a
  patched release had become available.

A negative value of `resolved_at - published_at` indicates that the patched
release was available before public disclosure; it is not a data error.

For RQ5, the unit of analysis is a project–DBMS-related-library pair that
remained on a vulnerable release after the first patched release became
available. Post-resolution exposure is measured from patch availability until
the project migrates to a safe release. If no migration is observed, exposure
is measured until the end of the observation window. These observations are
right-censored and must be interpreted as lower bounds rather than complete
exposure durations.

# Installation

## Requirements

- Python 3.7 or newer;
- Git 2.23 or newer;
- Maven 3.9.9 available as `mvn`;
- the Python dependencies declared in `Pipfile` and `Pipfile.lock`;
- a GitHub personal access token for a fresh advisory collection;
- optionally, an NVD API key; and
- local clones of the study repositories for a complete reconstruction from
  project histories.

## Setting Up the Environment

Run the following commands from the repository root:

```bash
python -m pip install pipenv
pipenv install
pipenv shell
```

For a fresh vulnerability lookup, configure the credentials:

```bash
export GITHUB_TOKEN="<github-token>"
export NVD_API_KEY="<optional-nvd-api-key>"
```

The default SQLite configuration in `database.json` is:

```json
{
  "drop_database": "False",
  "database_type": "sqlite",
  "database_name": "dbmining.sqlite"
}
```

## Database Schema Compatibility

The vulnerability pipeline introduced `execution.execution_type` to distinguish
original dependency extraction from retry executions. When the current code
opens a database created by the Adoption and Interaction Study, it applies an
additive, idempotent migration that creates the missing column and classifies
existing records as `ORIGINAL`. It does not delete or rewrite the original
study tables, and it does not impose the newer uniqueness constraint on legacy
data. Tables used only by the vulnerability study are created separately with
SQLAlchemy's additive `create_all` operation.

# Steps for Running the Analysis

Two reproduction paths are available. Reproducing the reported tables and
figures from the supplied database snapshot is the recommended path.
Reconstructing the database is substantially more expensive because Maven must
resolve historical dependency trees for tens of thousands of commits.

## Reproducing Tables and Figures from the Database Snapshot

Run these commands from the repository root, in order:

```bash
python src/extrair_base_rqs.py
python src/gerar_rq1.py
python src/gerar_rq1_rq2_release_distributions.py
python src/gerar_rq3_project_exposure.py
python src/gerar_rq4_release_cve_resolution.py
python src/gerar_rq4_vulnerable_activity.py
python src/gerar_rq5_exposure_duration.py
python src/gerar_rq5_vulnerability_resolution_time_boxplot.py
python src/gerar_radar_dbms_metrics.py
```

## Reconstructing the Vulnerability Database

The full extraction expects the study repositories to be locally available in
the workspace configured by the project utilities.

```bash
python src/extract_vulnerabilities_parallel.py \
  --input resources/annotated_java_vulnerabilities.xlsx

python src/search_vulnerabilites.py \
  --db-path dbmining.sqlite \
  --maven-cache-file maven_release_date_cache.json
```

Network services and advisory databases evolve. A fresh collection may differ
from the archived study snapshot because advisories, aliases, severity scores,
or Maven metadata may have been added or corrected.

# Datasets and Generated Artifacts

| Path | Content |
| --- | --- |
| `resources/annotated_java_vulnerabilities.xlsx` | Metadata for the projects analyzed by the vulnerability pipeline. |
| `resources/heuristics/vulnerabilities/` | DBMS-related Maven dependency detection heuristics. |
| `dbmining.sqlite` | Database snapshot used to derive the study results. |
| `rqs_data/` | Derived datasets for RQ1–RQ5. |
| `graficos_rq1/`–`graficos_rq5/` | Figures for the quantitative research questions. |
| `graficos_discussão/` | Cross-RQ vulnerability-profile figures and supporting metrics. |

# Reproducibility Notes

Before comparing regenerated results with the paper, verify:

- the database snapshot used by every command;
- the numbers of projects, PURLs, distinct vulnerabilities, and affected
  releases;
- records missing publication, patched-version, or resolution dates;
- `fix_lookup_status` and source provenance for fallback matches;
- CVE/GHSA alias consolidation;
- build failures during historical Maven dependency extraction; and
- right-censored project histories in post-resolution exposure analyses.

Outliers should not be removed automatically. Likewise, non-significant
statistical results must not be interpreted as evidence that an effect is
absent.

`src/extract_historical_vulnerabilities.py` and the former OSS Index-only
workflow are legacy implementations and are not part of the maintained
pipeline documented above.

# Citation

This replication package accompanies the following manuscript:

> Camila A. Paiva, Caio Lopes, João Felipe Pimentel, Leonardo Murta, and
> Vanessa Braganholo. *Analyzing Vulnerabilities of Database Management System
> Libraries in the History of Open Source Java Projects*. Manuscript submitted
> to Empirical Software Engineering.

Citation metadata will be updated after publication.

# Acknowledgements

The authors acknowledge Universidade Federal Fluminense and the funding
agencies that supported this research. Specific grant information can be added
to the final published citation metadata.

# License

See [LICENSE](LICENSE).
