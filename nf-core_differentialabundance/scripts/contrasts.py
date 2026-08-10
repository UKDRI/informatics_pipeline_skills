#!/usr/bin/env python3
"""Build and validate the nf-core:differentialabundance contrasts sheet.

Why this exists (see repo DESIGN.md §6, "Contrast ids"): a contrast's `id` is not
cosmetic. In the UKDRI fork it becomes `ext.prefix` for DESEQ2_DIFFERENTIAL,
LIMMA_DIFFERENTIAL and FILTER_DIFFTABLE, which the R templates paste straight into
filenames (`<id>.deseq2.results.tsv`), and a publishDir path component for
GPROFILER2_GOST and PROTEUS. So an id carrying '/', ';', a space or a shell
metacharacter yields broken paths, stray directories, or output nobody can glob —
and nothing upstream checks it: the fork ships no schema_contrasts.json, and when the
column is empty the workflow invents an id with `it.values().join('_')`, raw
observation values and all.

Two subcommands:
  build  — derive/normalise the `id` column and write a contrasts.csv into --dest
           (the source file is never mutated)
  check  — validate an existing contrasts file; exit 1 on any error

`check_file()` is also the importable entry point that build_job.py pre-flights via
CONFIG["sheet_checks"], so an unsafe sheet is caught before params.yml is written.

Stdlib only. Deterministic output. Writes only into --dest (DESIGN.md §7).
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys

# --------------------------------------------------------------------------- #
# Constants (the conventions live here, not inline — DESIGN.md §6)
# --------------------------------------------------------------------------- #
# Filename-safe id charset. Deliberately not stricter: '.' and '-' are safe in a
# path and meaningful in level names (e.g. braak5-6).
ID_SAFE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
ID_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
ID_SEP = "__"          # field separator inside a generated id
VS_TOKEN = "vs"        # separates target from reference
BLOCK_TOKEN = "block"  # marks the start of the blocking-variable list
BLOCKING_DELIM = ";"   # what deseq_de.R / limma_de.R split the blocking column on
REQUIRED_COLS = ("variable", "reference", "target")
KNOWN_COLS = ("id", "variable", "reference", "target", "blocking",
              "exclude_samples_col", "exclude_samples_values")
OUT_FIELD_ORDER = ("id", "variable", "reference", "target", "blocking")
OUT_NAME = "contrasts.csv"
# R's make.names() keeps letters, digits, '.' and '_' and requires a non-numeric
# start; anything else in a blocking variable name is silently rewritten there.
MAKE_NAMES_SAFE_RE = re.compile(r"^[A-Za-z.][A-Za-z0-9._]*$")


def die(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    sys.exit(f"ERROR: {msg}")


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Id construction
# --------------------------------------------------------------------------- #
def sanitize_token(value: str) -> str:
    """One id token: unsafe runs -> '_', '_' runs collapsed, ends trimmed.

    Collapsing '_' runs is what keeps ID_SEP ('__') unambiguous even though '_' is
    itself a legal token character: a token can never contain a double underscore.
    Returns '' when nothing usable is left — the caller decides what that means.
    """
    token = ID_UNSAFE_RE.sub("_", (value or "").strip())
    token = re.sub(r"_{2,}", "_", token)
    return token.strip("._-")


def split_blocking(value: str) -> list:
    """The blocking column as a list of variable names.

    deseq_de.R / limma_de.R both do
        strsplit(opt$blocking_variables, split = ';')
    so the delimiter is a semicolon, not a colon. An empty value, or the literal
    'NA' the pipeline strips, means no blocking variables.
    """
    out = []
    for part in (value or "").split(BLOCKING_DELIM):
        part = part.strip()
        if part and part != "NA":
            out.append(part)
    return out


def make_id(variable: str, reference: str, target: str, blocking: str = "") -> str:
    """The house contrast id: variable__target__vs__reference[__block__<b>...].

    Target before reference because that is the direction of the reported fold
    change. Every token is sanitized, so values such as 'AD/CTRL' or 'Braak 5-6'
    cannot leak a path separator or a space into an output filename.
    """
    parts = [variable, target, VS_TOKEN, reference]
    blocks = split_blocking(blocking)
    if blocks:
        parts += [BLOCK_TOKEN] + blocks
    tokens = []
    for part in parts:
        token = sanitize_token(part)
        if not token:
            die(f"cannot build a contrast id: {part!r} has no usable "
                f"[A-Za-z0-9._-] characters")
        tokens.append(token)
    return ID_SEP.join(tokens)


def illegal_chars(value: str) -> list:
    """The distinct characters in `value` that are not allowed in an id."""
    return sorted({c for c in value if not re.match(r"[A-Za-z0-9._-]", c)})


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
def read_contrasts(path: str) -> tuple:
    """Return (rows, fieldnames) from a contrasts CSV/TSV, values stripped.

    The pipeline accepts either separator, so the delimiter comes from the
    extension: .tsv/.txt are tab-separated, everything else comma-separated.
    """
    ext = os.path.splitext(path)[1].lower()
    delim = "\t" if ext in (".tsv", ".txt") else ","
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh, delimiter=delim)
        fields = [(f or "").strip() for f in (reader.fieldnames or [])]
        rows = []
        for raw in reader:
            row = {}
            for key, val in raw.items():
                if key is None:  # values past the header width
                    continue
                row[key.strip()] = val.strip() if isinstance(val, str) else (val or "")
            rows.append(row)
    return rows, fields


# --------------------------------------------------------------------------- #
# Validation (also imported by build_job.py via CONFIG["sheet_checks"])
# --------------------------------------------------------------------------- #
def check_file(path: str) -> tuple:
    """Validate a contrasts sheet. Returns (errors, warnings) — never raises.

    Errors are things that break the run or silently produce the wrong model or
    unusable output paths; warnings are advisory.
    """
    errors: list = []
    warnings: list = []
    if not os.path.isfile(path):
        return [f"contrasts file not found: {path}"], warnings
    name = os.path.basename(path)
    try:
        rows, fields = read_contrasts(path)
    except OSError as exc:
        return [f"cannot read {path}: {exc}"], warnings
    except csv.Error as exc:
        return [f"{name} is not parseable as CSV/TSV: {exc}"], warnings
    if not fields:
        return [f"{name}: no header row"], warnings

    missing = [c for c in REQUIRED_COLS if c not in fields]
    if missing:
        errors.append(f"{name}: missing required column(s): {', '.join(missing)} "
                      f"(header: {', '.join(fields)})")
    for field in fields:
        if field not in KNOWN_COLS:
            warnings.append(f"{name}: unrecognised column {field!r}; known columns are "
                            f"{', '.join(KNOWN_COLS)}")
    if not rows:
        errors.append(f"{name}: no contrast rows")
    has_id = "id" in fields
    if not has_id:
        warnings.append(
            f"{name}: no 'id' column — the pipeline will invent one per contrast with "
            f"it.values().join('_'), concatenating raw observation values (spaces and "
            f"slashes included) into every output filename. Generate ids with: "
            f"contrasts.py build --in {name} --dest <dir>")

    seen: dict = {}
    bad_ids = False
    for num, row in enumerate(rows, start=2):  # row 1 is the header
        blocking = row.get("blocking", "")
        if ":" in blocking:
            # The colon spelling is not rejected by the pipeline: it is read as one
            # variable name, make.names() mangles it, and the model is silently wrong.
            errors.append(
                f"{name} row {num}: blocking {blocking!r} looks colon-separated. It is "
                f"split on '{BLOCKING_DELIM}' (deseq_de.R / limma_de.R), so this is read as "
                f"ONE variable name and the model is silently wrong — use "
                f"{blocking.replace(':', BLOCKING_DELIM)!r}")
            blocking = ""  # the error above already explains it; skip the per-name checks
        for block in split_blocking(blocking):
            if not MAKE_NAMES_SAFE_RE.match(block):
                warnings.append(f"{name} row {num}: blocking variable {block!r} will be "
                                f"rewritten by R's make.names(); it must match an "
                                f"observations column after that rewrite")
            if "NA" in block:
                warnings.append(f"{name} row {num}: blocking variable {block!r} contains "
                                f"'NA', which the pipeline strips with "
                                f"it.blocking.replace('NA', '') — rename the column")
        if not has_id:
            continue
        cid = row.get("id", "")
        if not cid:
            errors.append(f"{name} row {num}: empty 'id'")
            bad_ids = True
            continue
        if not ID_SAFE_RE.match(cid):
            chars = ", ".join(repr(c) for c in illegal_chars(cid))
            suggestion = sanitize_token(cid)
            errors.append(
                f"{name} row {num}: id {cid!r} contains illegal character(s): {chars}. "
                f"Contrast ids become output filename and publishDir prefixes, so only "
                f"[A-Za-z0-9._-] is allowed" +
                (f" — use {suggestion!r}" if suggestion else ""))
            bad_ids = True
        if cid in seen:
            errors.append(f"{name} row {num}: duplicate id {cid!r} (also row {seen[cid]}); "
                          f"the two contrasts would overwrite each other's output files")
            bad_ids = True
        else:
            seen[cid] = num
    if bad_ids:
        warnings.append(f"{name}: to regenerate every id to the house convention "
                        f"({ID_SEP.join(['<variable>', '<target>', VS_TOKEN, '<reference>'])}"
                        f"[{ID_SEP}{BLOCK_TOKEN}{ID_SEP}<blocking>...]), run: "
                        f"contrasts.py build --in {name} --dest <dir> --rebuild-ids")
    return errors, warnings


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def parse_contrast_spec(spec: str) -> dict:
    """'variable=condition,reference=control,target=treated,blocking=sex;batch' -> row.

    Comma-separated key=value pairs; the blocking list keeps its own ';' delimiter,
    so it needs no escaping.
    """
    row: dict = {}
    for field in spec.split(","):
        if not field.strip():
            continue
        if "=" not in field:
            die(f"--contrast expects comma-separated key=value pairs, got {field!r} "
                f"in {spec!r}")
        key, val = field.split("=", 1)
        key = key.strip()
        if key not in KNOWN_COLS:
            die(f"--contrast: unknown key {key!r}; allowed: {', '.join(KNOWN_COLS)}")
        row[key] = val.strip()
    missing = [c for c in REQUIRED_COLS if not row.get(c)]
    if missing:
        die(f"--contrast {spec!r}: missing {', '.join(missing)}")
    return row


def cmd_build(args) -> None:
    if bool(args.infile) == bool(args.specs):
        die("give exactly one of --in <file> or --contrast <spec> (repeatable)")

    if args.infile:
        if not os.path.isfile(args.infile):
            die(f"no such file: {args.infile}")
        try:
            rows, fields = read_contrasts(args.infile)
        except (OSError, csv.Error) as exc:
            die(f"cannot read {args.infile}: {exc}")
        missing = [c for c in REQUIRED_COLS if c not in fields]
        if missing:
            die(f"{args.infile}: missing required column(s): {', '.join(missing)} "
                f"(header: {', '.join(fields)})")
    else:
        rows = [parse_contrast_spec(s) for s in args.specs]
        fields = [c for c in KNOWN_COLS if any(r.get(c) for r in rows)]
    if not rows:
        die("no contrast rows to write")

    # id, variable, reference, target, blocking, then any extra input columns in order
    out_fields = list(OUT_FIELD_ORDER) + [f for f in fields if f not in OUT_FIELD_ORDER]

    reports = []
    for num, row in enumerate(rows, start=2):  # row 1 is the header
        for col in REQUIRED_COLS:
            if not row.get(col):
                die(f"row {num}: '{col}' is empty; every contrast needs "
                    f"{', '.join(REQUIRED_COLS)}")
        # Caught before anything is written, so --dest never gets a sheet that the
        # check below would reject (a colon list silently becomes one variable name).
        if ":" in row.get("blocking", ""):
            die(f"row {num}: blocking {row['blocking']!r} looks colon-separated; it is "
                f"split on '{BLOCKING_DELIM}' — use "
                f"{row['blocking'].replace(':', BLOCKING_DELIM)!r}")
        derived = make_id(row["variable"], row["reference"], row["target"],
                          row.get("blocking", ""))
        current = (row.get("id") or "").strip()
        if not current:
            action = "derived"
        elif args.rebuild_ids:
            action = "kept" if current == derived else "rebuilt"
        elif ID_SAFE_RE.match(current):
            derived, action = current, "kept"
        else:
            chars = ", ".join(repr(c) for c in illegal_chars(current))
            warn(f"row {num}: id {current!r} contains illegal character(s): {chars}; "
                 f"replaced with {derived!r}")
            action = "replaced"
        row["id"] = derived
        reports.append((num, derived, action))

    seen: dict = {}
    for num, cid, _ in reports:
        if cid in seen:
            die(f"row {num}: id {cid!r} duplicates row {seen[cid]}. Two contrasts would "
                f"overwrite each other's output files — drop the duplicate row, or give "
                f"the rows distinct explicit ids")
        seen[cid] = num

    os.makedirs(args.dest, exist_ok=True)
    out_path = os.path.join(args.dest, args.out_name)
    if args.infile and os.path.exists(out_path) and os.path.samefile(args.infile, out_path):
        die(f"output {out_path} is the same file as --in; the source sheet is never "
            f"mutated — choose a different --dest or --out-name")
    with open(out_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=out_fields, extrasaction="ignore",
                                lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in out_fields})

    errors, warnings = check_file(out_path)
    for msg in warnings:
        warn(msg)
    if errors:
        die("the generated sheet does not validate:\n       " + "\n       ".join(errors))

    print(f"contrasts: {out_path}  ({len(rows)} contrast(s))")
    for num, cid, action in reports:
        print(f"  row {num}: {cid}  ({action})")


# --------------------------------------------------------------------------- #
# check
# --------------------------------------------------------------------------- #
def cmd_check(args) -> None:
    errors, warnings = check_file(args.contrasts)
    for msg in warnings:
        warn(msg)
    if errors:
        for msg in errors:
            print(f"ERROR: {msg}", file=sys.stderr)
        sys.exit(1)
    rows, _ = read_contrasts(args.contrasts)
    print(f"contrasts OK: {args.contrasts}  ({len(rows)} contrast(s))")
    for num, row in enumerate(rows, start=2):
        cid = row.get("id") or "(no id column — derived by the pipeline)"
        print(f"  row {num}: {cid}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build or validate the nf-core:differentialabundance contrasts sheet.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="write a contrasts.csv with validated ids into --dest")
    b.add_argument("--in", dest="infile",
                   help="draft contrasts CSV/TSV (columns: "
                        f"{','.join(REQUIRED_COLS)}[,blocking][,id]); never modified")
    b.add_argument("--contrast", dest="specs", action="append", default=[],
                   help="one contrast as key=value pairs, e.g. "
                        "'variable=condition,reference=control,target=treated,"
                        "blocking=sex;batch' (repeatable; alternative to --in)")
    b.add_argument("--rebuild-ids", action="store_true",
                   help="regenerate every id to the house convention, replacing ids that "
                        "are safe but non-canonical")
    b.add_argument("--dest", default=".", help="output directory (default: .)")
    b.add_argument("--out-name", default=OUT_NAME, help=f"output filename (default: {OUT_NAME})")
    b.set_defaults(func=cmd_build)

    c = sub.add_parser("check", help="validate an existing contrasts sheet (exit 1 on error)")
    c.add_argument("--contrasts", required=True, help="path to the contrasts CSV/TSV")
    c.set_defaults(func=cmd_check)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
