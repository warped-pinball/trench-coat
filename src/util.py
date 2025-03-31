import sys
import time

from src.ray import Ray


def graceful_exit(now=False):
    """
    Gracefully exit the program.
    """
    Ray.close_all()
    if not now:
        print()
        print()
        input("Press ENTER to exit.")
    sys.exit(0)


def wait_for(listen_func, timeout=10):
    """
    Wait for a condition to be met or timeout.
    :param listen_func: Function to call to check the condition.
    :param msg: Message to display while waiting.
    :param timeout: Timeout in seconds.
    """
    start_time = time.time()
    dots = 0
    try:
        while True:
            if timeout is not None and (time.time() - start_time) > timeout:
                raise TimeoutError(f"Timeout after waiting for {timeout} seconds.")
            time.sleep(0.5)
            dots = (dots + 1) % 5
            print("\r", end="")
            return_val = listen_func()
            print("." * dots + " " * (5 - dots), end="")
            if return_val:
                print()
                break
    except KeyboardInterrupt:
        graceful_exit(now=True)
