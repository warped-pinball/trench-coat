"""Small terminal-output helpers for consistent structure, color and indentation.

The flashing flow prints a lot of progress text. Routing it through these
helpers gives the output a clear visual hierarchy -- top-level phases, the
steps inside them, and their details -- and color-codes success / warning /
error lines so problems are easy to spot at a glance.

Everything degrades gracefully:

* Color is disabled when ``NO_COLOR`` is set, when stdout is not a terminal
  (e.g. when piped or captured by tests), or when the terminal can't be put
  into ANSI mode. ``FORCE_COLOR`` overrides the TTY check.
* Status symbols fall back to ASCII when stdout's encoding can't represent the
  Unicode ones (some frozen Windows consoles use cp1252).
"""

import os
import sys

# --- indentation ------------------------------------------------------------

# One indent level. Phases sit at column 0, their steps at one level, and
# per-step details at two.
INDENT = "  "


# --- color ------------------------------------------------------------------

_CODES = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
    "gray": "\033[90m",
    "on_green": "\033[42m",
    "black": "\033[30m",
}


def _enable_windows_ansi() -> bool:
    """Turn on ANSI escape processing for the Windows console.

    Windows 10+ consoles understand ANSI escapes but only once the
    ENABLE_VIRTUAL_TERMINAL_PROCESSING flag is set. Returns True on success.
    """
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return True
    except Exception:
        return False


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    stream = sys.stdout
    is_tty = hasattr(stream, "isatty") and stream.isatty()
    if os.environ.get("FORCE_COLOR"):
        forced = True
    else:
        forced = False
    if not is_tty and not forced:
        return False
    if os.name == "nt":
        return _enable_windows_ansi()
    return True


_COLOR = _supports_color()


def _c(text: str, *styles: str) -> str:
    """Wrap ``text`` in the given style codes, if color is enabled."""
    if not _COLOR or not styles:
        return text
    return "".join(_CODES[s] for s in styles) + text + _CODES["reset"]


# --- status symbols ---------------------------------------------------------


def _symbol(unicode_sym: str, ascii_sym: str) -> str:
    """Return ``unicode_sym`` if stdout can encode it, else ``ascii_sym``."""
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        unicode_sym.encode(encoding)
        return unicode_sym
    except (UnicodeEncodeError, LookupError):
        return ascii_sym


_SYM_STEP = _symbol("•", "-")  # bullet
_SYM_OK = _symbol("✓", "OK")  # check mark
_SYM_WARN = _symbol("⚠", "!")  # warning sign
_SYM_ERR = _symbol("✗", "x")  # ballot x


# --- public helpers ---------------------------------------------------------


def title(text: str) -> None:
    """A bold banner line with no leading blank (used for the welcome banner)."""
    print(_c(text, "bold", "cyan"))


def heading(text: str) -> None:
    """A top-level phase header, preceded by a blank line for separation."""
    print()
    print(_c(text, "bold", "cyan"))


def step(text: str, indent: int = 1) -> None:
    """An action within a phase, prefixed with a bullet."""
    print(f"{INDENT * indent}{_c(_SYM_STEP, 'cyan')} {text}")


def detail(text: str, indent: int = 2) -> None:
    """A subordinate detail line, dimmed."""
    print(_c(f"{INDENT * indent}{text}", "dim"))


def success(text: str, indent: int = 1) -> None:
    print(f"{INDENT * indent}{_c(_SYM_OK, 'green')} {_c(text, 'green')}")


def warning(text: str, indent: int = 1) -> None:
    print(f"{INDENT * indent}{_c(_SYM_WARN, 'yellow')} {_c(text, 'yellow')}")


def error(text: str, indent: int = 1) -> None:
    print(f"{INDENT * indent}{_c(_SYM_ERR, 'red')} {_c(text, 'red')}")


def done(text: str) -> None:
    """A prominent, highlighted completion banner, set off by blank lines.

    Rendered as bold text on a green background when color is available, and
    as a plain bracketed banner otherwise, so success is unmistakable.
    """
    print()
    label = f" {_SYM_OK}  {text} "
    if _COLOR:
        print(_c(label, "bold", "black", "on_green"))
    else:
        print(f"=== {text} ===")
    print()


def plain(text: str = "", indent: int = 0) -> None:
    """An uncolored line at the given indent level."""
    print(f"{INDENT * indent}{text}" if text else "")


def status(text: str, indent: int = 1) -> str:
    """Return an indented, dimmed status string for in-place (``\\r``) updates.

    Used by the spinner in ``wait_for`` so repeatedly-redrawn progress lines
    share the indentation and dim styling of the surrounding output.
    """
    return _c(f"{INDENT * indent}{text}", "dim")
