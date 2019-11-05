# About

This is the companion website for the paper "On the usage of Databases in Open Source Projects".

# Team

Vanessa Braganholo (UFF, Brazil)  
Leonardo Gresta Paulino Murta (UFF, Brazil)  
Igor Wiese (UTFPR, Brazil)  
Igor Steinmacher (NAU, USA)  
Marco Aurélio Gerosa (NAU, USA)  

# Project Corpus

- [Excel Spreadsheet](https://github.com/gems-uff/db-mining/raw/master/resources/annotated.xlsx)  
- [Collection Scripts](https://github.com/gems-uff/db-mining/tree/master/src) (see the installation instructions bellow to run the scripts in your computer)

# Installation

## Requirements

We assume you have Python 3.7+, Node 12.10+ and Git 2.23+ installed on your computer. 

## Steps for setting up the environment (needs to do just once) 

1. Clone our repository:  

`~$ git clone https://github.com/gems-uff/db-mining.git`

2. Go into the project directory:

`~$ cd db-mining`

3. Install pipenv (if it is not already installed)

`~/db-mining$ python3.7 -m pip install pipenv`

4. Prepare the Python environment: 

`~/db-mining$ pipenv install`

5. Go into the React app directory

`~/db-mining$ cd web`

6. Prepare the React app environment:

`~/db-mining/web$ npm install`

7. Build the React app:

`~/db-mining/web$ npm run build`

8. Configure database access. You can you either SQLite or PostgreSQL database. Go into the resources directory: 

`~$ cd resources`

9. Edit the database.json file. This JSON file has a drop_database field which indicates whether you would like the application to drop the existing database and create a new empty one. If that is the case, the value of drop_database should be True. The database_type field specifies which database management system will be used: SQLite or PostgreSQL. The remaining fields depend on the type of database you are using. 

If you are using SQLite, these are the mandatory fields of the JSON file: 

```
{
  "drop_database": "False",
  "database_type": "sqlite",
  "database_name": "dbmining.sqlite"
}
```
If you are using PostgreSQL, these are the mandatory fields:

```
{
  "drop_database": "False",
  "database_type": "postgresql",
  "host": "none",
  "port": "none",
  "username": "none",
  "password": "none",
  "database_name": "dbmining"
}
```

## Steps for running the Python and Jupyter scripts 

1. Go into the project directory:

`~$ cd db-mining`

2. Activate the environment: 

`~/db-mining$ pipenv shell`

3. You are now all set to run the scripts in src directory (check the [scripts description](#script-description) before running). For example:

`~/db-mining$ python3.7 src/extract.py`

or

`~/db-mining$ jupyter notebook src/analyze.ipynb`

## Steps for running the React app

1. Go into the project directory:

`~$ cd db-mining`

2. Activate the environment: 

`~/db-mining$ pipenv shell`

3. Start the Flask server:

`~/db-mining$ python3.7 src/server.py`

4. Access the React app at http://localhost:5000.

The URL http://localhost:5000 is served by Flask and uses the last build of the React app produced by `npm run build`. If you want to immediately reflect your changes into the React app without the need of rebuilding it every time during development, please follow the remaining steps.

5. Go into the React app directory

`~/db-mining$ cd web`

6. Start the Node.js server:

`~/db-mining/web$ npm start`

7. Access the React app at http://localhost:3000.

The URL http://localhost:3000 is served by Node.js and has hot reload capability. Please, note that it is significantly slower than rebuilding the React app (i.e., `npm run build`) and serving using Flask (http://localhost:5000). As our architecture is based on a REST API, even when accessing unsing Node.js, the Flask server should be online, to respond REST requests.

8. Update the variables `issuer` and `client_id` in the file `index.js` to match your [Okta](https://developer.okta.com) credentials, if you are intend to manage your own users. 

# Spreadsheets description

There are two sets of spreadsheets. The first one is related to the selection of projects for our corpus. The second one is related to our search for related work. They are described below, and can be found in the `resources` folder.

## Project Corpus

| Name | Content | # of projects |
| ---- | ------- | ------------- |
| projects.xlsx | All public, non-fork, and active (with pushes in the last 3 months) projects with ≥1000 stars from GitHub on August 23, 2019 | 13,393 |
| filtered.xlsx | All projects from projects.xlsx with ≥5000 stars, ≥5000 commits, ≥10 contributors, and top-10 programming languages | 389 |
| annotated.xlsx | All projects from filtered.xlsx with manual annotations classifying the domain of the projects and discarding inadequate projects | 178 |

## Related Work

We searched the DBLP XML file for papers that have "database" on the title, and that were published in major Software Engineering conferences and journals. The DBLP XML file was downloaded on Setember 16th, 2019. We then conducted a snowballing. The spreadsheets below are the result of this search. 

| Name | Content | # of papers |
| ---- | ------- | ------------- |
| papers.xlsx | All papers published in major Database and Software Engineering conferences and journals. The list of venues is specified in the `venue_keys.txt` file | 40,730 |
| filtered_papers.xlsx | All papers from the `papers.xlsx` file that have "database" in the title, filtered by Software Engineering venues and| 260 |  


# Scripts description

As with the spreadsheets, we also have two sets of scripts: one for the corpus and another for searching for related work. 

## Project Corpus 

| Name          | Goal                                                | Input          | Output        |
| ------------- | --------------------------------------------------- | -------------- | ------------- | 
| collect.py    | Queries projects' metadata from GitHub using API v4 | None           | projects.xlsx |
| filter.ipynb  | Applies some extra filters                          | projects.xlsx  | filtered.xlsx |
| analyze.ipynb | Produces statistics about the final corpus          | annotated.xlsx | None          |
| download.py   | Clones all repositories in the corpus               | annotated.xlsx | None          |
| reset.py      | Try to fix name colisions for case-insensitive FS   | annotated.xlsx | None          |

## Related Work 

| Name          | Goal                                                | Input          | Output        |
| ------------- | --------------------------------------------------- | -------------- | ------------- | 
| related-work.py    | Traverses the DBLP XML file using the SAX API to get papers from major Database and Software Engineering conferences and journals | venue_keys.txt           | papers.xlsx |
| related-work.ipynb  | Filters for papers with "database" on the title and that were published in Software Engineering venues                         | papers.xlsx  | filtered_papers.xlsx |

# Acknowledgements

We would like to thank CNPq for funding this research.

# License

Copyright (c) 2019 Universidade Federal Fluminense (UFF), Northern Arizona University (NAU).

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
