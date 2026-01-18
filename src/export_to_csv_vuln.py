import os
import pandas as pd
import database as db  # usa o seu módulo, que já configura engine/session
from util import VULNERABILITY_RESULTS, OUTPUT_CSV  # se você já tem um diretório padrão

SQL = """
SELECT
  vv.versionNumber,
  h.pattern,
  l.name,
  vv.file,
  vv.version_id,
  p.name as project_name,
  v.date_commit,
  v.sha1,
  v.project_id,
  vv.execution_id
FROM version_vulnerability AS vv
JOIN version   AS v ON vv.version_id = v.id
JOIN project AS p on v.project_id = p.id
JOIN execution AS e ON vv.execution_id = e.id
JOIN heuristic AS h ON e.heuristic_id = h.id
JOIN label AS l ON h.label_id = l.id
;
"""

def export_query_to_csv():
    db.connect()

    output_path = os.path.join(OUTPUT_CSV, VULNERABILITY_RESULTS)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    df = pd.read_sql_query(SQL, db.engine)
    df.to_csv(output_path, index=False)

    print(f"Arquivo salvo em {output_path}")


def main():
    export_query_to_csv()

if __name__ == "__main__":
    main()
