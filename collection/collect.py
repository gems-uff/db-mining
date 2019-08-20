import time
import datetime
from pprint import pprint
import pandas as pd

import requests
import os


def query_filter(min_stars=5000, max_stars=None, last_activity=90):
    """
    Builds the query filter string compatible to GitHub
    :param min_stars: minimum number of stargazers in the repository
    :param max_stars: maximum number of stargazers in the repository (do not change this parameter -- it is automatically set on demand to get more than 1,000 repositories).
    :param last_activity: number of days to check recent push activity in the repository
    :return: query filter string compatible to GitHub
    """
    date = datetime.datetime.now() - datetime.timedelta(days=last_activity)
    if max_stars:
        stars = f'{min_stars}..{max_stars}'
    else:
        stars = f'>={min_stars}'
    return f'is:public mirror:false archived:false fork:false stars:{stars} pushed:>={date:%Y-%m-%d} sort:stars'


def process(some_repositories, all_repositories):
    for repo in some_repositories:
        # Flattening fields
        for k, v in repo.items():
            while isinstance(v, dict):
                v = next(iter(v.values()))
            repo[k] = v

        all_repositories[repo['owner'] + '/' + repo['name']] = repo


def save(all_repositories):
    df = pd.DataFrame(all_repositories.values())
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
        'filter': query_filter(),
        'projectsPerPage': 10,  # from 1 to 100
        'cursor': None
    }

    request = {
        'query': open('query.graphql', 'r').read(),
        'variables': variables
    }

    # AIMD parameters for auto-tuning the page size
    ai = 2  # slow start: 2, 4, 8, 10 (max)
    md = 0.5

    all_repositories = dict()
    repository_count = -1
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
            if repository_count == -1:
                repository_count = result["data"]["search"]["repositoryCount"]

            some_repositories = result['data']['search']['nodes']
            process(some_repositories, all_repositories)
            print(f'Processed {len(all_repositories)} of {repository_count} projects.', end=' ')

            page_info = result['data']['search']['pageInfo']
            variables['cursor'] = page_info['endCursor']
            variables['projectsPerPage'] = min(100, variables['projectsPerPage'] + ai)  # using AIMD
            ai = min(10, ai * 2)  # slow start

            if not page_info['hasNextPage']:  # We may have finished all repositories or reached the 1,000 limit
                if len(all_repositories) == repository_count:  # We have finished all repositories
                    print(f'Finished.')
                    has_next_page = False
                else:  # We have reached the 1,000 limit
                    variables['filter'] = query_filter(max_stars=some_repositories[-1]['stargazers'])
                    variables['cursor'] = None

        time.sleep(1)  # Wait 1 second before next request (https://developer.github.com/v3/#abuse-rate-limits)

    save(all_repositories)


if __name__ == "__main__":
    main()
