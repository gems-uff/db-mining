import os
import re
import csv
from typing import Optional, List, Dict
from util import ANNOTATED_FILE_JAVA


import database as db
from extract import (
    get_or_create_projects,
    get_or_create_labels,
    read_args,
)
from util import REPOS_DIR, red, yellow, green, HEURISTICS_DIR_VULNERABILITIES


# ============================
# Helpers para POM e XML
# ============================

def _strip_ns(tag: str) -> str:
    """Remove namespace de uma tag XML."""
    return tag.split('}', 1)[-1] if '}' in tag else tag


def _resolve_basedir(path_text: str, pom_dir: str) -> str:
    """Resolve ${project.basedir} e ${basedir} em caminhos concretos."""
    if not path_text:
        return path_text
    return (
        path_text
        .replace('${project.basedir}', pom_dir)
        .replace('${basedir}', pom_dir)
    )


def find_external_files_in_pom(file_path: str):
    """
    Varre <configuration> de um pom.xml em busca de caminhos de arquivos externos.

    Retorna uma lista de caminhos absolutos que existem no filesystem.
    """
    import xml.etree.ElementTree as ET

    ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
    pom_dir = os.path.dirname(file_path)
    try:
        eff = os.path.join(pom_dir, 'effective-pom.xml')
        tree = ET.parse(eff if os.path.isfile(eff) else file_path)
    except Exception:
        return []

    root = tree.getroot()
    found = []

    # Procura tags que costumam carregar caminhos de arquivos
    for conf in root.findall('.//m:configuration', ns):
        for node in conf.iter():
            name = _strip_ns(node.tag).lower()
            if name in ('file', 'configfile', 'include'):
                if node.text and node.text.strip():
                    raw = node.text.strip()
                    resolved = _resolve_basedir(raw, pom_dir)
                    if not os.path.isabs(resolved):
                        resolved = os.path.normpath(os.path.join(pom_dir, resolved))
                    found.append(resolved)

    # Padrão com lista de arquivos
    for n in root.findall('.//m:configuration//m:files//m:file', ns):
        if n.text and n.text.strip():
            raw = n.text.strip()
            resolved = _resolve_basedir(raw, pom_dir)
            if not os.path.isabs(resolved):
                resolved = os.path.normpath(os.path.join(pom_dir, resolved))
            found.append(resolved)

    # Filtra apenas arquivos que existem, sem duplicar
    uniq = []
    seen = set()
    for p in found:
        if p not in seen and os.path.isfile(p):
            uniq.append(os.path.abspath(p))
            seen.add(p)

    return uniq


def get_root_pom_path() -> Optional[str]:
    """
    Retorna o caminho absoluto do pom.xml na raiz do repositório atual.

    Se não existir, retorna None.
    """
    root_pom = os.path.abspath(os.path.join(os.getcwd(), 'pom.xml'))
    return root_pom if os.path.isfile(root_pom) else None


# ============================
# Helpers para padrões de DB
# ============================

def build_db_patterns_from_labels(labels) -> List[str]:
    """
    Extrai padrões das heurísticas de DB (label.heuristic.pattern)
    e normaliza para comparação simples em texto.

    Exemplo de normalização
    "com.h2database : h2" vira "com.h2database:h2".
    """
    patterns = set()
    for label in labels:
        text = (label.heuristic.pattern or "")
        for ln in text.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            patterns.add(re.sub(r"\s+", "", ln).lower())
    return list(patterns)


def file_has_dependency_declarations(path: str, db_patterns: list[str]) -> bool:
    """
    Verifica se um arquivo externo parece declarar versões ou dependências
    relacionadas às heurísticas de DB.

    Usa dois critérios
    pelo menos um padrão de DB aparece no texto
    existe algum marcador típico de dependência ou versão.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return False

    lowered = text.lower()
    simplified = re.sub(r"\s+", "", lowered)

    # pelo menos um padrão de DB precisa aparecer
    if not any(pat in simplified for pat in db_patterns):
        return False

    # marcadores de dependência ou versão
    markers = [
        "<dependency>",
        "groupid",
        "artifactid",
        "version",
        ".version",
        "_version",
        "db.version",
        "database.version",
        "dependencymanagement",
    ]
    if not any(m in lowered for m in markers):
        return False

    return True


def collect_external_version_files(root_pom: str, labels) -> List[str]:
    """
    Usa o pom raiz para achar arquivos externos,
    depois filtra somente aqueles que parecem declarar versões ou dependências de DB.
    """
    external_files = find_external_files_in_pom(root_pom)
    if not external_files:
        return []

    db_patterns = build_db_patterns_from_labels(labels)
    if not db_patterns:
        return []

    version_files = []
    for path in external_files:
        if file_has_dependency_declarations(path, db_patterns):
            version_files.append(path)

    return version_files


# ============================
# Diagnóstico principal
# ============================

def diagnose_external_dependency_files(args, output_csv: str = "external_version_files.csv"):
    """
    Para cada projeto do corpus
    entra no repositório
    encontra o pom.xml raiz
    busca arquivos externos referenciados no pom
    identifica quais destes arquivos parecem declarar dependências ou versões de DB.

    Resultado é salvo em CSV com colunas
    owner, name, has_external_version_files, files
    """
    db.connect()

    projects = get_or_create_projects(
        create_version=False,
        filename=args.input,
        filters=args.filter,
        min_project=args.min_project,
        max_project=args.max_project,
        skip_remove=args.skip_remove,
    )

    labels = get_or_create_labels(
        heuristics_dir=args.heuristics,
        label_type=args.label_type,
        skip_remove=args.skip_remove,
    )

    rows = []

    print(f"\nAnalisando {len(projects)} projetos para uso de arquivos externos com dependências de DB.")

    for project in projects:
        repo_path = os.path.join(REPOS_DIR, project.owner, project.name)
        print(f"\nProjeto {project.owner}/{project.name}")
        try:
            os.chdir(repo_path)
        except NotADirectoryError:
            print(red("Repositório não encontrado."))
            rows.append({
                "owner": project.owner,
                "name": project.name,
                "has_external_version_files": False,
                "files": "",
                "reason": "repository_not_found",
            })
            continue

        root_pom = get_root_pom_path()
        if not root_pom:
            print(yellow("Sem pom.xml na raiz."))
            rows.append({
                "owner": project.owner,
                "name": project.name,
                "has_external_version_files": False,
                "files": "",
                "reason": "no_root_pom",
            })
            continue

        try:
            version_files = collect_external_version_files(root_pom, labels)
        except Exception as e:
            print(red(f"Erro ao coletar arquivos externos, {e}"))
            rows.append({
                "owner": project.owner,
                "name": project.name,
                "has_external_version_files": False,
                "files": "",
                "reason": f"error_collecting_files, {e}",
            })
            continue

        if version_files:
            print(green(f"Encontrados arquivos externos com possíveis declarações de dependências de DB."))
            for vf in version_files:
                print(f"  {vf}")
        else:
            print(yellow("Nenhum arquivo externo com declarações de dependências de DB encontrado."))

        rows.append({
            "owner": project.owner,
            "name": project.name,
            "has_external_version_files": bool(version_files),
            "files": ";".join(version_files),
            "reason": "",
        })

    # grava CSV
    try:
        fieldnames = ["owner", "name", "has_external_version_files", "files", "reason"]
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(green(f"\nArquivo de diagnóstico salvo em {output_csv}"))
    except Exception as e:
        print(red(f"Falha ao salvar CSV, {e}"))

    db.close()


def main():
    """
    Script de diagnóstico para identificar projetos que usam arquivos externos
    com declarações de dependências ou versões de DB.
    """
    args = read_args(
    'diagnose_external_deps',     # nome do script (posicional)
    'Diagnose external files that declare DB dependencies or versions',
    "vulnerabilities",
    True,
    HEURISTICS_DIR_VULNERABILITIES,
    ANNOTATED_FILE_JAVA
)


    diagnose_external_dependency_files(args)

if __name__ == "__main__":
    main()
