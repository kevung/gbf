"""Convert .py scripts to .ipynb notebooks.

Run once from the notebooks/ directory:
    python3 make_notebooks.py
"""
import json, re, os

SCRIPTS = [
    ("01_umap.py",       "01_umap.ipynb"),
    ("02_pca.py",        "02_pca.ipynb"),
    ("03_clustering.py", "03_clustering.ipynb"),
    ("04_difficulty.py", "04_difficulty.ipynb"),
    ("05_players.py",    "05_players.ipynb"),
]

def py_to_notebook(py_path):
    with open(py_path) as f:
        source = f.read()

    lines = source.split("\n")
    cells = []

    # Split on section comments (# ── ... ───) or top docstring.
    i = 0
    buf = []
    in_docstring = False

    for line in lines:
        # Top module docstring → markdown cell.
        if not cells and line.startswith('"""'):
            in_docstring = not in_docstring
            buf.append(line.lstrip('"').rstrip('"'))
            continue
        if in_docstring:
            if line.strip().endswith('"""'):
                in_docstring = False
                buf.append(line.rstrip('"'))
                cells.append({"cell_type": "markdown",
                              "source": "\n".join(buf).strip(),
                              "metadata": {}})
                buf = []
            else:
                buf.append(line)
            continue

        # Section separator → flush code cell, start new section label.
        if re.match(r"^# ── ", line):
            if buf and any(l.strip() for l in buf):
                cells.append({"cell_type": "code",
                              "source": "\n".join(buf).rstrip(),
                              "metadata": {},
                              "outputs": [],
                              "execution_count": None})
            buf = [line]
        else:
            buf.append(line)

    if buf and any(l.strip() for l in buf):
        cells.append({"cell_type": "code",
                      "source": "\n".join(buf).rstrip(),
                      "metadata": {},
                      "outputs": [],
                      "execution_count": None})

    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.12"},
        },
        "cells": cells,
    }


for src, dst in SCRIPTS:
    nb = py_to_notebook(src)
    with open(dst, "w") as f:
        json.dump(nb, f, indent=1, ensure_ascii=False)
    print(f"  {src} → {dst}  ({len(nb['cells'])} cells)")

print("done.")
