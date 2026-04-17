#!/usr/bin/env python3
import os
import subprocess
from typing import Dict, List, Optional, Tuple

import database as db
from extract import get_or_create_labels, maybe_checkout, read_args
from util import REPOS_DIR, HEURISTICS_DIR_VULNERABILITIES, green, yellow, red

# Reaproveite estas funções do seu script atual
from extract_historical_vulnerabilities import (
    generate_all_dependencies,
    parse_consolidated_dependency_tree_text,
    compile_patterns_by_label,
    parse_and_extract_from_consolidated,
    preload_executions_for_version,
    preload_existing_vulns_for_version,
    build_maven_purl,
    build_full_commit_index,
    preload_last_seen_vuln_sha,
    run_reset
)

from extract import do_commit


def find_failed_versions(only_http_related: bool = True, limit: Optional[int] = None):
    """
    Busca versões cujo dependency:tree falhou anteriormente.
    Considera apenas executions com output preenchido.
    """
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
                .filter(
                    db.Execution.version_id == version.id,
                    db.Execution.output != None
                )
                .all()
            )
            text = "\n".join((o[0] or "") for o in outputs)
            if (
                "Blocked mirror for repositories" in text
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


def clear_version_vulnerabilities(version_id: int):
    (
        db.db.session.query(db.VersionVulnerability)
        .filter(db.VersionVulnerability.version_id == version_id)
        .delete(synchronize_session=False)
    )
    db.db.session.flush()


def update_execution_outputs_success(version, labels, all_deps_text: str):
    executions_by_heuristic = preload_executions_for_version(version.id)
    first_label_id = labels[0].id if labels else None
    exec_id_by_label = {}

    for label in labels:
        heuristic_id = label.heuristic.id
        output_to_store = all_deps_text if label.id == first_label_id else ""
        existing = executions_by_heuristic.get(heuristic_id)

        if existing:
            existing.output = output_to_store
            eid = existing.id
        else:
            execution = db.create(
                db.Execution,
                output=output_to_store,
                version=version,
                heuristic=label.heuristic,
                isValidated=False,
                isAccepted=False
            )
            db.db.session.flush()
            eid = execution.id

        exec_id_by_label[label.id] = (eid, heuristic_id)

    return exec_id_by_label


def update_execution_outputs_failure(version, labels, fail_output: str):
    executions_by_heuristic = preload_executions_for_version(version.id)
    first_label_id = labels[0].id if labels else None

    for label in labels:
        heuristic_id = label.heuristic.id
        output_to_store = fail_output if label.id == first_label_id else ""
        existing = executions_by_heuristic.get(heuristic_id)

        if existing:
            existing.output = output_to_store
        else:
            db.create(
                db.Execution,
                output=output_to_store,
                version=version,
                heuristic=label.heuristic,
                isValidated=False,
                isAccepted=False
            )

    db.db.session.flush()


def rebuild_vulnerabilities_for_version(version, project, labels, compiled_patterns_by_label):
    repo_root = os.getcwd()
    mvn_res = generate_all_dependencies(repo_root=repo_root)

    if not mvn_res.ok:
        # Não altera nada no banco quando o retry falha.
        # Preserva integralmente a rastreabilidade da primeira execução.
        return False, 0

    dep_entries = parse_consolidated_dependency_tree_text(mvn_res.stdout_text)

    # Se o dependency:tree gerou com sucesso, atualiza as executions como sucesso
    # e segue com a extração para todos os labels.
    if not dep_entries:
        update_execution_outputs_success(version, labels, mvn_res.stdout_text)
        return True, 0

    clear_version_vulnerabilities(version.id)

    parsed_by_label: Dict[int, List[Dict]] = {}
    for label in labels:
        parsed_by_label[label.id] = parse_and_extract_from_consolidated(
            dep_entries=dep_entries,
            compiled_patterns=compiled_patterns_by_label.get(label.id, []),
            scopes_accept=None
        )

    exec_id_by_label = update_execution_outputs_success(version, labels, mvn_res.stdout_text)
    existing_vulns = preload_existing_vulns_for_version(version.id)

    full_sha_index = build_full_commit_index()
    previous_sha_cache = preload_last_seen_vuln_sha(project.id)

    created = 0

    for label in labels:
        parsed = parsed_by_label[label.id]
        eid, heuristic_id = exec_id_by_label[label.id]

        for result in parsed:
            file_path = result["file"]
            new_version = result["version"]

            dedup_key = (file_path, new_version, heuristic_id)
            if dedup_key in existing_vulns:
                continue

            ga = (result.get("group_artifact") or "")
            parts = ga.split(":", 1)
            group = parts[0] if len(parts) > 0 else ""
            artifact = parts[1] if len(parts) > 1 else ""
            purl_value = build_maven_purl(group, artifact, new_version)

            cache_key = (file_path, heuristic_id)
            prev_sha = previous_sha_cache.get(cache_key)

            if prev_sha and prev_sha in full_sha_index and version.sha1 in full_sha_index:
                commits_between = max(0, full_sha_index[version.sha1] - full_sha_index[prev_sha])
            else:
                commits_between = 0

            db.create(
                db.VersionVulnerability,
                versionNumber=new_version,
                file=file_path,
                version_id=version.id,
                commitsBetween=commits_between,
                purl=purl_value,
                execution_id=eid
            )

            existing_vulns.add(dedup_key)
            previous_sha_cache[cache_key] = version.sha1
            created += 1

    db.db.session.flush()
    return True, created


def retry_failed_versions(args):
    db.connect()

    labels = get_or_create_labels(
        heuristics_dir=args.heuristics,
        label_type=args.label_type,
        skip_remove=True
    )
    compiled_patterns_by_label = compile_patterns_by_label(labels)

    failed_versions = find_failed_versions(
        only_http_related=args.only_http_related,
        limit=args.limit
    )

    print(yellow(f"Versões com falha selecionadas para retry: {len(failed_versions)}"))

    recovered = 0
    still_failed = 0
    total_created = 0

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
            current_sha1 = None
            current_commit = maybe_checkout(args, version.sha1, current_sha1)

            if current_commit != version.sha1:
                print(red(f"Checkout falhou para {project.name} em {version.sha1[:7]}"))
                still_failed += 1
                continue

            ok, created = rebuild_vulnerabilities_for_version(
                version=version,
                project=project,
                labels=labels,
                compiled_patterns_by_label=compiled_patterns_by_label
            )

            do_commit()

            if ok:
                recovered += 1
                total_created += created
                print(green(f"{project.name} {version.sha1[:7]} reprocessado, {created} vulnerabilidades"))
            else:
                still_failed += 1
                print(yellow(f"{project.name} {version.sha1[:7]} continuou falhando"))

        except Exception as e:
            db.db.session.rollback()
            still_failed += 1
            print(red(f"Erro ao reprocessar {project.name} {version.sha1[:7]}: {e}"))

    print()
    print(green(f"Reprocessados com sucesso: {recovered}"))
    print(yellow(f"Ainda falharam: {still_failed}"))
    print(green(f"VersionVulnerability recriados: {total_created}"))

    db.close()


def build_args():
    args = read_args(
        "retry_failed_dependency_tree",
        "Retry dependency:tree failures after Maven settings change",
        default_label_type="vulnerabilities",
        default_skip_remove=True,
        default_heuristics=HEURISTICS_DIR_VULNERABILITIES
    )
    args.checkout = True

    if not hasattr(args, "only_http_related"):
        args.only_http_related = True
    if not hasattr(args, "limit"):
        args.limit = None

    return args


def main():
    #run_reset()
    args = build_args()
    retry_failed_versions(args)


if __name__ == "__main__":
    main()