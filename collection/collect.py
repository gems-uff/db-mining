import errno
import time

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

    variables = {
        "projectsPerPage": 100,  # from 1 to 100
        "cursor": None
    }

    request = {
        'query': open('query.graphql', 'r').read(),
        'variables': variables
    }

    processed_projects = 0
    has_next_page = True
    while has_next_page:
        print(f'Trying to retrieve the next {variables["projectsPerPage"]} projects...')
        response = requests.post(url="https://api.github.com/graphql", json=request, headers=headers)
        result = response.json()

        # print(result)
        # print(response.headers)

        if 'message' in result:  # reached retry limit
            print(f'Waiting for {response.headers["Retry-After"]} seconds before continuing...', end=' ')
            time.sleep(int(response.headers['Retry-After']))

        if 'errors' in result:  # reached timeout
            print(f'Timeout!', end=' ')
            if variables['cursor']:  # We have already retrieved some projects in the past
                variables['projectsPerPage'] = max(1, variables['projectsPerPage'] - 1)
            else:  # We have always received timeout
                variables['projectsPerPage'] = int(max(1, variables['projectsPerPage'] / 2))

        if 'data' in result and result['data']:
            # process(result)
            processed_projects += len(result['data']['search']['nodes'])
            print(f'Processed {processed_projects} of {result["data"]["search"]["repositoryCount"]} projects.', end=' ')

            page_info = result['data']['search']['pageInfo']
            if page_info['hasNextPage']:  # We still have pending projects
                variables['cursor'] = page_info['endCursor']
                variables['projectsPerPage'] = min(100, variables['projectsPerPage'] + 1)
            else:  # We finished processing all projects
                print(f'Finished.')
                has_next_page = False

if __name__ == "__main__":
    main()
