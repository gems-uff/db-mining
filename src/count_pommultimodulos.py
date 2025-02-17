import os
import pandas as pd
import xml.etree.ElementTree as ET
from util import ANNOTATED_FILE_JAVA_TEST

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

def check_projects_multimodule(xlsx_path):
    """Lê a lista de projetos do XLSX e verifica se possuem multimódulos"""
    df = pd.read_excel(xlsx_path)
    results = []

    for _, row in df.iterrows():
        project_path = row[0]  # Supondo que a primeira coluna contém o caminho dos projetos
        pom_path = os.path.join(project_path, "pom.xml")

        if os.path.exists(pom_path):
            is_multimodule = is_multimodule_pom(pom_path)
            results.append({"project": project_path, "multimodule": is_multimodule})
        else:
            results.append({"project": project_path, "multimodule": None})  # Nenhum pom.xml encontrado

    # Criar DataFrame para salvar resultados
    result_df = pd.DataFrame(results)
    result_df.to_excel("multimodule_projects.xlsx", index=False)

    # Contagem final
    multimodule_count = sum(1 for r in results if r["multimodule"] is True)
    non_multimodule_count = sum(1 for r in results if r["multimodule"] is False)
    no_pom_count = sum(1 for r in results if r["multimodule"] is None)

    print(f"Projetos com multimódulos: {multimodule_count}")
    print(f"Projetos sem multimódulos: {non_multimodule_count}")
    print(f"Projetos sem pom.xml: {no_pom_count}")

# Caminho do seu arquivo XLSX
check_projects_multimodule(ANNOTATED_FILE_JAVA_TEST)
