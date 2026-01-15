import pandas as pd
from itertools import combinations

# Load data
path = "/Users/camilapaiva/Documents/GitHub/db-mining/resources/vulnerabilities/_SELECT_vv_versionNumber_h_pattern_l_name_vv_file_vv_version_id__202601121903.csv"
df = pd.read_csv(path)

# Normalize columns
df["date_commit"] = pd.to_datetime(df["date_commit"], errors="coerce")
df = df.dropna(subset=["date_commit"])

df["file"] = df["file"].astype(str).str.strip()
df["versionNumber"] = df["versionNumber"].astype(str).str.strip()
df["pattern"] = df["pattern"].astype(str).str.strip()
df["project"] = df["name.1"].astype(str).str.strip()

# Build intervals per project, pattern, module, version
intervals = (
    df.groupby(["project_id", "project", "pattern", "file", "versionNumber"])
      .agg(
          start_date=("date_commit", "min"),
          end_date=("date_commit", "max")
      )
      .reset_index()
)

rows = []

# Detect concurrent versions
for (project_id, pattern), g in intervals.groupby(["project_id", "pattern"]):
    versions = g.to_dict("records")
    for v1, v2 in combinations(versions, 2):
        latest_start = max(v1["start_date"], v2["start_date"])
        earliest_end = min(v1["end_date"], v2["end_date"])
        if latest_start <= earliest_end:
            rows.append({
                "project_id": project_id,
                "project": v1["project"],
                "pattern": pattern,
                "version_a": v1["versionNumber"],
                "module_a": v1["file"],
                "version_b": v2["versionNumber"],
                "module_b": v2["file"],
                "overlap_start": latest_start.date(),
                "overlap_end": earliest_end.date(),
                "overlap_days": (earliest_end - latest_start).days + 1
            })

overlap_df = pd.DataFrame(rows).sort_values(
    ["project", "pattern", "overlap_start"]
)

# Export to Excel
out_path="/Users/camilapaiva/Documents/GitHub/db-mining/resources/vulnerabilities/overlap_versions_by_project.xlsx"
with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
    overlap_df.to_excel(writer, index=False, sheet_name="VersionOverlap")

out_path
