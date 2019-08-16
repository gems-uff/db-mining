import errno
import requests
import os

def process(result):
    print(result)

def main():
    token = os.getenv('GITHUB_TOKEN')
    if not token:
        print(
            'Please, set the GITHUB_TOKEN environment variable with your OAuth token (https://help.github.com/en/articles/creating-a-personal-access-token-for-the-command-line)')
        exit(errno.EACCES)
    headers = {
        'Authorization': f'bearer {token}'
    }

    GRAPHQL_QUERY = """
    query ($github_query: String!, $cursor: String) {
        rateLimit {
            cost
            remaining
        }
        search(query: $github_query, type: REPOSITORY, first: 2, after: $cursor) {
            pageInfo {
                endCursor
                hasNextPage
            }
            repositoryCount
            nodes {
                ... on Repository {
                    resourcePath
                    pushedAt
                    stargazers {
                        totalCount
                    }
                    primaryLanguage {
                        name
                    }
                    languages(first: 10) {
                        nodes {
                            ... on Language {
                                name
                            }
                        }
                    }
                    refs(refPrefix: "refs/heads/", first: 10) {
                        totalCount
                        nodes {
                            name
                            target {       
                                ... on Commit {
                                    history {
                                        totalCount
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    """

    variables = {
        "github_query": "is:public mirror:false archived:false fork:false stars:>=100000 pushed:>=2019-07-15 sort:stars"
    }

    request = {
        'query': GRAPHQL_QUERY,
        'variables': variables
    }

    has_next_page = True
    while has_next_page:
        response = requests.post(url="https://api.github.com/graphql", json=request, headers=headers)
        result = response.json()

        process(result)

        page_info = result['data']['search']['pageInfo']
        if page_info['hasNextPage']:
            variables['cursor'] = page_info['endCursor']
        else:
           has_next_page = False

if __name__ == "__main__":
    main()