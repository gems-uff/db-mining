"""Extract classes heuristic from last version

Equivalent to `
    extract.py --proportional --slices 1 \\
        --label-type classes \\
        --heuristics resources/heuristics/first-level \\
        --label-selection project \\
        --skip-remove
`
"""
from extract import read_args, process_projects
from util import HEURISTICS_DIR_FIRST_LEVEL

def main():
    args = read_args(
        'extract_classes', 
        'Extract `classes` heuristics from last version',
        default_proportional=True,
        default_slices=1,
        default_label_type="classes",
        default_skip_remove=True,
        default_heuristics=HEURISTICS_DIR_FIRST_LEVEL,
        default_label_selection="project"
    )
    print(args)
    process_projects(args)

if __name__ == "__main__":
    main()
