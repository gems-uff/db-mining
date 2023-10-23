# About

This is the companion website for the research "On the usage of Databases in Open Source Projects". This research has so far been divided into two main analyses: current and historical. In the **Current Analysis** we investigate the use of DBMS in the current situation in which the projects find themselves. In the **Historical Analysis**, we investigated the adoption of DBMS throughout the projects life cycle.

# Team

Vanessa Braganholo (UFF, Brazil)  
Leonardo Gresta Paulino Murta (UFF, Brazil)  
Igor Wiese (UTFPR, Brazil)  
Igor Steinmacher (NAU, USA)  
Marco Aurélio Gerosa (NAU, USA)  
Camila Acácio de Paiva (UFF, Brazil)
Raquel Maximino de Barros Santos (UFF, Brazil)
Frederico Gomes de Paiva (UFF, Brazil)
João Felipe Pimentel (UFF, Brazil)

# Project Corpus
- In summary, the table below shows the workflow to the selection of projects for our corpus. We have the name of the script, your purpose, the required entry and the output produced.

| Name          | Goal                                                | Input          | Output        |
| ------------- | --------------------------------------------------- | -------------- | ------------- | 
| collect.py    | Queries projects' metadata from GitHub using API v4 | None           | projects.xlsx |
| filter.ipynb  | Applies some extra filters                          | projects.xlsx  | filtered.xlsx |
| analyze.ipynb | Produces statistics about the final corpus          | annotated_java.xlsx | None          |
| download.py   | Clones all repositories in the corpus               | annotated_java.xlsx | None          |
| reset.py      | Tries to fix name colisions for case-insensitive FS | annotated_java.xlsx | None          |

# Heuristics Extraction
- The table below shows the workflow for searching established heuristics. We have the name of the script, your purpose, the required entry and the output produced.
  
| Name          | Goal                                                | Input          | Output        |
| ------------- | --------------------------------------------------- | -------------- | ------------- |
| extract.py    | Runs git grep and populates the database            | annotated_java.xlsx | None       |
| extract_historical.py    | Runs git grep on ten slices of projects history and populates the database | annotated_java.xlsx | None         |
| create_file_dbCode.py    | Generates .txt files that contains dbCode Heuristics            | DataBase (Implementation Heuristics) | Path .first-level |
| extract_classes.py    | Runs git grep and populates the database with dependencies of dbCode            | Path .first-level | None          |
| create_vulnerabilityDatabase.py    | Produces database about vulnerabilities            | Vulnerability_Version_20061101_Date_20220913.xlsx | None        |
| extract_historical_vulnerabilities.py    | Runs git grep and populates the database with historial of vulnerabilities            | DataBase | None        |

# Results Analysis

## Current Analysis
- The table below shows the workflow for currently analyzing the results.

| Name          | Goal                                                | Input          | Output        |
| ------------- | --------------------------------------------------- | -------------- | ------------- |
| results_dbCode_dependencies.py    | Count the results of bdCode and its dependencies to the project          | DataBase (Second Level) | Path .second-level and usage_fan_in_file.xlsx          |
| results_in_xlsx.py    | Generates the xlsx that it will use to analyze the results           | DataBase | count_implementation.xlsx, count_sql.xlsx, database.xlsx, implementation.xlsx, implementation_names.xlsx, query.xlsx          |
| results_database_characterization.ipynb    | Produces statistics about database Heuristics            | database.xlsx | None          |
| results_implementation_characterization.ipynb   | Produces statistics about implementation Heuristics            | database.xlsx, implementation.xlsx, implementation_names.xlsx, query.xlsx | None          |
  
## Historical Analysis
- The table below shows the workflow for historical analysis of the results. This analysis only requires the execution of the **Heuristics Extraction script** extract_historical.py".

| Name          | Goal                                                | Input          | Output        |
| ------------- | --------------------------------------------------- | -------------- | ------------- |
| historical_implementation.py | Generates a coded dataset with the results of the history of the projects | DataBase | historical.xlsx |
| historical_analysis.ipynb | Produces statistics about DBMS adopted throughout the history of projects | historical.xlsx | historical_join.xlsx  |
| historical_count_models.ipynb | Produces statistics and dataset about DBMS models | historical_join.xlsx, databases_models.xlsx | historical_join_db.xlsx |
| historical_graphs.ipynb | Produces graphs with statistics about DBMS models and project domains |historical_join_db.xlsx | None |
| historical_coocurrence_version1.ipynb | Generates association rules for the results found in the projects history first slice. |historical_join.xlsx | historical_rulesv1.xlsx |
| historical_coocurrence_version5.ipynb | Generates association rules for the results found in the projects history fifth slice. |historical_join.xlsx | historical_rulesv5.xlsx |
| historical_coocurrence_version10.ipynb | Generates association rules for the results found in the projects history last slice. |historical_join.xlsx | historical_rulesv10.xlsx |
| historical_coocurrence_filters_v1.ipynb | Apply filters to analyze the correlations found in the first version |historical_rulesv1.xlsx | None |
| historical_coocurrence_filters_v5.ipynb | Apply filters to analyze the correlations found in the fifth version |historical_rulesv5.xlsx | None |
| historical_coocurrence_filters_v10.ipynb | Apply filters to analyze the correlations found in the last version |historical_rulesv10.xlsx| None |
| historical_seqpatterns_format.ipynb | Converts the historical_join dataset to the file format required by the SPMF library |historical_join.xlsx| input_sequencial_init_in_out.txt, output_tam1.txt, output_tam3.txt, output_tam4_sid.txt  |
| historical_seqpatterns_filters.ipynb | Apply filters to search for established replacement patterns and generates some data mining measures | output_tam1.txt, output_tam3.txt, output_tam4_sid.txt | pattern_selection_measures.xlsx |

## Related Work 

| Name          | Goal                                                | Input          | Output        |
| ------------- | --------------------------------------------------- | -------------- | ------------- | 
| related-work.py    | Traverses the DBLP XML file using the SAX API to get papers from major Database and Software Engineering conferences and journals | venue_keys.txt           | papers.xlsx |
| related-work.ipynb  | Filters for papers with "database" on the title and that were published in Software Engineering venues                         | papers.xlsx  | filtered_papers.xlsx |

- [Excel Spreadsheet](https://github.com/gems-uff/db-mining/raw/master/resources/annotated.xlsx)  (validate that all fields in the spreadsheet are filled in correctly, the convert of formulas may cause an error.)
- [Collection Scripts](https://github.com/gems-uff/db-mining/tree/master/src) (see the installation instructions bellow to run the scripts in your computer)

# Installation

## Requirements

We assume you have Python 3.7+, Node 12.10+ and Git 2.23+ installed on your computer. 
OBS: At the moment, sqlalchemy-utils has a incompatibility with sqlalchemy 1.4.0b1. Change to an older version, for example sqlalchemy 1.3.23.

## Steps for setting up the environment (needs to be done just once) 

### Configuring project base

1. Clone our repository: 

`~$ git clone https://github.com/gems-uff/db-mining.git`

2. Go into the project directory:

`~$ cd db-mining`

3. Install pipenv (if it is not already installed):

`~/db-mining$ python -m pip install pipenv`

4. Prepare the Python environment: 

`~/db-mining$ pipenv install`

5. Go into the React app directory:

`~/db-mining$ cd web`

6. Prepare the React app environment:

`~/db-mining/web$ npm install`


### Configuring Okta authentication
This project uses Okta as the authentication mechanism. Follow the steps below to set up your credentials.

1. Access https://www.okta.com/ and create an account (if you do not already have one).

2. Access your panel and create a new application with the following settings:

| Parameter | Value |
| --------- | ----- |
| Platform | Single-Page App |
| Base URIs | http://127.0.0.1:5000/ |
| Login redirect URIs | http://localhost:3000/implicit/callback<br/>http://localhost:5000/implicit/callback<br/> http://127.0.0.1:5000/implicit/callback |
| Logout redirect URIs | http://localhost:5000/login <br/>http://localhost:3000/login <br/>http://127.0.0.1:5000/login |
| Implicit checkbox | Marked |

3. Go to the file `authentication.json` and update the variables `issuer` and `client_id` to match your credentials.


### Configuring database access
You can use either SQLite or PostgreSQL database.

1. Go to the file `database.json`.

2. Edit it according to the database you will use:

This JSON file has a drop_database field which indicates whether you would like the application to drop the existing database and create a new empty one. If that is the case, the value of drop_database should be True. The database_type field specifies which database management system will be used: SQLite or PostgreSQL. The remaining fields depend on the type of database you are using. 

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

Now, if you just want to run the project using the analysis we made with the databases and the projects we selected, follow the steps below.
But, if you want to run the project to create your own analysis, go to [Steps for creating your own analysis](#own-analysis).

## Steps for running the application

### Running the scripts

1. Go into the project directory:

`~$ cd db-mining`

2. Activate the environment: 

`~/db-mining$ pipenv shell`

3. Run the `download.py` script to clone all the repositories in the corpus:

`~/db-mining$ python src/download.py`

4. Run the `reset.py` to fix name colisions for case-insensitive file systems:

`~/db-mining$ python src/reset.py`

5. Run the `extract.py` to execute the **Current Analysis** or `extract_historical.py` to execute the **Historical Analysis** and populate the database:

`~/db-mining$ python src/extract.py`

### Starting the application

1. Go into the React app directory:

`~/db-mining$ cd web`

2. Build the application:

`~/db-mining/web$ npm run build`

3. Back to the root directory:

`~/db-mining$ cd ..`

4. Run the `server.py` to start the Flask server:

`~/db-mining$ python src/server.py`

5. Access the React app at http://127.0.0.1:5000

In this case, the URL http://127.0.0.1:5000 is served by Flask and uses the last build of the React app produced by `npm run build`. 
Alternatively, you can run the application with Node.js server if you want to immediately reflect your changes into the React app without the need of rebuilding it every time during development.
If so, follow the remaining steps.

6. Add http://localhost:3000 as a trusted origin with CORS enabled in the Okta panel, API > Trusted origin.

7. Go into the React app directory:

`~/db-mining$ cd web`

8. Start the Node.js server:

`~/db-mining/web$ npm start`

9. Access the React app at http://localhost:3000.


The URL http://localhost:3000 is served by Node.js and has hot reload capability. Please, note that it is significantly slower than rebuilding the React app (i.e., `npm run build`) and serving using Flask (http://127.0.0.1:5000). As our architecture is based on a REST API, even when accessing unsing Node.js, the Flask server should be online (Step 9), to respond REST requests.

## <a name="own-analysis"></a>Steps for creating your own analysis

### Steps for Current Analysis
*Soon...*

### Steps for Historical Analysis

1. Go into the project directory:

`~$ cd db-mining`

2. Run the `historical_implementation.py` to generate a one-hot coded dataset with the results of the projects history:
   
`~/db-mining$ python src/historical_implementation.py`

3. Execute the next scripts in Google Colab or Jupyter Notebook platforms. 
   
4. Run the `historical_analysis.ipynb` to produce statistics about DBMS adopted throughout the history of projects.

5. Run the `historical_count_models.ipynb` to produce statistics and dataset about DBMS models.

6. Run the `historical_count_models.ipynb` to produce graphs with statistics about DBMS models and project domains.

7. Run the `historical_coocurrence_version1.ipynb`, `historical_coocurrence_version5.ipynb`, and `historical_coocurrence_version1o.ipynb` to generate association rules for the first, fifth and last slices of project history.

8. Run the `historical_coocurrence_filters_v1.ipynb`, `historical_coocurrence_filters_v5.ipynb`, and `historical_coocurrence_filters_v1o.ipynb` to apply filters to analyze the correlations found in the three moments of the projects' history.

9. Run the `historical_seqpatterns_format.ipynb` to generate the standard input file for the SPMF library.

10. Run the `historical_seqpatterns_filters.ipynb` to filter the replacement patterns and generate the measures.


# Spreadsheets description

There are two sets of spreadsheets. The first one is related to the selection of projects for our corpus. The second one is related to our search for related work. They are described below, and can be found in the `resources` folder.

## Project Corpus

| Name | Content | # of projects |
| ---- | ------- | ------------- |
| projects.xlsx | All public, non-fork, and active (with pushes in the last 3 months) projects with ≥1000 stars from GitHub on March 27, 2021 | 21,149 |
| filtered.xlsx | All projects from projects.xlsx with ≥1000 stars, ≥1000 commits, ≥10 contributors, and Java programming languages | 633 |
| annotated_java.xlsx | All Java projects from filtered.xlsx with manual annotations classifying the domain of the projects and discarding inadequate projects | 317 |

## Related Work

We searched the DBLP XML file for papers that have "database" on the title, and that were published in major Software Engineering conferences and journals. The DBLP XML file was downloaded on Setember 16th, 2019. We then conducted a snowballing. The spreadsheets below are the result of this search. 

| Name | Content | # of papers |
| ---- | ------- | ------------- |
| papers.xlsx | All papers published in major Database and Software Engineering conferences and journals. The list of venues is specified in the `venue_keys.txt` file | 40,730 |
| filtered_papers.xlsx | All papers from the `papers.xlsx` file that have "database" in the title, filtered by Software Engineering venues and| 260 |  


# Acknowledgements

We would like to thank CNPq for funding this research.

# License

Copyright (c) 2019 Universidade Federal Fluminense (UFF), Northern Arizona University (NAU).

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
