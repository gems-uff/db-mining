import pandas as pd
import numpy as np
import os

# =========================
# 1. Leitura dos dados
# =========================

csv_path = (
    "/Users/camilapaiva/Documents/GitHub/db-mining/"
    "resources/vulnerabilities/"
    "_SELECT_vv_versionNumber_h_pattern_l_name_vv_file_vv_version_id__202601121903.csv"
)

df = pd.read_csv(csv_path)

df["date_commit"] = pd.to_datetime(df["date_commit"], errors="coerce")
df = df.dropna(subset=["date_commit"]).copy()

# Normalizações defensivas
for col in ["name", "versionNumber", "sha1", "name.1", "project_id"]:
    if col in df.columns:
        df[col] = df[col].astype(str).str.strip()

# Renomes para clareza semântica
df = df.rename(columns={
    "name": "db",
    "name.1": "project_name",
})

# =========================
# 2. Segmentação temporal
# =========================

def build_segments_for_project(sub: pd.DataFrame) -> pd.DataFrame:
    sub = sub.sort_values(["date_commit", "sha1", "version_id"])

    sub["prev_version"] = sub["versionNumber"].shift(1)
    sub["is_change"] = (
        (sub["versionNumber"] != sub["prev_version"]) |
        sub["prev_version"].isna()
    )
    sub["segment_id"] = sub["is_change"].cumsum()

    seg = (
        sub.groupby("segment_id")
           .agg(
               project_id=("project_id", "first"),
               project_name=("project_name", "first"),
               db=("db", "first"),
               versionNumber=("versionNumber", "first"),
               start_date=("date_commit", "min"),
               last_seen_date=("date_commit", "max"),
               commits=("sha1", "nunique"),
               rows=("version_id", "count"),
           )
           .reset_index(drop=True)
    )

    # Cálculo do end_date
    seg["next_start_date"] = seg["start_date"].shift(-1)
    seg["end_date"] = seg["last_seen_date"]

    mask = seg["next_start_date"].notna()
    candidate = seg.loc[mask, "next_start_date"] - pd.Timedelta(days=1)

    seg.loc[mask, "end_date"] = np.maximum(
        seg.loc[mask, "last_seen_date"].values.astype("datetime64[ns]"),
        candidate.values.astype("datetime64[ns]")
    )

    seg["duration_days"] = (seg["end_date"] - seg["start_date"]).dt.days + 1

    return seg.drop(columns=["next_start_date"])


segments = []
for (project_id, db), sub in df.groupby(["project_id", "db"], sort=False):
    segments.append(build_segments_for_project(sub))

segments = pd.concat(segments, ignore_index=True)

# =========================
# 3. História única do projeto
# =========================

history = (
    segments
    .groupby(
        ["project_id", "project_name", "db", "versionNumber"],
        as_index=False
    )
    .agg(
        first_start_date=("start_date", "min"),
        last_end_date=("end_date", "max"),
        total_duration_days=("duration_days", "sum"),
        times_entered=("versionNumber", "count"),
        total_commits=("commits", "sum"),
    )
    .sort_values(["project_id", "db", "first_start_date"])
)

# =========================
# 4. Cálculo correto de saídas
# =========================

last_version = (
    segments
    .sort_values(["project_id", "db", "start_date"])
    .groupby(["project_id", "db"], as_index=False)
    .tail(1)[["project_id", "db", "versionNumber"]]
    .rename(columns={"versionNumber": "last_version"})
)

history = history.merge(
    last_version,
    on=["project_id", "db"],
    how="left"
)

history["times_exited"] = history["times_entered"]
mask_last = history["versionNumber"] == history["last_version"]
history.loc[mask_last, "times_exited"] = (
    history.loc[mask_last, "times_entered"] - 1
)
history["times_exited"] = history["times_exited"].clip(lower=0)

history = history.drop(columns=["last_version"])

# =========================
# 5. Geração do arquivo
# =========================

out_path = ("/Users/camilapaiva/Documents/GitHub/db-mining/resources/vulnerabilities/historia_projeto_bd.xlsx")

with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
    history.to_excel(
        writer,
        index=False,
        sheet_name="HistoriaProjeto"
    )
    segments.to_excel(
        writer,
        index=False,
        sheet_name="SegmentosProjeto"
    )

print(f"Arquivo gerado com sucesso em: {out_path}")
