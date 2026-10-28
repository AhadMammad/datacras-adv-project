"""advgen command line: `uv run advgen build` regenerates every artifact."""
from __future__ import annotations

import argparse
import json
import shutil

from . import emit_docs, emit_smoke, emit_sql
from .build import ROOT, build_model, load_yaml


def build() -> None:
    model = build_model()
    part = load_yaml("conventions.yaml")["partitioning"]
    physical = ROOT / "models" / "physical"
    shutil.rmtree(physical, ignore_errors=True)
    emit_sql.emit(model, ROOT, (str(part["window_start"]), part["window_months"]))
    (physical / "manifest.json").write_text(json.dumps(emit_sql.manifest(model), indent=2) + "\n")
    emit_smoke.emit(model, ROOT)
    emit_docs.emit(model, ROOT)
    print(f"built {len(model.tables)} tables in {len(model.systems)} systems")


def main() -> None:
    p = argparse.ArgumentParser(prog="advgen")
    p.add_argument("command", choices=["build"])
    args = p.parse_args()
    {"build": build}[args.command]()
