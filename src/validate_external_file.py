#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validação de repositórios (DB-mining):
- Verifica se há pom.xml na raiz
- Verifica se o pom.xml da raiz contém tag <file> em qualquer nível (namespaceless ou com prefixo)
- Gera CSV/XLSX com resultados e um pequeno resumo
"""

import os
import re
import json
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Tuple, Dict

# === dependências do seu projeto ===
import database as db
from extract import get_or_create_projects, read_args
from util import REPOS_DIR, yellow

# opcional para gerar planilha
try:
    import pandas as pd
    HAS_PANDAS = True
except Exception:
    HAS_PANDAS = False

# ---------------------------------------------------------------------------
# Helpers XML
# ---------------------------------------------------------------------------

def _read_xml_ns_aware(p: Path):
    """
    Retorna (root, txt, q) onde:
      - root: ElementTree root ou None se parsing falhar
      - txt: conteúdo textual do arquivo (sempre)
      - q(name): helper para compor tag com namespace detectado (ou nome simples)
    """
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None, "", None
    try:
        root = ET.fromstring(txt)
    except ET.ParseError:
        return None, txt, None  # fallback textual
    ns_uri = root.tag.split('}')[0].strip('{') if root.tag.startswith('{') else None
    def q(name):  # consulta com namespace dinâmico
        return f"{{{ns_uri}}}{name}" if ns_uri else name
    return root, txt, q

def _localname(tag: str) -> str:
    """Extrai o nome local da tag, ignorando namespace ({ns}local) e prefixo (m:local)."""
    if not tag:
        return ""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag.split(":", 1)[-1]

def _pom_has_file_tag_anywhere(pom_path: Path) -> Tuple[bool, int]:
    """
    Procura por <file> em QUALQUER nível do POM.
    1) Tenta varrer a árvore XML (independente de namespace).
    2) Fallback regex tolerante: captura <file> e <prefixo:file> (case-insensitive).
    Retorna (has_file_tag, count).
    """
    root, txt, _ = _read_xml_ns_aware(pom_path)

    if root is not None:
        count = 0
        for node in root.iter():
            if _localname(getattr(node, "tag", "")).lower() == "file":
                count += 1
        if count > 0:
            return True, count
        # continua no fallback textual, pode haver trechos não parseáveis

    pattern = r"<(?:[\w\-]+:)?file\b[^>]*>.*?</(?:[\w\-]+:)?file\s*>"
    matches = re.findall(pattern, txt, flags=re.IGNORECASE | re.DOTALL)
    return (len(matches) > 0, len(matches))

# ---------------------------------------------------------------------------
# Caminhos / CLI
# ---------------------------------------------------------------------------

def build_repo_path(owner: str, name: str) -> Path:
    return Path(REPOS_DIR) / owner / name

def parse_extra_cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--out-xlsx", default="validacao_pom_file.xlsx")
    p.add_argument("--out-csv", default="validacao_pom_file.csv")
    return p.parse_known_args()[0]

# ---------------------------------------------------------------------------
# Validação solicitada
# ---------------------------------------------------------------------------

def validate_root_pom_and_file_tag(repo_root: Path) -> Dict[str, object]:
    """
    Valida apenas:
      - se há pom.xml na raiz
      - se o pom.xml da raiz contém tag <file> (qualquer nível)
    """
    repo_root = repo_root.resolve()
    root_pom = repo_root / "pom.xml"
    has_root = root_pom.is_file()

    result = {
        "has_root_pom": has_root,
        "root_pom_has_file_tag": False,
        "root_pom_file_tag_count": 0,
        "erro": False,
    }

    if not has_root:
        return result

    try:
        has_file, count_file = _pom_has_file_tag_anywhere(root_pom)
        result["root_pom_has_file_tag"] = has_file
        result["root_pom_file_tag_count"] = count_file
    except Exception:
        result["erro"] = True

    return result

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # usa o mesmo read_args do seu projeto para carregar a lista de repositórios
    args = read_args(
        'validate_root_pom_file_tag',
        'Valida se existe pom.xml na raiz e se o POM possui tag <file> em qualquer nível.',
        default_label_type="vulnerabilities",
        default_skip_remove=True
    )
    extra = parse_extra_cli()

    db.connect()

    projects = get_or_create_projects(
        create_version=False,
        filename=args.input,
        filters=args.filter,
        min_project=args.min_project,
        max_project=args.max_project,
        skip_remove=args.skip_remove
    )

    print(f"\nFound {len(projects)} projects. Validating...\n")
    header = "owner,name,repo_path,has_root_pom,root_pom_has_file_tag,root_pom_file_tag_count,erro_no_caminho"
    print(header)

    rows = []
    for project in projects:
        repo_path = build_repo_path(project.owner, project.name)
        diag = validate_root_pom_and_file_tag(repo_path)

        print(f"{project.owner},{project.name},{repo_path},"
              f"{diag['has_root_pom']},{diag['root_pom_has_file_tag']},"
              f"{diag['root_pom_file_tag_count']},{diag.get('erro', False)}")

        rows.append({
            "owner": project.owner,
            "name": project.name,
            "repo_path": str(repo_path),
            "has_root_pom": bool(diag["has_root_pom"]),
            "root_pom_has_file_tag": bool(diag["root_pom_has_file_tag"]),
            "root_pom_file_tag_count": int(diag["root_pom_file_tag_count"]),
            "erro_no_caminho": bool(diag.get("erro", False)),
        })

    # Saídas em CSV
    try:
        import csv
        fieldnames = [
            "owner","name","repo_path",
            "has_root_pom","root_pom_has_file_tag","root_pom_file_tag_count",
            "erro_no_caminho"
        ]
        with open(extra.out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        print(f"\n[OK] CSV salvo em: {extra.out_csv}")
    except Exception as e:
        print(yellow(f"[WARN] Falha ao salvar CSV: {e}"))

    # XLSX (se pandas disponível)
    if HAS_PANDAS:
        try:
            df = pd.DataFrame(rows)
            resumo = pd.DataFrame([
                {"metric": "projetos_com_pom_raiz", "value": int(df["has_root_pom"].sum())},
                {"metric": "poms_raiz_com_tag_file", "value": int(df["root_pom_has_file_tag"].sum())},
                {"metric": "total_tags_file_encontradas", "value": int(df["root_pom_file_tag_count"].sum())},
            ])
            with pd.ExcelWriter(extra.out_xlsx, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="validacao")
                resumo.to_excel(writer, index=False, sheet_name="resumo")
            print(f"[OK] XLSX salvo em: {extra.out_xlsx}")
        except Exception as e:
            print(yellow(f"[WARN] Falha ao salvar XLSX: {e}"))
    else:
        print(yellow("[INFO] pandas não instalado; XLSX não gerado. Instale com: pip install pandas openpyxl"))

    db.close()

if __name__ == "__main__":
    main()
