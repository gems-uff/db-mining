import requests
from requests.auth import HTTPBasicAuth

# Credenciais (substitua pelos seus dados)
USERNAME = "camila.acacio.paiva@gmail.com"
API_TOKEN = "57a1511224eb4cd7f8de724d493ed3226ae5fc15"

# Endpoint da API do OSS Index
API_URL = "https://ossindex.sonatype.org/api/v3/component-report"

# Pacote a ser consultado
package_purl = "pkg:maven/org.postgresql/postgresql@2.6.0"
payload = {"coordinates": [package_purl]}

# Requisição autenticada
response = requests.post(API_URL, json=payload, auth=HTTPBasicAuth(USERNAME, API_TOKEN))

# Exibir resposta
if response.status_code == 200:
    print(response.json())
else:
    print(f"Erro {response.status_code}: {response.text}")

