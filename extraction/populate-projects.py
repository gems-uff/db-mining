import utils.database as db
import pandas as pd

# File to load the data with repositories
REPO_FILE = '../resources/annotated.xlsx'

def main():
    # create a database connection
    db.connect()

    print(f'Loading repositories from {REPO_FILE}...')
    df = pd.read_excel(REPO_FILE, keep_default_na=False)
    # removing discarded repositories
    df = df[df.discardReason == '']
    total = len(df)
    print(f'Processing {total} projects...')

    for i, row in df.iterrows():
        project_id = db.insert_project(row)

    print('\nRemoving projects that in the database and not in the Excel file...')
    db.remove_old_projects()

    print('Commiting changes...')
    db.commit()
    print('Closing database connection...')
    db.close()

if __name__ == '__main__':
    main()
