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

# Scripts description

Pending. We will add a table here soon.

# Acknowledgements

We would like to thank CNPq for funding this research.

# License

Copyright (c) 2019 Universidade Federal Fluminense (UFF), Northern Arizona University (NAU).

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
