import pandas as pd
import requests

from util import ANNOTATED_FILE_JAVA_COMPLET

# Função para carregar a lista de projetos de um arquivo Excel
def load_projects_from_excel(file_path):
    df = pd.read_excel(file_path, sheet_name='2021')
    
    # Verificar as linhas onde a coluna 'contributors_2024' está vazia
    vazio_contributors = df[df['discardReason'].isnull() & df['contributors_2024'].isnull()]

    # Concatenar as colunas 'owner' e 'name' em uma lista
    concatenacao = (vazio_contributors['owner'] + '/' + vazio_contributors['name']).tolist()
    # Retornar a lista resultante
    print(len(concatenacao))

    # Opcional: se você quiser preencher a coluna 'contributors_2024' com essa lista
    #df.loc[df['contributors_2024'].isnull(), 'contributors_2024'] = concatenacao
    
    return concatenacao  # Supondo que a coluna dos repositórios seja chamada 'repo_url'

# Função para obter dados de um projeto do GitHub usando a API
def get_github_project_info(repo_url, token):
    # Extraindo o nome do repositório a partir da URL
    repo_name = '/'.join(repo_url.split('/')[-2:])
    url = f"https://api.github.com/repos/{repo_name}"

    # Cabeçalho com o token de autenticação
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }
    
    # Fazendo a requisição GET à API do GitHub
    response = requests.get(url, headers=headers)
    
    # Verificando se a requisição foi bem-sucedida
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Erro ao buscar dados para o repositório: {repo_name} - Status Code: {response.status_code}")
        return None


def get_contributors(repo_url, token):
    repo_name = '/'.join(repo_url.split('/')[-2:])
    url = f"https://api.github.com/repos/{repo_name}/contributors"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }
    contributors_count = 0
    page = 1

    while True:
        response = requests.get(url, headers=headers, params={'page': page})
        if response.status_code != 200:
            print(f"Erro ao buscar contribuidores: {response.status_code} - {response.text}")
            break
        
        data = response.json()
        if not data:  # Se não houver mais dados, saia do loop
            break

        contributors_count += len(data)
        page += 1

    return contributors_count



# Função principal
def main():
    df = pd.read_excel(ANNOTATED_FILE_JAVA_COMPLET, sheet_name='2021')
    # Carregando a lista de projetos
    project_urls = load_projects_from_excel(ANNOTATED_FILE_JAVA_COMPLET)
    
    # Token do GitHub (insira o seu token aqui)
    github_token = ''
    
    # Lista para armazenar os resultados
    project_data = []

    # Iterando sobre a lista de URLs dos projetos
    for repo_url in project_urls:
        data = get_github_project_info(repo_url, github_token)
        if data:
            project_data.append({
                'repo_name': repo_url,
                'starsAPI': data['stargazers_count'],
                'forksAPI': data['forks_count'],
                'commits_urlAPI': data['commits_url'].split('{')[0],  # Removendo parâmetros adicionais da URL
                'open_issuesAPI': data['open_issues_count'],
                'contributorsAPI': get_contributors(repo_url, github_token),
                'isFork': data['fork']
            })
    
    # Exibindo os dados coletados
    print(len(project_data))
    for project in project_data:
        print(f"Repositório: {project['repo_name']}, Estrelas: {project['starsAPI']}, Forks: {project['forksAPI']}, "
              f"Issues Abertas: {project['open_issuesAPI']}, Contributors: {project['contributorsAPI']}")

    # Criar um DataFrame com os dados do GitHub
    df_github = pd.DataFrame(project_data)

    # Separar 'owner' e 'name' da coluna 'repo_name' do GitHub
    #df_github[['owner', 'name']] = df_github['repo_name'].str.split('/', expand=True)

    #df_merged = pd.merge(df, df_github, on=['owner', 'name'], how='left')
    
    #df_merged['stargazers_2024'] = df_merged['stargazers_2024'].combine_first(df_merged['starsAPI'])
    #df_merged['forks_2024'] = df_merged['forks_2024'].combine_first(df_merged['forksAPI'])
    #df_merged['commits_2024'] = df_merged['commits_2024'].combine_first(df_merged['commits_urlAPI'])
    #df_merged['contributors_2024'] = df_merged['contributors_2024'].combine_first(df_merged['watchersAPI'])


    # Salvar o DataFrame atualizado em um novo arquivo Excel
    df_github.to_excel('df_maior_atualizado.xlsx', index=False)

    print("Arquivo atualizado salvo com sucesso!")

    

if __name__ == "__main__":
    main()
