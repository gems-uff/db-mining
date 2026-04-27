#!/usr/bin/env python3
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

import database as db
from extract import get_or_create_labels, maybe_checkout, read_args, do_commit
from util import REPOS_DIR, HEURISTICS_DIR_VULNERABILITIES, green, yellow, red

from extract_historical_vulnerabilities import (
    generate_all_dependencies,
    parse_consolidated_dependency_tree_text,
    compile_patterns_by_label,
    parse_and_extract_from_consolidated,
    build_maven_purl,
    build_full_commit_index,
    preload_last_seen_vuln_sha,
)

MAX_OUTPUT_CHARS = 30000

HTTP_TO_HTTPS_REPLACEMENTS = {
    "http://repo1.maven.org/maven2": "https://repo1.maven.org/maven2",
    "http://repo2.maven.org": "https://repo1.maven.org/maven2",
    "http://central.maven.org/maven2": "https://repo1.maven.org/maven2",
    "http://repo.maven.apache.org/maven2": "https://repo.maven.apache.org/maven2",

    "http://download.osgeo.org/webdav/geotools/": "https://repo.osgeo.org/repository/release/",
    "http://repo.opengeo.org": "https://repo.osgeo.org/repository/release/",

    "http://download.java.net/maven/2/": "https://download.java.net/maven/2/",
    "http://download.java.net/": "https://download.java.net/",

    "http://repository.jboss.org/nexus/content/groups/public/": "https://repository.jboss.org/nexus/content/groups/public/",
    "http://repository.apache.org/snapshots": "https://repository.apache.org/snapshots",

    "http://repo.spring.io/plugins-release": "https://repo.spring.io/plugins-release",
    "http://conjars.org/repo": "https://conjars.org/repo",
    "http://jcenter.bintray.com": "https://jcenter.bintray.com",
    "http://download.oracle.com/maven": "https://download.oracle.com/maven",
}


def find_failed_versions(only_http_related: bool = True, limit: Optional[int] = None):
    q = (
        db.db.session.query(db.Version)
        .join(db.Execution, db.Execution.version_id == db.Version.id)
        .filter(db.Execution.output.contains("BUILD FAILED: dependency:tree"))
        .distinct()
        .order_by(db.Version.id.asc())
    )

    versions = q.all()

    if only_http_related:
        filtered = []

        for version in versions:
            outputs = (
                db.db.session.query(db.Execution.output)
                .filter(db.Execution.version_id == version.id)
                .all()
            )

            text = "\n".join((row[0] or "") for row in outputs)

            if (
                "Blocked mirror for repositories" in text
                or "maven-default-http-blocker" in text
                or "external:http" in text
                or "http://" in text
            ):
                filtered.append(version)

        versions = filtered

    if limit is not None:
        versions = versions[:limit]

    return versions


def get_project_by_id(project_id: int):
    return (
        db.db.session.query(db.Project)
        .filter(db.Project.id == project_id)
        .first()
    )


def patch_pom_urls(repo_root: str) -> Dict[str, int]:
    changed_files: Dict[str, int] = {}

    for pom_path in Path(repo_root).rglob("pom.xml"):
        try:
            original = pom_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        patched = original
        replacements_count = 0

        for old, new in HTTP_TO_HTTPS_REPLACEMENTS.items():
            count = patched.count(old)
            if count > 0:
                patched = patched.replace(old, new)
                replacements_count += count

        if patched != original:
            pom_path.write_text(patched, encoding="utf-8")
            changed_files[str(pom_path)] = replacements_count

    return changed_files


def restore_repository(repo_root: str):
    subprocess.run(
        ["git", "reset", "--hard"],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    subprocess.run(
        ["git", "clean", "-ffd"],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def create_retry_executions(version, labels, output_text: str, source: str):
    first_label_id = labels[0].id if labels else None
    exec_id_by_label = {}

    for label in labels:
        output_to_store = output_text if label.id == first_label_id else ""

        retry_output = (
            "[DBMINING] RETRY EXECUTION\n"
            f"[DBMINING] source={source}\n"
            f"[DBMINING] original_version_id={version.id}\n\n"
            + output_to_store
        )[:MAX_OUTPUT_CHARS]

        execution = db.create(
            db.Execution,
            output=retry_output,
            version=version,
            heuristic=label.heuristic,
            isValidated=False,
            isAccepted=False,
        )

        db.db.session.flush()
        exec_id_by_label[label.id] = (execution.id, label.heuristic.id)

    return exec_id_by_label


def existing_vulnerability_keys_for_version(version_id: int) -> set:
    rows = (
        db.db.session.query(
            db.VersionVulnerability.file,
            db.VersionVulnerability.versionNumber,
            db.Execution.heuristic_id,
        )
        .join(db.Execution, db.Execution.id == db.VersionVulnerability.execution_id)
        .filter(db.VersionVulnerability.version_id == version_id)
        .all()
    )

    return {(file, version_number, heuristic_id) for file, version_number, heuristic_id in rows}


def persist_extracted_libraries(
    version,
    project,
    labels,
    compiled_patterns_by_label,
    dep_entries: List[Dict],
    output_text: str,
    source: str,
):
    parsed_by_label: Dict[int, List[Dict]] = {}

    for label in labels:
        parsed_by_label[label.id] = parse_and_extract_from_consolidated(
            dep_entries=dep_entries,
            compiled_patterns=compiled_patterns_by_label.get(label.id, []),
            scopes_accept=None,
        )

    exec_id_by_label = create_retry_executions(
        version=version,
        labels=labels,
        output_text=output_text,
        source=source,
    )

    existing_keys = existing_vulnerability_keys_for_version(version.id)
    new_keys = set()

    full_sha_index = build_full_commit_index()
    previous_sha_cache = preload_last_seen_vuln_sha(project.id)

    created = 0

    for label in labels:
        parsed = parsed_by_label[label.id]
        eid, heuristic_id = exec_id_by_label[label.id]

        for result in parsed:
            file_path = result["file"]
            version_number = result["version"]

            dedup_key = (file_path, version_number, heuristic_id)
            if dedup_key in existing_keys or dedup_key in new_keys:
                continue

            group_artifact = result.get("group_artifact") or ""
            parts = group_artifact.split(":", 1)

            group = parts[0] if len(parts) > 0 else ""
            artifact = parts[1] if len(parts) > 1 else ""

            purl_value = build_maven_purl(group, artifact, version_number)

            cache_key = (file_path, heuristic_id)
            prev_sha = previous_sha_cache.get(cache_key)

            if prev_sha and prev_sha in full_sha_index and version.sha1 in full_sha_index:
                commits_between = max(
                    0,
                    full_sha_index[version.sha1] - full_sha_index[prev_sha]
                )
            else:
                commits_between = 0

            db.create(
                db.VersionVulnerability,
                versionNumber=version_number,
                file=file_path,
                version_id=version.id,
                commitsBetween=commits_between,
                purl=purl_value,
                execution_id=eid,
            )

            new_keys.add(dedup_key)
            previous_sha_cache[cache_key] = version.sha1
            created += 1

    db.db.session.flush()
    return created


def rebuild_vulnerabilities_for_version(version, project, labels, compiled_patterns_by_label):
    repo_root = os.getcwd()

    changed_files = patch_pom_urls(repo_root)

    if not changed_files:
        return False, 0, "NO_PATCH_APPLIED"

    try:
        mvn_res = generate_all_dependencies(repo_root=repo_root)

        if not mvn_res.ok:
            return False, 0, "PATCHED_DEPENDENCY_TREE_FAILED"

        dep_entries = parse_consolidated_dependency_tree_text(mvn_res.stdout_text)

        if not dep_entries:
            return False, 0, "PATCHED_DEPENDENCY_TREE_EMPTY"

        patch_summary = "\n".join(
            f"{path}: {count} replacement(s)"
            for path, count in changed_files.items()
        )

        output_text = (
            "[DBMINING] TEMPORARY HTTP TO HTTPS PATCH\n"
            f"[DBMINING] project={project.owner}/{project.name}\n"
            f"[DBMINING] sha={version.sha1}\n"
            "[DBMINING] patched_files:\n"
            + patch_summary
            + "\n\n"
            + mvn_res.stdout_text
        )[:MAX_OUTPUT_CHARS]

        created = persist_extracted_libraries(
            version=version,
            project=project,
            labels=labels,
            compiled_patterns_by_label=compiled_patterns_by_label,
            dep_entries=dep_entries,
            output_text=output_text,
            source="PATCHED_HTTP_TO_HTTPS_DEPENDENCY_TREE",
        )

        return True, created, "PATCHED_HTTP_TO_HTTPS_DEPENDENCY_TREE"

    finally:
        restore_repository(repo_root)


def retry_failed_versions(args):
    db.connect()

    labels = get_or_create_labels(
        heuristics_dir=args.heuristics,
        label_type=args.label_type,
        skip_remove=True,
    )

    compiled_patterns_by_label = compile_patterns_by_label(labels)

    failed_versions = find_failed_versions(
        only_http_related=getattr(args, "only_http_related", True),
        limit=getattr(args, "limit", None),
    )

    print(yellow(f"Versões com falha selecionadas para retry com patch: {len(failed_versions)}"))

    recovered = 0
    still_failed = 0
    total_created = 0
    by_status: Dict[str, int] = {}

    for version in failed_versions:
        project = get_project_by_id(version.project_id)

        if not project:
            print(red(f"Projeto não encontrado para version_id={version.id}"))
            continue

        project_path = os.path.join(REPOS_DIR, project.owner, project.name)

        try:
            os.chdir(project_path)
        except Exception:
            print(red(f"Repositório não encontrado: {project.owner}/{project.name}"))
            continue

        try:
            current_commit = maybe_checkout(args, version.sha1, None)

            if current_commit != version.sha1:
                still_failed += 1
                by_status["CHECKOUT_FAILED"] = by_status.get("CHECKOUT_FAILED", 0) + 1
                print(red(f"Checkout falhou para {project.name} em {version.sha1[:7]}"))
                continue

            ok, created, status = rebuild_vulnerabilities_for_version(
                version=version,
                project=project,
                labels=labels,
                compiled_patterns_by_label=compiled_patterns_by_label,
            )

            do_commit()

            by_status[status] = by_status.get(status, 0) + 1

            if ok:
                recovered += 1
                total_created += created

                print(green(
                    f"{project.name} {version.sha1[:7]} recuperado via patch, "
                    f"{created} registros"
                ))
            else:
                still_failed += 1

                print(yellow(
                    f"{project.name} {version.sha1[:7]} não recuperado, "
                    f"status={status}"
                ))

        except Exception as e:
            try:
                db.db.session.rollback()
            except Exception:
                pass

            still_failed += 1
            by_status["ERROR"] = by_status.get("ERROR", 0) + 1

            print(red(f"Erro ao reprocessar {project.name} {version.sha1[:7]}: {e}"))

        finally:
            try:
                restore_repository(project_path)
            except Exception:
                pass

    print()
    print(green(f"Recuperados com patch: {recovered}"))
    print(yellow(f"Ainda falharam: {still_failed}"))
    print(green(f"VersionVulnerability criados: {total_created}"))

    print(yellow("Resumo por status:"))
    for status, count in sorted(by_status.items(), key=lambda x: x[1], reverse=True):
        print(f"{status}: {count}")

    db.close()


def build_args():
    args = read_args(
        "retry_failed_dependency_tree_http_patch",
        "Retry dependency:tree after temporary HTTP to HTTPS patch in pom.xml",
        default_label_type="vulnerabilities",
        default_skip_remove=True,
        default_heuristics=HEURISTICS_DIR_VULNERABILITIES,
    )

    args.checkout = True

    if not hasattr(args, "only_http_related"):
        args.only_http_related = True

    if not hasattr(args, "limit"):
        args.limit = None

    return args


def main():
    args = build_args()
    retry_failed_versions(args)


if __name__ == "__main__":
    main()