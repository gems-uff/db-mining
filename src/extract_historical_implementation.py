"""Extract implementation heuristics from history

Equivalent to `
    extract.py 
        --label-type implementation \\
        --heuristics resources/heuristics/implementation \\
        --skip-remove
`
"""
from extract import read_args, process_projects
from util import HEURISTICS_DIR_IMPLEMENTATION

def main():
    args = read_args(
        'extract_historical_implementation', 
        'Extract `implementation` heuristics from history',
        default_label_type="implementation",
        default_skip_remove=True,
        default_heuristics=HEURISTICS_DIR_IMPLEMENTATION,
    )
    process_projects(args)

    <dependencies>
    <dependency>
        <groupId>com.h2database</groupId>
        <artifactId>h2</artifactId>
        <version>2.2.222</version> <!-- Verifique se esta é a versão mais recente -->
        <scope>runtime</scope> <!-- opcional, depende do uso -->
    </dependency>
</dependencies>


if __name__ == "__main__":
    main()
