"""Extract classes heuristic from last version

Equivalent to `
    extract.py --proportional --slices 1 \\
        --label-type implementation \\
        --heuristics resources/heuristics/.implementation \\
        --skip-remove \\
        --may-grep-workspace
`
"""
from extract import read_args, process_projects
from util import HEURISTICS_DIR_IMPLEMENTATION

def main():
    args = read_args(
        'extract_implementation', 
        'Extract `implementation` heuristics from last version',
        default_proportional=True,
        default_slices=1,
        default_label_type="implementation",
        default_skip_remove=True,
        default_heuristics=HEURISTICS_DIR_IMPLEMENTATION,
        default_grep_workspace=True
    )
    process_projects(args)

if __name__ == "__main__":
    main()
