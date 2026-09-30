# DB Mining

This repository contains the data, source code, and replication material for a
research project on the use of database management systems (DBMSs) in
open-source Java projects. The project currently supports two complementary
empirical studies: one on DBMS adoption and interaction, and another on
vulnerabilities in DBMS-related libraries.

## Studies

### Study 1 — DBMS Adoption and Interaction

**Analyzing the Adoption and Interaction of Database Management Systems
Throughout the History of Open Source Projects**

This study investigates which DBMS technologies are used by open-source Java
projects, how their adoption evolves throughout project histories, and how
different DBMS technologies are combined. It includes current and historical
analyses of DBMS usage, implementation technologies, query mechanisms,
co-occurrence, and replacement patterns.

See [README_ADOPTION.md](README_ADOPTION.md) for the study description,
pipeline, installation instructions, datasets, and reproduction steps.

### Study 2 — Vulnerabilities in DBMS-Related Libraries

**Analyzing Vulnerabilities of Database Management System Libraries in the
History of Open Source Java Projects**

This study reconstructs Maven dependency histories to investigate vulnerable
DBMS-related library releases, vulnerability propagation, downstream project
exposure, disclosure and resolution phases, post-resolution exposure duration,
and the motivations behind dependency updates.

See [README_VULNERABILITIES.md](README_VULNERABILITIES.md) for the complete
method, research questions, data sources, temporal definitions, and reproduction
steps.

## Repository Organization

Both studies share part of the project corpus and research infrastructure, but
their analysis pipelines and derived results are documented separately. Before
running an analysis, follow the requirements and commands in the corresponding
study README.

## License

See [LICENSE](LICENSE).
