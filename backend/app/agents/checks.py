"""Checks on what an LLM writes. The most important: every figure in an
answer must come from the data the model was given, or it may be made up.
"""
import re

FIGURE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def figures(text: str) -> list[str]:
    """Every number in the text, without separators: "₹1,23,456.7" -> "123456.7"."""
    return [f.replace(",", "") for f in FIGURE.findall(text)]


def number_in(value: float, source: str) -> bool:
    """Whether a number the model extracted appears in the source text
    (10741149 matches "1,07,41,149"; 7200.0 matches "7,200.00")."""
    if float(value).is_integer():
        text = str(int(value))
    else:
        text = f"{value:.4f}".rstrip("0").rstrip(".")
    return not unsupported_figures(text, source)


def unsupported_figures(text: str, source: str) -> list[str]:
    """Figures in `text` that don't appear in `source`. A figure counts as
    found if it's within one unit of its last digit of a source figure, so
    rounded or truncated figures pass (70.92 supports 70.9, 71 and 70), but
    64.1 doesn't support 80. Single digits are skipped: they're usually
    counts like "top 5", not data."""
    known = [float(f) for f in figures(source)]
    unsupported = []
    for figure in figures(text):
        if len(figure) == 1:
            continue
        decimals = len(figure.split(".")[1]) if "." in figure else 0
        if not any(abs(k - float(figure)) < 10 ** -decimals for k in known):
            unsupported.append(figure)
    return unsupported
