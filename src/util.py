import sys


def graceful_exit(now=False):
    """
    Gracefully exit the program.
    """
    if not now:
        input("Press ENTER to exit.")
    sys.exit(0)
