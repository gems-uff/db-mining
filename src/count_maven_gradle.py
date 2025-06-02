import os
import csv
import xml.etree.ElementTree as ET
import pandas as pd
from collections import defaultdict
from util import REPOS_DIR, BUILD_TOOLS_REPORT, ANNOTATED_FILE_JAVA_TEST

def is_multimodule_pom(pom_path):
    try:
        tree = ET.parse(pom_path)
        root = tree.getroot()
        namespaces = {'mvn': 'http://maven.apache.org/POM/4.0.0'}
        return root.find("mvn:modules", namespaces) is not None
    except ET.ParseError:
        print(f"Erro ao analisar XML: {pom_path}")
    except Exception as e:
        print(f"Erro ao verificar {pom_path}: {e}")
    return False

def identify_build_tools_from_annotated(xlsx_path):
    df = pd.read_excel(xlsx_path)
    project_tools = defaultdict(lambda: {"Maven": 0, "Gradle": 0, "Multimodule": 0})
    
    total_projects = 0
    multimodule_projects = 0

    for _, row in df.iterrows():
        owner, name = row[0], row[1]
        project_path = os.path.join(REPOS_DIR, owner, name)
        if not os.path.exists(project_path):
            print(f"Caminho não encontrado: {project_path}")
            continue

        found = False
        for root, dirs, files in os.walk(project_path):
            if 'pom.xml' in files:
                project_tools[f"{owner}/{name}"]["Maven"] += 1
                pom_path = os.path.join(root, 'pom.xml')
                if is_multimodule_pom(pom_path):
                    project_tools[f"{owner}/{name}"]["Multimodule"] += 1
                    multimodule_projects += 1
                found = True
                break  # para na primeira ocorrência
            elif 'build.gradle' in files or 'build.gradle.kts' in files:
                project_tools[f"{owner}/{name}"]["Gradle"] += 1
                found = True
                break

        total_projects += 1
        if total_projects % 10 == 0:
            print(f"Projetos analisados: {total_projects}, com multimódulos: {multimodule_projects}")
        if not found:
            print(f"Nenhum arquivo de build encontrado em: {owner}/{name}")

    return project_tools

def save_results_to_csv(project_tools, output_file):
    with open(output_file, mode='w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Project Name", "Maven Count", "Gradle Count", "Multimodule Count"])
        for project, tools in project_tools.items():
            writer.writerow([project, tools["Maven"], tools["Gradle"], tools["Multimodule"]])

def main():
    if not os.path.exists(REPOS_DIR):
        print(f"A pasta '{REPOS_DIR}' não existe.")
        return

    print("Iniciando a análise dos projetos do annotated...")
    project_tools = identify_build_tools_from_annotated(ANNOTATED_FILE_JAVA_TEST)
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
