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

def process_directory(repo, path, token=None):
    vulnerabilities = []
    stack = [path]

    while stack:
        current_path = stack.pop()
        items = fetch_github_contents(repo, current_path, token)
        for item in items:
            if item["type"] == "dir":
                stack.append(item["path"])
            elif item["type"] == "file" and item["name"].endswith(".json"):
                file_content = fetch_file_content(item["download_url"], token)
                if file_content:
                    vulnerabilities.append({
                        "id": file_content.get("id"),
                        "published": file_content.get("published"),
                        "aliases": file_content.get("aliases", []),
                        "severity": file_content.get("database_specific", {})
                                                .get("severity"),
                    })
    return vulnerabilities

def display_results(vulnerabilities):
    print(f"Total de vulnerabilidades encontradas: {len(vulnerabilities)}\n")
    for vuln in vulnerabilities:
        print(f"ID: {vuln['id']}")
        print(f"Publicado: {vuln['published']}")
        print(f"Aliases: {', '.join(vuln['aliases'])}")
        print(f"Ecossistema: {vuln['ecosystem']}")
        print(f"Versão vulnerável: {vuln['version']}")
        print(f"URLs: {', '.join(vuln['urls'])}")
        print(f"Gravidade: {vuln['severity']}")
        print("-" * 40)

def main():
    repo = "github/advisory-database"
    base_path = "advisories/"
    

    print(f"Buscando vulnerabilidades no repositório {repo} em {base_path}...\n")
    vulnerabilities = process_directory(repo, base_path, token)
    display_results(vulnerabilities)

if __name__ == "__main__":
    main()
