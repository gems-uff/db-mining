import pandas as pd
from sqlalchemy.orm import defer

import database as db
from util import AGREEMENT_FILE

#reads Excel file
df = pd.read_excel(AGREEMENT_FILE, sheet_name='Round1', use_cols=[0,1,2,3], keep_default_na=False)

db.connect()
for i, row in df.iterrows():
    if row["A"] == row["B"]:
        execution_id = row['EXECUTION_ID']
        print(f'Saving execution {execution_id}.')
        execution = db.query(db.Execution).options(defer('output')).filter(db.Execution.id == execution_id).first()
        # execution.isValidated = True
        # execution.isAccepted = row['A']
        # execution.user = 'Leonardo & Vanessa'
        print(execution)
# db.commit()



