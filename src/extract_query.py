"""Extract classes heuristic from last version

Equivalent to `
    extract.py --proportional --slices 1 \\
        --label-type query \\
        --heuristics resources/heuristics/.query \\
        --skip-remove \\
        --may-grep-workspace
`
"""
from extract import read_args, process_projects
from util import HEURISTICS_DIR_QUERY

def main():
    args = read_args(
        'extract_query', 
        'Extract `query` heuristics from last version',
        default_proportional=True,
        default_slices=1,
        default_label_type="query",
        default_skip_remove=True,
        default_heuristics=HEURISTICS_DIR_QUERY,
        default_grep_workspace=True
    )
    process_projects(args)

if __name__ == "__main__":
    main()
