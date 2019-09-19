import xml.sax
from xml.sax import saxutils
import pandas as pd
import html.entities
from util import DBLP_FILE, VENUE_KEYS, PAPERS_FILE

# Global variables
stack = [] # this is a list that is used as a stack to store open element names
authors = ''
title = ''
venue_keys = []
paper = {}
save_paper = False
df = pd.DataFrame()
#ent = {'&#8482;': 'TM', "&apos;": "'", "&quot;": '"'}
ent = html.entities.entitydefs

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
        global paper, authors, title

        if save_paper:
            if len(stack) >= 2 and (stack[-2] == 'inproceedings' or stack[-2] == 'article'):
                content = saxutils.unescape(content, entities=ent)

                if stack[-1] == 'crossref':
                    paper['crossref'] = content
                if stack[-1] == 'author':
                    authors = authors + content
                    paper['authors'] = authors
                if stack[-1] == 'year':
                    paper['year'] = content
                if stack[-1] == 'title':
                    title = title + content
                    paper['title'] = title
                if len(stack) >= 2 and stack[-2] == 'title':
                    #deal with cases like <title>Abc<i>def</i>ghd</title>
                    title = title + content
                    paper['title'] = title
                if stack[-1] == 'url':
                    paper['url'] = content

    def endElement(self, name):
        global stack, authors, save_paper, df, paper, title
        stack.pop()
        if name == 'inproceedings' or name == 'article':
            if save_paper:
                df = df.append(paper, ignore_index=True)
            paper = {}
            authors = ''
            title = ''
            save_paper = False


# process entity dictionary to include &;
tmp = ent.copy()
for e in tmp:
    ent['&' + e + ';'] = ent.pop(e) #creates a new entry in the dictionary and removes the old entry

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