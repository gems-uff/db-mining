#Script to Identify pom.xml Files Containing Dependencies Without a <version> Tag

from util import REPOS_DIR
import csv
import os
import xml.etree.ElementTree as ET

"""
Descrição:
-----------
Este script percorre todos os repositórios localizados em `REPOS_DIR` e analisa cada arquivo
`pom.xml` encontrado, verificando se há dependências Maven declaradas sem a tag <version>.
O objetivo é identificar projetos que dependem implicitamente de versões herdadas (via parent POM
ou dependencyManagement), o que pode indicar configurações frágeis ou dependências não explicitamente
definidas.

Funcionamento:
---------------
1. Varre recursivamente a pasta base (`REPOS_DIR`) em busca de arquivos `pom.xml`.
2. Para cada `pom.xml` encontrado:
   - Faz o parsing do XML utilizando o namespace Maven padrão (`http://maven.apache.org/POM/4.0.0`);
   - Busca todos os elementos `<dependency>`;
   - Verifica se há algum `<dependency>` sem a tag `<version>`.
3. Registra o nome do projeto (extraído do caminho do arquivo) caso alguma dependência esteja sem versão.
4. Gera um relatório CSV contendo apenas os nomes dos projetos afetados.

Saídas:
--------
- `projects_with_missing_versions.csv`: arquivo CSV com a lista dos projetos que possuem pelo menos
  uma dependência sem `<version>`.
- Resumo exibido no console com:
  - Total de projetos analisados;
  - Total de projetos com dependências sem versão;
  - Lista dos projetos identificados.
"""

NAMESPACE = {'m': 'http://maven.apache.org/POM/4.0.0'}

def extract_project_name(path):
    """
    Extrai o quarto item do caminho para identificar o nome do projeto.
    """
    parts = path.split(os.sep)
    return parts[6] if len(parts) > 6 else "Unknown"

def has_dependency_without_version(pom_path):
    """
    Verifica se o pom.xml possui ao menos uma dependência sem a tag <version>.
    """
    try:
        tree = ET.parse(pom_path)
        root = tree.getroot()
        dependencies = root.findall('.//m:dependency', NAMESPACE)
        for dep in dependencies:
            if dep.find('m:version', NAMESPACE) is None:
                return True
    except ET.ParseError:
        print(f"Erro ao analisar XML: {pom_path}")
    except Exception as e:
        print(f"Erro ao processar {pom_path}: {e}")
    return False

def find_projects_with_missing_versions(base_path):
    """
    Retorna uma lista com os nomes dos projetos que possuem ao menos um pom.xml com dependência sem <version>
    e a contagem total de projetos analisados.
    """
    projects_with_missing_versions = set()
    total_projects_analyzed = set()

    for root, dirs, files in os.walk(base_path):
        if 'pom.xml' in files:
            project_name = extract_project_name(root)
            if project_name == "Unknown":
                continue

            total_projects_analyzed.add(project_name)

            pom_path = os.path.join(root, "pom.xml")
            if has_dependency_without_version(pom_path):
                projects_with_missing_versions.add(project_name)

    return sorted(projects_with_missing_versions), len(total_projects_analyzed)

def save_results_to_csv(project_names, output_file):
    with open(output_file, mode='w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Project Name"])
        for project in project_names:
            writer.writerow([project])

def main():
    if not os.path.exists(REPOS_DIR):
        print(f"A pasta '{REPOS_DIR}' não existe. Verifique o caminho.")
        return

    print("Buscando projetos com pom.xml contendo dependências sem <version>...")
    projects, total_projects = find_projects_with_missing_versions(REPOS_DIR)
    output_file = "projects_with_missing_versions.csv"
    save_results_to_csv(projects, output_file)

    print(f"Relatório salvo em: {output_file}")
    print("\nResumo:")
    print(f"Total de projetos analisados: {total_projects}")
    print(f"Total de projetos com dependências sem <version>: {len(projects)}")
    for project in projects:
        print(f"- {project}")

if __name__ == "__main__":
    main()
