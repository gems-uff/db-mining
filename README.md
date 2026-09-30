# Analyzing Vulnerabilities of Database Management System Libraries in the History of Open Source Java Projects

This repository is the replication package for a longitudinal study of
vulnerabilities in database management system (DBMS)-related libraries used by
open-source Java projects.

DBMS-related libraries mediate the interaction between applications and stored
data. Vulnerabilities in these dependencies can therefore affect the
confidentiality, integrity, and availability of application data. This study
examines vulnerability exposure as a multidimensional phenomenon: vulnerable
library releases, vulnerability propagation across release histories,
downstream project exposure, activity before and after disclosure and
resolution, post-resolution exposure duration, and the motivations behind
dependency updates.

The study reconstructs Maven dependency histories commit by commit instead of
examining only project snapshots. For each relevant commit, the pipeline
identifies DBMS-related libraries and their releases, represents them as
Package URLs (PURLs), and associates them with public vulnerability records.

## Authors

- Camila A. Paiva
- Caio Lopes
- João Felipe Pimentel
- Leonardo Murta
- Vanessa Braganholo

All authors are affiliated with the Institute of Computing, Universidade
Federal Fluminense (UFF), Brazil.

Contact: `{camila.paiva, conceicaocaio, jpimentel, leomurta, vanessa}@ic.uff.br`

## Study Overview

The project corpus was derived from a broader corpus of mature and popular
open-source Java repositories. This study retains Maven projects with a
consistent single-module or multi-module structure and evidence of using at
least one reference DBMS-related library.

The study snapshot contains:

- 83 open-source Java projects;
- 50 reference DBMS technologies, selected from the February 2022 DB-Engines
  ranking;
- 77,918 relevant commits that modified at least one `pom.xml` file;
- 62 distinct vulnerabilities;
- 645 affected DBMS-related library releases; and
- 1,342 vulnerability-library-release records.

The repositories were updated and revalidated in January 2026. The results
characterize the DBMS-related Java libraries observed in this corpus and must
not be interpreted as a security ranking of the underlying DBMS servers.

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
RQ5 analyze exposure in downstream projects. RQ6 is an exploratory manual
analysis of commits, pull requests, issue discussions, and release notes; an
update is classified as security-driven only when the available evidence
explicitly mentions a vulnerability, CVE, advisory, or another security reason.

## Method Summary

The automated workflow has four main stages:

1. Reconstruct the default-branch history of each repository and select
   commits that modify at least one `pom.xml` file.
2. Generate a consolidated Maven dependency tree for every relevant commit,
   preserving direct and transitive dependencies and the structure of
   multi-module projects.
3. Apply validated regular-expression heuristics to Maven `groupId` and
   `artifactId` values to identify DBMS-related libraries and releases.
4. Convert each detected release to a Maven PURL and associate it with
   vulnerability advisories and temporal metadata.

The DBMS-library detection heuristics were manually validated using 69 relevant
commits from four projects. After refinement, the reported validation achieved
100% precision and 81.40% recall. Most remaining false negatives resulted from
historical commits whose Maven dependency trees could not be generated.

## Vulnerability Sources

The pipeline queries and enriches vulnerability records using the following
sources:

- **GitHub Advisory Database** — primary source for affected Maven releases and
  first patched releases;
- **OSV.dev** — fallback source for structured vulnerability records; and
- **National Vulnerability Database (NVD)** — complementary source for CVE
  publication dates, CVSS information, affected ranges, and missing resolution
  metadata.

Broad keyword matches are not treated as sufficient evidence. A package and
its observed release must be supported by an affected-release range. CVE and
GHSA aliases are consolidated to avoid counting the same vulnerability more
than once.

## Repository Structure

| Path | Purpose |
| --- | --- |
| `resources/annotated_java_vulnerabilities.xlsx` | Metadata for the projects analyzed by the vulnerability pipeline. |
| `resources/heuristics/vulnerabilities/` | DBMS-related Maven dependency detection heuristics. |
| `src/extract_vulnerabilities_parallel.py` | Historical Maven dependency extraction. |
| `src/search_vulnerabilites.py` | Vulnerability lookup, validation, enrichment, and resolution metadata. |
| `dbmining.sqlite` | Database snapshot used to derive the study results. |
| `rqs_data/` | Derived tables used by RQ1–RQ5. |
| `graficos_rq1/`–`graficos_rq5/` | Figures for the quantitative research questions. |
| `graficos_discussão/` | Cross-RQ vulnerability-profile figures and their supporting metrics. |

## Requirements

- Python 3.7 or newer;
- Git 2.23 or newer;
- Maven 3.9.9 available as `mvn`;
- the Python dependencies declared in `Pipfile` and `Pipfile.lock`;
- a GitHub personal access token for fresh advisory collection;
- optionally, an NVD API key; and
- local clones of the study repositories for a complete reconstruction from
  project histories.

Set up the Python environment from the repository root:

```bash
python -m pip install pipenv
pipenv install
pipenv shell
```

For a fresh vulnerability lookup, configure the required credentials:

```bash
export GITHUB_TOKEN="<github-token>"
export NVD_API_KEY="<optional-nvd-api-key>"
```

The default SQLite configuration is:

```json
{
  "drop_database": "False",
  "database_type": "sqlite",
  "database_name": "dbmining.sqlite"
}
```

## Reproducing the Study

Two reproduction paths are available. To reproduce the reported tables and
figures, start from the supplied database snapshot. Reconstructing the database
from repository histories is substantially more expensive because Maven must
resolve historical dependency trees for tens of thousands of commits.

### A. Reproduce Tables and Figures from the Database Snapshot

Run the commands below from the repository root, in the listed order:

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

The scripts write derived CSV files to `rqs_data/`, RQ-specific figures to the
`graficos_rq*` directories, and integrated vulnerability-profile figures to
`graficos_discussão/`.

### B. Reconstruct the Vulnerability Database

The full historical extraction expects the study repositories to be locally
available in the workspace configured by the project utilities.

```bash
python src/extract_vulnerabilities_parallel.py \
  --input resources/annotated_java_vulnerabilities.xlsx

python src/search_vulnerabilites.py \
  --db-path dbmining.sqlite \
  --maven-cache-file maven_release_date_cache.json
```

The extraction script supports filters for individual repositories and bounded
commit ranges. Consult its command-line help before a full execution:

```bash
python src/extract_vulnerabilities_parallel.py --help
python src/search_vulnerabilites.py --help
```

Network services and advisory databases evolve over time. A fresh collection
may therefore differ from the archived study snapshot because advisories,
aliases, severity scores, or Maven metadata may have been added or corrected.

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

## Reproducibility Checks

Before comparing regenerated results with the paper, verify:

- the database snapshot used by every command;
- the numbers of projects, PURLs, distinct vulnerabilities, and affected
  releases;
- records missing publication, patched-version, or resolution dates;
- `fix_lookup_status` and source provenance for fallback matches;
- CVE/GHSA alias consolidation;
- build failures in historical Maven dependency extraction; and
- right-censored project histories in post-resolution exposure analyses.

Outliers should not be removed automatically. Likewise, non-significant
statistical results must not be interpreted as evidence that an effect is
absent.

`src/extract_historical_vulnerabilities.py` and the former OSS Index-only
workflow are legacy implementations and are not part of the maintained
pipeline documented above.

## Citation

This replication package accompanies the following manuscript:

> Camila A. Paiva, Caio Lopes, João Felipe Pimentel, Leonardo Murta, and
> Vanessa Braganholo. *Analyzing Vulnerabilities of Database Management System
> Libraries in the History of Open Source Java Projects*. Manuscript submitted
> to Empirical Software Engineering.

Citation metadata will be updated after publication.

## License

See [LICENSE](LICENSE).
