#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validação de repositórios (DB-mining):
- Detecta POM na raiz (aceita pom.xml e variações: *pom.xml, ex.: build-pom.xml)
- Verifica se há bytes/texto antes da declaração XML (<?xml ...?>), incluindo BOM
- Verifica se o POM da raiz contém tag <file> em qualquer nível (namespaceless ou com prefixo)
- Gera CSV/XLSX com resultados e um pequeno resumo
"""

import os
import re
import glob
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Tuple, Dict, List, Optional

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
# Helpers XML / leitura
# ---------------------------------------------------------------------------

def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

def _read_bytes(p: Path) -> bytes:
    try:
        return p.read_bytes()
    except Exception:
        return b""

def _read_xml_ns_aware(p: Path):
    """
    Retorna (root, txt, q) onde:
      - root: ElementTree root ou None se parsing falhar
      - txt: conteúdo textual do arquivo (sempre)
      - q(name): helper para compor tag com namespace detectado (ou nome simples)
    """
    txt = _read_text(p)
    if not txt:
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

# ---------------------------------------------------------------------------
# Detecção da tag <file>
# ---------------------------------------------------------------------------

FILE_TAG_RE = re.compile(
    r"<(?:[\w-]+:)?file\b[^>]*>.*?</(?:[\w-]+:)?file\s*>",
    flags=re.IGNORECASE | re.DOTALL
)

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

    matches = FILE_TAG_RE.findall(txt)
    return (len(matches) > 0, len(matches))

# ---------------------------------------------------------------------------
# POM na raiz (suporta variações de nome) + preâmbulo XML
# ---------------------------------------------------------------------------

def _score_pom_candidate(path: Path) -> tuple:
    """
    Heurística de ordenação para candidatos *pom.xml:
      1) 'pom.xml' primeiro
      2) caminhos mais curtos
      3) nome lexicográfico
    """
    name = path.name.lower()
    is_plain = (name == "pom.xml")
    return (0 if is_plain else 1, len(name), name)

def find_root_pom_path(repo_root: Path) -> Optional[Path]:
    """
    Procura POM na raiz:
      - prioridade: 'pom.xml'
      - senão, qualquer '*pom.xml' (ex.: 'build-pom.xml', 'parent-pom.xml'), exceto 'effective-pom.xml' e 'settings.xml'
    """
    repo_root = repo_root.resolve()
    exact = repo_root / "pom.xml"
    if exact.is_file():
        return exact

    # busca por variações
    candidates = []
    for pat in ("*pom.xml", "*-pom.xml", "*_pom.xml"):
        candidates.extend(Path(repo_root).glob(pat))
    # filtra arquivos óbvios que não são POM de projeto
    filtered = [
        p for p in set(candidates)
        if p.is_file()
        and p.name.lower() not in {"effective-pom.xml", "settings.xml"}
    ]
    if not filtered:
        return None
    filtered.sort(key=_score_pom_candidate)
    return filtered[0]

XML_DECL_RE = re.compile(rb"<\?xml\s+version\s*=\s*['\"]1\.[0-9]['\"][^?]*\?>", re.IGNORECASE)

def analyze_xml_preamble(pom_path: Path) -> Dict[str, object]:
    """
    Verifica condições problemáticas antes da declaração XML:
      - Presença de BOM UTF-8
      - Bytes não-brancos antes de '<?xml ...?>'
      - Preview (até 40 bytes iniciais, em escape) para depuração
    """
    data = _read_bytes(pom_path)
    info = {
        "has_bom": False,
        "has_bytes_before_xml_decl": False,
        "xml_decl_found": False,
        "preamble_preview": "",
    }
    if not data:
        return info

    # Preview para depuração
    info["preamble_preview"] = repr(data[:40])

    # BOM UTF-8 = EF BB BF
    if data.startswith(b"\xEF\xBB\xBF"):
        info["has_bom"] = True
        # Ignora BOM ao procurar a declaração
        search_data = data[3:]
    else:
        search_data = data

    # Posição da declaração XML
    m = XML_DECL_RE.search(search_data)
    if not m:
        # Se não tem declaração, mas há qualquer byte não-branco antes do primeiro '<', sinaliza como "antes da raiz"
        info["xml_decl_found"] = False
        first_non_ws = next((i for i, b in enumerate(search_data) if chr(b).strip() != ""), None)
        if first_non_ws is not None and search_data[first_non_ws:first_non_ws+1] != b"<":
            info["has_bytes_before_xml_decl"] = True
        return info

    info["xml_decl_found"] = True
    start = m.start()

    # Existem bytes não-brancos antes da declaração?
    leading = search_data[:start]
    if any(chr(b).strip() != "" for b in leading):
        info["has_bytes_before_xml_decl"] = True

    return info

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
    Valida:
      - se há POM na raiz (pom.xml ou variações *pom.xml)
      - se existem bytes/texto antes da declaração XML (<?xml ...?>), incluindo BOM
      - se o POM contém tag <file> (qualquer nível)
    """
    repo_root = repo_root.resolve()
    root_pom = find_root_pom_path(repo_root)
    has_root = root_pom is not None

    result = {
        "has_root_pom": has_root,
        "root_pom_path": str(root_pom) if root_pom else "",
        "root_pom_has_file_tag": False,
        "root_pom_file_tag_count": 0,
        "xml_has_bom": False,
        "xml_has_bytes_before_decl": False,
        "xml_decl_found": False,
        "xml_preamble_preview": "",
        "erro": False,
    }

    if not has_root:
        return result

    try:
        # Preambulo/declaração XML
        pre = analyze_xml_preamble(root_pom)
        result["xml_has_bom"] = bool(pre["has_bom"])
        result["xml_has_bytes_before_decl"] = bool(pre["has_bytes_before_xml_decl"])
        result["xml_decl_found"] = bool(pre["xml_decl_found"])
        result["xml_preamble_preview"] = pre["preamble_preview"]

        # Tag <file>
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
    args = read_args(
        'validate_root_pom_file_tag',
        'Valida POM na raiz (nome padrão ou variações), preâmbulo XML e presença de <file>.',
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
    header = ("owner,name,repo_path,has_root_pom,root_pom_path,"
              "xml_decl_found,xml_has_bom,xml_has_bytes_before_decl,root_pom_has_file_tag,"
              "root_pom_file_tag_count,erro_no_caminho")
    print(header)

    rows = []
    for project in projects:
        repo_path = build_repo_path(project.owner, project.name)
        diag = validate_root_pom_and_file_tag(repo_path)

        print(f"{project.owner},{project.name},{repo_path},"
              f"{diag['has_root_pom']},{diag['root_pom_path']},"
              f"{diag['xml_decl_found']},{diag['xml_has_bom']},{diag['xml_has_bytes_before_decl']},"
              f"{diag['root_pom_has_file_tag']},{diag['root_pom_file_tag_count']},"
              f"{diag.get('erro', False)}")

        rows.append({
            "owner": project.owner,
            "name": project.name,
            "repo_path": str(repo_path),
            "has_root_pom": bool(diag["has_root_pom"]),
            "root_pom_path": diag["root_pom_path"],
            "xml_decl_found": bool(diag["xml_decl_found"]),
            "xml_has_bom": bool(diag["xml_has_bom"]),
            "xml_has_bytes_before_decl": bool(diag["xml_has_bytes_before_decl"]),
            "xml_preamble_preview": diag["xml_preamble_preview"],
            "root_pom_has_file_tag": bool(diag["root_pom_has_file_tag"]),
            "root_pom_file_tag_count": int(diag["root_pom_file_tag_count"]),
            "erro_no_caminho": bool(diag.get("erro", False)),
        })

    # Saídas em CSV
    try:
        import csv
        fieldnames = [
            "owner","name","repo_path",
            "has_root_pom","root_pom_path",
            "xml_decl_found","xml_has_bom","xml_has_bytes_before_decl","xml_preamble_preview",
            "root_pom_has_file_tag","root_pom_file_tag_count",
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
                {"metric": "poms_com_bytes_antes_da_decl", "value": int(df["xml_has_bytes_before_decl"].sum())},
                {"metric": "poms_com_bom_utf8", "value": int(df["xml_has_bom"].sum())},
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
