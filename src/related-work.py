import xml.sax
import pandas as pd
from util import DBLP_FILE, VENUE_KEYS, PAPERS_FILE

# Global variables
stack = [] # this is a list that is used as a stack to store open element names
authors = ''
venue_keys = []
paper = {}
save_paper = False
df = pd.DataFrame()


class DBLPHandler(xml.sax.ContentHandler):

    def startElement(self, name, attrs):
        global stack, save_paper
        stack.append(name)
        if name == 'inproceedings' or name == 'article':
            for a in attrs.items():
                if a[0] == 'key':
                    for venue in venue_keys:
                        if venue in a[1]:
                            save_paper = True
                            paper['key'] = a[1]

    def characters(self, content):
        global paper, authors

        if save_paper:
            if len(stack) >= 2 and (stack[-2] == 'inproceedings' or stack[-2] == 'article'):
                if stack[-1] == 'crossref':
                    crossref = content
                    paper['crossref'] = crossref
                if stack[-1] == 'author':
                    authors = authors + content
                    paper['authors'] = authors
                if stack[-1] == 'year':
                    paper['year'] = content
                if stack[-1] == 'title':
                    paper['title'] = str(content)
                if stack[-1] == 'url':
                    paper['url'] = str(content)

    def endElement(self, name):
        global stack, authors, save_paper, df, paper
        stack.pop()
        if name == 'inproceedings' or name == 'article':
            if save_paper:
                df = df.append(paper, ignore_index=True)
            paper = {}
            authors = ''
            save_paper = False


# loads venue keys from file
file = open(VENUE_KEYS, 'r')
for line in file:
    venue_keys.append(line.rstrip())
parser = xml.sax.make_parser()
parser.setContentHandler(DBLPHandler())
print('Parsing DBLP...')
parser.parse(open(DBLP_FILE, 'r'))
print('Saving', len(df), 'papers to Excel file... ')
df.to_excel(PAPERS_FILE, index=False)