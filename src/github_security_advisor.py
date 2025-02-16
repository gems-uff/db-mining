import requests
import json
import os

def fetch_github_contents(repo, path, token=None):
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"token {token}"} if token else {}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Erro ao acessar {path}: {response.status_code} - {response.text}")
        return []

def fetch_file_content(file_url, token=None):
    headers = {"Authorization": f"token {token}"} if token else {}
    response = requests.get(file_url, headers=headers)
    if response.status_code == 200:
        return json.loads(response.text)
    else:
        print(f"Erro ao baixar o arquivo: {response.status_code} - {response.text}")
        return None

def process_directory(repo, path, token=None, limit=10):
    vulnerabilities = []
    stack = [path]
    count = 0  # Contador de itens processados

    while stack and count < limit:
        current_path = stack.pop()
        items = fetch_github_contents(repo, current_path, token)
        print(f"Acessando o repositório: {current_path}")

        for item in items:
            if count >= limit:
                break  # Sai do loop quando atingir o limite

            if item["type"] == "dir":
                stack.append(item["path"])
            elif item["type"] == "file" and item["name"].endswith(".json"):
                file_content = fetch_file_content(item["download_url"], token)
                if file_content:
                    #print(file_content)
                    affected = file_content.get("affected", {})
                    vulnerabilities.append({
                        "id": file_content.get("id"),
                        "schema_version": file_content.get("schema_version"),
                        "published": file_content.get("published"),
                        "aliases": file_content.get("aliases", []),
                        "details": file_content.get("details", "Sem detalhes disponíveis"),
                        "ecosystem": affected[0].get("package", {}).get("ecosystem"),
                        "name": affected[0].get("package", {}).get("name"),
                        "severity": file_content.get("database_specific", {}).get("severity"),
                                
                    })
                    count += 1  # Incrementa o contador após processar um item
    return vulnerabilities

def display_results(vulnerabilities):
    print(f"Total de vulnerabilidades encontradas: {len(vulnerabilities)}\n")
    for vuln in vulnerabilities:
        print(f"ID: {vuln['id']}")
        print(f"SchemaVersion: {vuln['schema_version']}")
        print(f"Publicado: {vuln['published']}")
        print(f"Aliases: {', '.join(vuln['aliases'])}")
        print(f"Details: {vuln['details']}")
        print(f"Ecosystem: {vuln['ecosystem'] if vuln['ecosystem'] else 'Desconhecido'}")  # Lista de ecossistemas
        print(f"Name: {vuln['name'] if vuln['name'] else 'Desconhecido'}")
        print(f"Gravidade: {vuln['severity']}")
        print("-" * 40)

def main():
    repo = "github/advisory-database"
    base_path = "advisories/github-reviewed"
    token = ''

    print(f"Buscando vulnerabilidades no repositório {repo} em {base_path}...\n")
    vulnerabilities = process_directory(repo, base_path, token, limit=10)
    display_results(vulnerabilities)

if __name__ == "__main__":
    main()