import scholarly
import pandas as pd
import time
from util import FILTERED_PAPERS_FILE

# reads papers from Excel file
df = pd.read_excel(FILTERED_PAPERS_FILE, keep_default_na=False)
new_df = pd.DataFrame()

print('Processing', len(df), 'papers...')

i = 0
for index, row in df.iterrows():
    paper = row.to_dict()
    print('Getting citation # of paper: ')
    year = '(' + str(paper['year']) + ')'
    print('   ', paper['title'], year)
    search_query = scholarly.search_pubs_query(paper['title'])
    pub = next(search_query)
    row['bib-scholar'] = pub.bib
    row['citations'] = pub.citedby
    print('    ==>', row['citations'], 'citations')
    new_df.append(row)
    i += 1
    # Stops once and a while so Google Scholar does not complain
    if (i % 4) == 0:
        time.sleep(10)

print(new_df)
df.to_excel(FILTERED_PAPERS_FILE, index=False)
