import time
from pprint import pprint
import pandas as pd

import requests
import os


def process(some_repositories, all_repositories):
    for repo in some_repositories:
        # Flattening fields
        for k, v in repo.items():
            while isinstance(v, dict):
                v = next(iter(v.values()))
            repo[k] = v

        all_repositories.append(repo)


def save(all_repositories):
    df = pd.DataFrame(all_repositories)
    df.to_excel('projects.xlsx', index=False)


def main():
    token = os.getenv('GITHUB_TOKEN')
    if not token:
        print(
            'Please, set the GITHUB_TOKEN environment variable with your OAuth token (https://help.github.com/en/articles/creating-a-personal-access-token-for-the-command-line)')
        exit(1)
    headers = {
        'Authorization': f'bearer {token}'
    }

    variables = {
        "projectsPerPage": 10,  # from 1 to 100
        "cursor": None
    }

    request = {
        'query': open('query.graphql', 'r').read(),
        'variables': variables
    }

    # AIMD parameters for auto-tuning the page size
    ai = 2  # slow start: 2, 4, 8, 10 (max)
    md = 0.5

    all_repositories = []
    has_next_page = True
    while has_next_page:
        print(f'Trying to retrieve the next {variables["projectsPerPage"]} projects...')
        response = requests.post(url="https://api.github.com/graphql", json=request, headers=headers)
        result = response.json()

        if 'Retry-After' in response.headers:  # reached retry limit
            print(f'Waiting for {response.headers["Retry-After"]} seconds before continuing...', end=' ')
            time.sleep(int(response.headers['Retry-After']))

        if 'errors' in result:
            if 'timeout' in result['errors'][0]['message']:  # reached timeout
                print(f'Timeout!', end=' ')
                variables['projectsPerPage'] = int(max(1, variables['projectsPerPage'] * md))  # using AIMD
                ai = 2  # resetting slow start
            else:  # some unexpected error
                pprint(result['error'])
                exit(1)

        if 'data' in result and result['data']:
            process(result['data']['search']['nodes'], all_repositories)
            print(f'Processed {len(all_repositories)} of {result["data"]["search"]["repositoryCount"]} projects.', end=' ')

            page_info = result['data']['search']['pageInfo']
            if page_info['hasNextPage']:  # We still have pending projects
                variables['cursor'] = page_info['endCursor']
                variables['projectsPerPage'] = min(100, variables['projectsPerPage'] + ai)  # using AIMD
                ai = min(10, ai * 2)  # slow start
            else:  # We finished processing all projects
                print(f'Finished.')
                has_next_page = False

        time.sleep(1)  # Wait 1 second before next request (https://developer.github.com/v3/#abuse-rate-limits)

    save(all_repositories)


if __name__ == "__main__":
    main()
