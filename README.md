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

We assume you have [Anaconda](https://www.anaconda.com/) installed on your computer. 

## Steps 

1. Clone our repository:  

`git clone https://github.com/gems-uff/db-mining.git`

2. Go into the project directory:

`cd db-mining`

3. Create a conda environment: 

`conda env create -f environment.yml`

4. Activate the conda environment: 

`conda activate db-mining` 

(on Windows this should be `source activate db-mining`)

5. You are now all set to run the scripts. 

# Acknowledgements

We would like to thank CNPq for funding this research.

# License

Copyright (c) 2019 Universidade Federal Fluminense (UFF), Northern Arizona University (NAU).

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
