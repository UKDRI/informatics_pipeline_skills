#!/usr/bin/env python3
"""Validate the per-sample metadata TSV for nf-core:scdownstream's qc_clustering entry.

Why this exists (see repo DESIGN.md §8 and SKILL.md §4): `--metadata` adds every column of
a per-sample TSV to the cells' obs, and those columns are what the differential_genes
stage contrasts (condition, treatment, ...) and blocks on (donor, sex, ...). The fork's
ADATA_ADDMETADATA step stops the run on a malformed file — but only after the per-sample
inputs have been loaded on the cluster. These are the same rules, checked up front.

The file belongs to the user. This script only reads it: it never builds, fixes or
rewrites a metadata file. Problems are reported for the user to correct.

One subcommand:
  check  — validate a metadata TSV, optionally against the samplesheet; exit 1 on any error

`check_file()` is also the importable entry point that build_job.py pre-flights via
CONFIG["sheet_checks"], so a bad file is caught before params_qc_clustering.yml is written.

Stdlib only.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys

# --------------------------------------------------------------------------- #
# Constants — mirror modules/local/adata/addmetadata/templates/add_metadata.py
# --------------------------------------------------------------------------- #
DEFAULT_SAMPLE_COL = "sample"   # the pipeline's metadata_sample_col default
# Created by the pipeline itself; a metadata column with one of these names stops the run.
RESERVED_COLS = ("batch", "label", "sample_original", "outlier")
# Always present in obs when metadata is added (ADATA_ADDSAMPLE runs first), so a metadata
# column of this name clashes unless it IS the sample-id column.
OBS_SAMPLE_COL = "sample"
# Written to obs by later steps, which would silently replace a metadata column of that name.
OVERWRITTEN_COLS = ("n_genes_by_counts", "total_counts", "pct_counts_mt", "n_genes",
                    "n_counts", "doublet_score", "predicted_doublet", "leiden")
OVERWRITTEN_RE = re.compile(r"^(celltypist:.*|leiden_.*|total_counts_.*|pct_counts_.*|"
                            r"log1p_.*|n_cells_by_counts)$")
TSV_EXTS = (".tsv", ".txt", ".tab")


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


def samplesheet_ids(path: str) -> list:
    """The `sample` column of a samplesheet CSV, in order, without duplicates."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if "sample" not in (reader.fieldnames or []):
            raise ValueError(f"samplesheet {path} has no 'sample' column")
        seen: list = []
        for row in reader:
            sid = (row.get("sample") or "").strip()
            if sid and sid not in seen:
                seen.append(sid)
    return seen


def check_file(path: str, context: dict | None = None,
               sample_col: str | None = None, samplesheet: str | None = None) -> tuple:
    """Validate a metadata TSV. Returns (errors, warnings) — never raises.

    `context` is what build_job.py's sheet_checks hook passes: the resolved params (for
    metadata_sample_col) and --input (the samplesheet, cross-checked when it is a local
    file). The CLI passes `sample_col` / `samplesheet` directly instead.
    """
    context = context or {}
    params = context.get("params") or {}
    sample_col = sample_col or params.get("metadata_sample_col") or DEFAULT_SAMPLE_COL
    if samplesheet is None:
        candidate = context.get("input")
        if candidate and os.path.isfile(candidate) and candidate.lower().endswith(".csv"):
            samplesheet = candidate

    errors: list = []
    warnings: list = []
    name = os.path.basename(path)
    if not os.path.isfile(path):
        return [f"metadata file not found: {path}"], warnings

    ext = os.path.splitext(path)[1].lower()
    if ext not in TSV_EXTS:
        errors.append(f"{name}: the pipeline reads --metadata as TAB-separated; give a .tsv file"
                      + (" (this looks like a CSV — save it with tabs instead of commas)"
                         if ext == ".csv" else ""))
        return errors, warnings

    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh, delimiter="\t"))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return [f"cannot read {path}: {exc}"], warnings
    rows = [r for r in rows if any(c.strip() for c in r)]   # pandas skips blank lines too
    if not rows:
        return [f"{name} is empty"], warnings

    header = [c.strip() for c in rows[0]]
    if len(header) == 1 and "," in header[0]:
        return [f"{name}: the header has no tabs but contains commas — the file must be "
                "tab-separated, not comma-separated"], warnings
    if "" in header:
        errors.append(f"{name}: empty column name in the header (column "
                      f"{header.index('') + 1}) — often a trailing tab")
    dups = sorted({c for c in header if c and header.count(c) > 1})
    if dups:
        errors.append(f"{name}: duplicate column name(s): {', '.join(dups)}")
    if sample_col not in header:
        errors.append(f"{name}: no sample-id column '{sample_col}' (metadata_sample_col). "
                      f"Columns: {', '.join(header)}")
        return errors, warnings

    new_cols = [c for c in header if c and c != sample_col]
    if not new_cols:
        errors.append(f"{name}: needs at least one column besides '{sample_col}'")
    reserved = [c for c in new_cols if c in RESERVED_COLS]
    if reserved:
        errors.append(f"{name}: column name(s) {', '.join(reserved)} are reserved by the pipeline "
                      f"({', '.join(RESERVED_COLS)}); rename them, e.g. 'batch' -> 'seq_batch'")
    if OBS_SAMPLE_COL in new_cols:
        errors.append(f"{name}: a '{OBS_SAMPLE_COL}' column clashes with the one the pipeline adds "
                      f"to obs; with metadata_sample_col = '{sample_col}' rename or drop it")
    overwritten = [c for c in new_cols if c in OVERWRITTEN_COLS or OVERWRITTEN_RE.match(c)]
    if overwritten:
        warnings.append(f"{name}: column(s) {', '.join(overwritten)} are rewritten in obs by later "
                        "pipeline steps (QC metrics, doublets, CellTypist, Leiden) without a "
                        "warning; rename them to keep your values")

    idx = header.index(sample_col)
    ids: list = []
    for n, row in enumerate(rows[1:], start=1):
        if len(row) > len(header):
            errors.append(f"{name}: data row {n} has {len(row)} fields but the header has "
                          f"{len(header)}")
        sid = row[idx].strip() if idx < len(row) else ""
        if not sid or sid.upper() in ("NA", "NAN"):
            errors.append(f"{name}: data row {n} has an empty '{sample_col}'")
            continue
        ids.append(sid)
    dup_ids = sorted({s for s in ids if ids.count(s) > 1})
    if dup_ids:
        errors.append(f"{name}: duplicate sample id(s) in '{sample_col}': {', '.join(dup_ids)}")
    if not ids:
        errors.append(f"{name}: no data rows")

    for col in new_cols:
        values = {(r[header.index(col)].strip() if header.index(col) < len(r) else "")
                  for r in rows[1:]}
        if values <= {""}:
            warnings.append(f"{name}: column '{col}' is empty for every sample")

    if samplesheet:
        try:
            wanted = samplesheet_ids(samplesheet)
        except (OSError, ValueError, csv.Error) as exc:
            warnings.append(f"could not cross-check against the samplesheet: {exc}")
        else:
            missing = [s for s in wanted if s not in ids]
            if missing:
                errors.append(f"{name}: samplesheet sample(s) with no metadata row: "
                              f"{', '.join(missing)} — the pipeline stops on these")
            unused = [s for s in ids if s not in wanted]
            if unused:
                warnings.append(f"{name}: {len(unused)} row(s) for samples not in the samplesheet "
                                f"(ignored by the pipeline): {', '.join(unused[:10])}"
                                + (" ..." if len(unused) > 10 else ""))
    return errors, warnings


def cmd_check(args) -> None:
    errors, warnings = check_file(args.metadata, sample_col=args.metadata_sample_col,
                                  samplesheet=args.input)
    for msg in warnings:
        warn(msg)
    if errors:
        for msg in errors:
            print(f"ERROR: {msg}", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {args.metadata}" + (f" (checked against {args.input})" if args.input else ""))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate a per-sample metadata TSV; exit 1 on errors")
    c.add_argument("--metadata", required=True, help="the per-sample metadata TSV")
    c.add_argument("--input", help="the samplesheet.csv: every sample must have a metadata row")
    c.add_argument("--metadata-sample-col", "--metadata_sample_col", dest="metadata_sample_col",
                   default=DEFAULT_SAMPLE_COL,
                   help=f"column holding the samplesheet sample ids (default: {DEFAULT_SAMPLE_COL})")
    c.set_defaults(func=cmd_check)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
