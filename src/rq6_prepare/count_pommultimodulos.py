import os
import xml.etree.ElementTree as ET
from util import ANNOTATED_FILE_JAVA_TEST, REPOS_DIR

import pandas as pd

def is_multimodule_pom(pom_path):
    """Verifica se um arquivo pom.xml contém a tag <modules> indicando multimódulos"""
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

def is_multimodule_gradle(build_path):
    """Verifica se um arquivo build.gradle ou build.gradle.kts contém referências a subprojetos, indicando multimódulos"""
    try:
        with open(build_path, 'r', encoding='utf-8') as file:
            content = file.read()
            return 'include' in content or 'subprojects' in content
    except Exception as e:
        print(f"Erro ao verificar {build_path}: {e}")
    return False

def find_build_files(project_path):
    """Busca recursivamente por pom.xml, build.gradle e build.gradle.kts em pastas e subpastas"""
    pom_file = None
    gradle_file = None
    gradle_kts_file = None

    for root, _, files in os.walk(project_path):
        if 'pom.xml' in files:
            pom_file = os.path.join(root, 'pom.xml')
        if 'build.gradle' in files:
            gradle_file = os.path.join(root, 'build.gradle')
        if 'build.gradle.kts' in files:
            gradle_kts_file = os.path.join(root, 'build.gradle.kts')

        if pom_file or gradle_file or gradle_kts_file:
            break

    return pom_file, gradle_file or gradle_kts_file

def check_projects_multimodule(xlsx_path):
    """Lê a lista de projetos do XLSX e verifica se possuem multimódulos para Maven ou Gradle"""
    df = pd.read_excel(xlsx_path)
    results = []

    for _, row in df.iterrows():
        project_path = REPOS_DIR + "/" + row[0] + "/" + row[1] 
        project_path_name = row[0] + "/" + row[1]
        pom_path, gradle_path = find_build_files(project_path)

        if pom_path:
            multimodule = is_multimodule_pom(pom_path)
            tool = 'Maven'
        elif gradle_path:
            multimodule = is_multimodule_gradle(gradle_path)
            tool = 'Gradle'
        else:
            multimodule = None
            tool = 'None'

        results.append({
            "project": project_path_name,
            "tool": tool,
            "multimodule": multimodule
        })

    result_df = pd.DataFrame(results)
    result_df.to_excel("multimodule_projects.xlsx", index=False)

    # Contagem por ferramenta
    maven_count = result_df[result_df['tool'] == 'Maven'].shape[0]
    gradle_count = result_df[result_df['tool'] == 'Gradle'].shape[0]
    no_build_count = result_df[result_df['tool'] == 'None'].shape[0]

    multimodule_maven = result_df[(result_df['tool'] == 'Maven') & (result_df['multimodule'] == True)].shape[0]
    multimodule_gradle = result_df[(result_df['tool'] == 'Gradle') & (result_df['multimodule'] == True)].shape[0]

    print(f"Projetos Maven: {maven_count}")
    print(f"Projetos Gradle: {gradle_count}")
    print(f"Projetos sem ferramenta de build: {no_build_count}")
    print(f"Projetos Maven multimódulo: {multimodule_maven}")
    print(f"Projetos Gradle multimódulo: {multimodule_gradle}")

check_projects_multimodule(ANNOTATED_FILE_JAVA_TEST)
