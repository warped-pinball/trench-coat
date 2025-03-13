import sys

from src.cli import cmd_mode, parse_args
from src.interactive import interactive_mode


def main():
    args = parse_args()

    # If no arguments provided or interactive mode explicitly requested, run in interactive mode
    if len(sys.argv) == 1 or args.interactive:
        interactive_mode()
    else:
        # Process command line arguments
        cmd_mode(args)


if __name__ == "__main__":
    main()
