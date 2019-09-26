import xml.sax
from xml.sax import saxutils
import pandas as pd
import html.entities
import html
from util import DBLP_FILE, VENUE_KEYS, PAPERS_FILE

# Global variables
stack = []  # this is a list that is used as a stack to store open element names
authors = ''
title = ''
previous_author_entity = False
venue_keys = {}
paper = {}
save_paper = False
df = pd.DataFrame()
ent = html.entities.entitydefs


class DBLPHandler(xml.sax.ContentHandler):

    def startElement(self, name, attrs):
        global stack, save_paper, paper, cont
        stack.append(name)
        if name == 'inproceedings' or name == 'article':
            for a in attrs.items():
                if a[0] == 'key':
                    for venue in venue_keys.keys():
                        if venue in a[1]:
                            save_paper = True
                            paper['key'] = a[1]
                            paper['venue'] = venue

    def characters(self, content):
        global paper, authors, title, previous_author_entity

        if save_paper:
            if len(stack) >= 2 and (stack[-2] == 'inproceedings' or stack[-2] == 'article'):
                content = saxutils.unescape(content, entities=ent)
                content = html.unescape(content)
                if stack[-1] == 'crossref':
                    paper['crossref'] = content
                if stack[-1] == 'author':
                    if authors == '' or previous_author_entity:
                        authors = authors + content
                    else:
                        authors = authors + ' and ' + content
                    paper['authors'] = authors
                    previous_author_entity = False
                if stack[-1] == 'year':
                    paper['year'] = content
                if stack[-1] == 'title':
                    title = title + content
                    paper['title'] = title
                if stack[-1] == 'url':
                    paper['url'] = content
            if len(stack) >= 3 and (stack[-3] == 'inproceedings' or stack[-3] == 'article'):
                content = saxutils.unescape(content, entities=ent)
                if len(stack) >= 2 and stack[-2] == 'title':
                    # deals with cases like <title>Abc<i>def</i>ghd</title>
                    title = title + content
                    paper['title'] = title
                if len(stack) >= 2 and stack[-2] == 'author':
                    authors = authors + content
                    paper['authors'] = authors

    def endElement(self, name):
        global stack, authors, save_paper, df, paper, title
        stack.pop()
        if name == 'inproceedings' or name == 'article':
            if save_paper:
                authors = paper.get('authors', ' ') # for some entries in DBLP, there are no authors -- this code avoids key errors
                author_key = authors.split(' ')
                if len(author_key) >= 2:
                    author_key = author_key[1]
                else:
                    author_key = author_key[0]
                if paper['title'][-1] == '.':
                    paper['title'] = paper['title'][0:-1]
                # construct bibtex
                if name == 'inproceedings':
                    paper['bibtex'] = '@inproceedings{' + author_key.lower() + ':' + paper['year'] + ',\n' + 'booktitle = {' + venue_keys.get(paper['venue']) + '}, \n'
                else:
                    paper['bibtex'] = '@article{' + author_key.lower() + ':' + paper['year'] + ',\n' + 'journal = {' + venue_keys.get(paper['venue']) + '}, \n'
                paper['bibtex'] = paper['bibtex'] + 'author = {' + authors + '}, \n' + 'title = {{' + paper['title'] + '}}, \n' + 'year = {' + paper['year'] + '} \n}'

                df = df.append(paper, ignore_index=True)
            paper = {}
            authors = ''
            title = ''
            save_paper = False
            previous_author_entity = False

    def skippedEntity(self, name):
        global paper, authors, title, previous_author_entity
        if stack[-1] == 'title' or stack[-1] == 'author':
            key = '&' + name + ';'
            content = ent[key]
            if stack[-1] == 'title':
                title = title + content
                paper['title'] = title
            else:
                if authors != '':
                    authors = authors + content
                else:
                    authors = content
                paper['authors'] = authors
                previous_author_entity = True


# process entity dictionary to include &;
tmp = ent.copy()
for e in tmp:
    ent['&' + e + ';'] = ent.pop(e)  # creates a new entry in the dictionary and removes the old entry

# loads venue keys from file
file = open(VENUE_KEYS, 'r')
for line in file:
    line = line.rstrip()
    key = line.split('  ')[0]
    name = line.split('  ')[1]
    venue_keys[key] = name

parser = xml.sax.make_parser()
parser.setContentHandler(DBLPHandler())
print('Parsing DBLP...')
parser.parse(open(DBLP_FILE, 'r'))

print('Saving', len(df), 'papers to Excel file... ')
df.to_excel(PAPERS_FILE, index=False)
