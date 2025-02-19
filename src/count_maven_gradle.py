from util import REPOS_DIR, BUILD_TOOLS_REPORT
import csv
import os
import xml.etree.ElementTree as ET
from collections import defaultdict

def extract_project_name(path):
    """
    Extrai o quarto item do caminho para identificar o nome do projeto.
    """
    parts = path.split(os.sep)
    return parts[4] if len(parts) > 4 else "Unknown"

def is_multimodule_pom(pom_path):
    """Verifica se um arquivo pom.xml contém a tag <modules> indicando multimódulos"""
    try:
        tree = ET.parse(pom_path)
        root = tree.getroot()
        namespaces = {'mvn': 'http://maven.apache.org/POM/4.0.0'}  # Namespace do Maven
        return root.find("mvn:modules", namespaces) is not None
    except ET.ParseError:
        print(f"Erro ao analisar XML: {pom_path}")
    except Exception as e:
        print(f"Erro ao verificar {pom_path}: {e}")
    return False

def identify_build_tools(base_path):
    project_tools = defaultdict(lambda: {"Maven": 0, "Gradle": 0, "Multimodule": 0})
    total_projects = 0
    multimodule_projects = 0
    
    for root, dirs, files in os.walk(base_path):
        project_name = extract_project_name(root)
        
        if project_name == "Unknown":
            continue

        if 'pom.xml' in files:
            project_tools[project_name]["Maven"] += 1
            pom_path = os.path.join(root, "pom.xml")
            if is_multimodule_pom(pom_path):
                project_tools[project_name]["Multimodule"] += 1
                multimodule_projects += 1

        elif 'build.gradle' in files or 'build.gradle.kts' in files:
            project_tools[project_name]["Gradle"] += 1
        
        total_projects += 1
        if total_projects % 10 == 0:  # Log a cada 10 projetos analisados
            print(f"Projetos analisados: {total_projects}, com multimódulos: {multimodule_projects}")

    return project_tools

def save_results_to_csv(project_tools, output_file):
    with open(output_file, mode='w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Project Name", "Maven Count", "Gradle Count", "Multimodule Count"])

        for project, tools in project_tools.items():
            writer.writerow([project, tools["Maven"], tools["Gradle"], tools["Multimodule"]])

def main():
    if not os.path.exists(REPOS_DIR):
        print(f"A pasta '{REPOS_DIR}' não existe. Certifique-se de que o caminho está correto.")
        return

    print("Iniciando a análise dos projetos...")
    project_tools = identify_build_tools(REPOS_DIR)
    print("Análise concluída.")

    save_results_to_csv(project_tools, BUILD_TOOLS_REPORT)
    print(f"Resultados salvos no arquivo: {BUILD_TOOLS_REPORT}")

    print("\n=== Resumo ===")
    total_projects = len(project_tools)
    multimodule_projects = sum(1 for tools in project_tools.values() if tools["Multimodule"] > 0)
    print(f"Total de projetos analisados: {total_projects}")
    print(f"Projetos com multimódulos: {multimodule_projects}")

if __name__ == "__main__":
    main()
