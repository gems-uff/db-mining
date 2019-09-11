import pandas as pd

import database as db
from util import ANNOTATED_FILE


def main():
    # creating a database connection
    db.connect()

    print(f'Loading repositories from {ANNOTATED_FILE}...')
    df = pd.read_excel(ANNOTATED_FILE, keep_default_na=False)
    # removing discarded repositories
    df = df[df.discardReason == '']
    total = len(df)
    print(f'Processing {total} projects...')

    # for i, row in df.iterrows():
    #     db.insert_project(row)
    # TODO: Use SQL Alchemy

    print('\nRemoving projects that in the database and not in the Excel file...')
    # db.remove_old_projects()
    # TODO: migrate the function to here.

    print('Closing database connection...')
    db.close()


if __name__ == '__main__':
    main()
