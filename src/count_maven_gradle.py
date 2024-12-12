from util import REPOS_DIR, BUILD_TOOLS_REPORT
import csv
import os
from collections import defaultdict

def extract_project_name(path):
    """
    Extrai o quarto item do caminho para identificar o nome do projeto.
    """
    parts = path.split(os.sep)
    return parts[4] if len(parts) > 4 else "Unknown"

def identify_build_tools(base_path):
    project_tools = defaultdict(lambda: {"Maven": 0, "Gradle": 0})

    for root, dirs, files in os.walk(base_path):
        # Verifica arquivos característicos na pasta atual
        if 'pom.xml' in files:
            project_name = extract_project_name(root)
            project_tools[project_name]["Maven"] += 1
        elif 'build.gradle' in files or 'build.gradle.kts' in files:
            project_name = extract_project_name(root)
            project_tools[project_name]["Gradle"] += 1

    return project_tools

def save_results_to_csv(project_tools, output_file):
    with open(output_file, mode='w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Project Name", "Maven Count", "Gradle Count"])

        for project, tools in project_tools.items():
            writer.writerow([project, tools["Maven"], tools["Gradle"]])

def main():
    if not os.path.exists(REPOS_DIR):
        print(f"A pasta '{REPOS_DIR}' não existe. Certifique-se de que o caminho está correto.")
        return

    # Identificar projetos e ferramentas de build
    project_tools = identify_build_tools(REPOS_DIR)

    # Salvar resultados em CSV
    save_results_to_csv(project_tools, BUILD_TOOLS_REPORT)

    # Exibir resultados
    print("=== Resultados ===")
    for project, tools in project_tools.items():
        print(f"Projeto: {project}")
        print(f"  - Maven: {tools['Maven']}")
        print(f"  - Gradle: {tools['Gradle']}")

    # Resumo
    total_projects = len(project_tools)
    print("\n=== Resumo ===")
    print(f"Total de projetos analisados: {total_projects}")
    print(f"Resultados salvos no arquivo: {BUILD_TOOLS_REPORT}")

if __name__ == "__main__":
    main()
