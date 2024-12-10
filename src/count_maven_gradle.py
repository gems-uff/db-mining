import os
from util import REPOS_DIR, BUILD_TOOLS_REPORT 
import csv

def identify_build_tools(base_path):
    maven_projects = []
    gradle_projects = []

    for root, dirs, files in os.walk(base_path):
        # Verifica arquivos característicos na pasta atual
        if 'pom.xml' in files:
            maven_projects.append(root)
        elif 'build.gradle' in files or 'build.gradle.kts' in files:
            gradle_projects.append(root)

    return maven_projects, gradle_projects

def save_results_to_csv(maven_projects, gradle_projects, output_file):
    with open(output_file, mode='w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Project Path", "Build Tool"])

        for project in maven_projects:
            writer.writerow([project, "Maven"])
        for project in gradle_projects:
            writer.writerow([project, "Gradle"])

def main():
    #base_path = "repos"  # Caminho para a pasta que contém os projetos
    #output_file = "build_tools_report.csv"  # Nome do arquivo CSV de saída

    if not os.path.exists(REPOS_DIR):
        print(f"A pasta '{REPOS_DIR}' não existe. Certifique-se de que o caminho está correto.")
        return

    # Identificar projetos
    maven_projects, gradle_projects = identify_build_tools(REPOS_DIR)

    # Salvar resultados em CSV
    save_results_to_csv(maven_projects, gradle_projects, BUILD_TOOLS_REPORT)

    # Exibir resultados
    print("=== Resultados ===")
    print(f"Projetos que usam Maven ({len(maven_projects)}):")
    for project in maven_projects:
        print(f"  - {project}")

    print(f"\nProjetos que usam Gradle ({len(gradle_projects)}):")
    for project in gradle_projects:
        print(f"  - {project}")

    # Resumo
    total_projects = len(maven_projects) + len(gradle_projects)
    print("\n=== Resumo ===")
    print(f"Total de projetos analisados: {total_projects}")
    print(f"Usam Maven: {len(maven_projects)}")
    print(f"Usam Gradle: {len(gradle_projects)}")
    print(f"Resultados salvos no arquivo: {BUILD_TOOLS_REPORT}")

if __name__ == "__main__":
    main()
