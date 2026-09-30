import pandas as pd, numpy as np, os
from util import VULNERABILITY_RESULTS, VULNERABILITY_VERSIONS_POR_MODULO


df = pd.read_csv(VULNERABILITY_RESULTS)
df['date_commit'] = pd.to_datetime(df['date_commit'], errors='coerce')
df = df.dropna(subset=['date_commit']).copy()
for col in ['file','name','pattern','versionNumber','project_name','sha1']:
    if col in df.columns:
        df[col] = df[col].astype(str).str.strip()

def build_segments_for_group(sub: pd.DataFrame) -> pd.DataFrame:
    sub = sub.sort_values(['date_commit','sha1','version_id'])
    sub['prev_version'] = sub['versionNumber'].shift(1)
    sub['is_change'] = (sub['versionNumber'] != sub['prev_version']) | sub['prev_version'].isna()
    sub['segment_id'] = sub['is_change'].cumsum()
    seg = (sub.groupby('segment_id')
           .agg(file=('file','first'),
                db=('name','first'),
                pattern=('pattern','first'),
                project=('project_name','first'),
                project_id=('project_id','first'),
                start_date=('date_commit','min'),
                last_seen_date=('date_commit','max'),
                versionNumber=('versionNumber','first'),
                commits=('sha1','nunique'),
                rows=('version_id','count'))
           .reset_index(drop=True))
    seg['next_start_date'] = seg['start_date'].shift(-1)
    seg['end_date'] = seg['last_seen_date']
    mask = seg['next_start_date'].notna()
    candidate = seg.loc[mask, 'next_start_date'] - pd.Timedelta(days=1)
    seg.loc[mask, 'end_date'] = np.maximum(seg.loc[mask, 'last_seen_date'].values.astype('datetime64[ns]'),
                                           candidate.values.astype('datetime64[ns]'))
    seg['duration_days'] = (seg['end_date'] - seg['start_date']).dt.days + 1
    seg = seg.drop(columns=['next_start_date'])
    return seg

# gera tabela para todos os módulos (e DBs) do csv
segments_all = []
summary_all = []
for (file_val, db_val), sub in df.groupby(['file','name'], sort=False):
    seg = build_segments_for_group(sub)
    segments_all.append(seg)
    summary_all.append({
        'file': file_val,
        'db': db_val,
        'distinct_versions': sub['versionNumber'].nunique(),
        'first_commit': sub['date_commit'].min().date(),
        'last_commit': sub['date_commit'].max().date(),
        'total_commits_observed': sub['sha1'].nunique(),
        'total_rows': len(sub),
    })
segments_all = pd.concat(segments_all, ignore_index=True)
summary_all = pd.DataFrame(summary_all).sort_values(['db','file'])

with pd.ExcelWriter(VULNERABILITY_VERSIONS_POR_MODULO, engine="openpyxl") as writer:
    summary_all.to_excel(writer, index=False, sheet_name="Resumo")
    segments_all.to_excel(writer, index=False, sheet_name="VersoesPorModulo")

VULNERABILITY_VERSIONS_POR_MODULO, summary_all.head(), segments_all.head()