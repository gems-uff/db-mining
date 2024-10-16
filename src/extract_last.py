"""Extract heuristics from last version

Equivalent to `extract.py -p -s 1`
"""
from extract import read_args, process_projects


def main():
    args = read_args(
        'extract_last', 
        'Extract heuristics from last version',
        default_proportional=True,
        default_slices=1,
    )
    process_projects(args)

if __name__ == "__main__":
    main()