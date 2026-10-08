#!/usr/bin/env python3
"""Build and validate the nf-core:scdownstream differential_genes contrasts sheet.

Why this exists (see repo DESIGN.md §8 and SKILL.md §6): `diffgenes_contrasts` follows
the nf-core/differentialabundance contrasts definition, but the UKDRI scdownstream fork
reads it differently from the differentialabundance fork:

  * it is TAB-separated (samplesheetToList against assets/schema_contrasts.json), so
  * `blocking` is COMMA-separated, not ';'-separated, and
  * every field must be free of whitespace (the schema's `^\\S+$` patterns), and `id` is
    required — the pipeline invents none.

The contrast id becomes part of every result filename (<name>_<group>_<id>.tsv), and a
contrast whose reference or target level is absent from the data is SKIPPED SILENTLY.
So a check against the per-sample metadata — the source of condition/treatment
columns — catches a mistyped level before the run instead of after it.

Two subcommands:
  build  — derive/normalise the `id` column and write a contrasts.tsv into --dest
           (the source file is never mutated)
  check  — validate an existing contrasts file, optionally against the metadata TSV;
           exit 1 on any error

`check_file()` is also the importable entry point that build_job.py pre-flights via
CONFIG["sheet_checks"], so a bad sheet is caught before params_differential_genes.yml is
written.

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
# Filename-safe id charset, as in the differentialabundance helper.
ID_SAFE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
ID_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
ID_SEP = "__"          # field separator inside a generated id
VS_TOKEN = "vs"        # separates target from reference
BLOCK_TOKEN = "block"  # marks the start of the blocking-variable list
BLOCKING_DELIM = ","   # what workflows/differential_genes.nf and the DE template split on
REQUIRED_COLS = ("variable", "reference", "target")
KNOWN_COLS = ("id", "variable", "reference", "target", "blocking",
              "exclude_samples_col", "exclude_samples_values")
INACTIVE_COLS = ("exclude_samples_col", "exclude_samples_values")
OUT_FIELD_ORDER = ("id", "variable", "reference", "target", "blocking")
OUT_NAME = "contrasts.tsv"
# obs columns the pipeline itself creates, so a contrast may use them with no metadata.
PIPELINE_OBS_COLS = ("sample", "batch", "label")


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
    """The blocking column as a list of obs column names (comma-separated)."""
    return [part.strip() for part in (value or "").split(BLOCKING_DELIM) if part.strip()]


def make_id(variable: str, reference: str, target: str, blocking: str = "") -> str:
    """The house contrast id: variable__target__vs__reference[__block__<b>...].

    Target before reference because that is the direction of the reported fold
    change. Every token is sanitized, so values such as 'AD/CTRL' cannot leak a path
    separator into an output filename.
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
def read_table(path: str, delim: str) -> tuple:
    """Return (rows, fieldnames) from a delimited file, header and values stripped."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh, delimiter=delim)
        fields = [(f or "").strip() for f in (reader.fieldnames or [])]
        rows = []
        for raw in reader:
            row = {}
            for key, val in raw.items():
                if key is None:  # values past the header width
                    continue
                row[key.strip()] = val.strip() if isinstance(val, str) else (val or "")
            if any(row.values()):
                rows.append(row)
    return rows, fields


def read_contrasts(path: str) -> tuple:
    """Contrasts are always tab-separated for this pipeline."""
    return read_table(path, "\t")


def metadata_levels(path: str) -> dict:
    """{column: set of values} from the per-sample metadata TSV (sample-id column included)."""
    rows, fields = read_table(path, "\t")
    return {f: {r.get(f, "") for r in rows} - {""} for f in fields if f}


# --------------------------------------------------------------------------- #
# Validation (also imported by build_job.py via CONFIG["sheet_checks"])
# --------------------------------------------------------------------------- #
def check_file(path: str, context: dict | None = None, metadata: str | None = None) -> tuple:
    """Validate a contrasts sheet. Returns (errors, warnings) — never raises.

    `context` is what build_job.py's sheet_checks hook passes; its "metadata" path (the
    --metadata flag) is used for the cross-check when it is a readable local file. The
    CLI passes `metadata` directly instead.
    """
    errors: list = []
    warnings: list = []
    if not os.path.isfile(path):
        return [f"contrasts file not found: {path}"], warnings
    name = os.path.basename(path)
    if os.path.splitext(path)[1].lower() not in (".tsv", ".txt", ".tab"):
        return [f"{name}: diffgenes_contrasts must be a TAB-separated .tsv (its blocking column "
                "is comma-separated, so a CSV cannot hold it) — build one with: "
                f"contrasts.py build --in {name} --dest <dir>"], warnings
    try:
        rows, fields = read_contrasts(path)
    except OSError as exc:
        return [f"cannot read {path}: {exc}"], warnings
    except (csv.Error, UnicodeDecodeError) as exc:
        return [f"{name} is not parseable as a TSV: {exc}"], warnings
    if not fields:
        return [f"{name}: no header row"], warnings
    if len(fields) == 1 and "," in fields[0]:
        return [f"{name}: the header has no tabs but contains commas — the file must be "
                "tab-separated"], warnings

    missing = [c for c in ("id",) + REQUIRED_COLS if c not in fields]
    if missing:
        errors.append(f"{name}: missing required column(s): {', '.join(missing)} "
                      f"(header: {', '.join(fields)})"
                      + (" — the pipeline requires an id; generate them with: contrasts.py "
                         f"build --in {name} --dest <dir>" if "id" in missing else ""))
    for field in fields:
        if field not in KNOWN_COLS:
            warnings.append(f"{name}: unrecognised column {field!r}; known columns are "
                            f"{', '.join(KNOWN_COLS)}")
    for field in INACTIVE_COLS:
        if field in fields and any(r.get(field) for r in rows):
            warnings.append(f"{name}: '{field}' is accepted but currently INACTIVE in the "
                            "pipeline — those samples will NOT be excluded")
    if not rows:
        errors.append(f"{name}: no contrast rows")

    meta_path = metadata or (context or {}).get("metadata")
    levels = None
    if meta_path and os.path.isfile(meta_path):
        try:
            levels = metadata_levels(meta_path)
        except (OSError, csv.Error, UnicodeDecodeError) as exc:
            warnings.append(f"could not read the metadata {meta_path} for the cross-check: {exc}")
    meta_name = os.path.basename(meta_path) if meta_path else ""

    seen: dict = {}
    for num, row in enumerate(rows, start=2):  # row 1 is the header
        for col in KNOWN_COLS:
            value = row.get(col, "")
            if col == "blocking" and ";" in value:
                errors.append(f"{name} row {num}: blocking {value!r} is ';'-separated; this "
                              f"pipeline splits on ',' — use {value.replace(';', ',')!r}")
            elif re.search(r"\s", value):
                errors.append(f"{name} row {num}: '{col}' = {value!r} contains whitespace, which "
                              "the pipeline's contrasts schema rejects")
        for col in REQUIRED_COLS:
            if not row.get(col):
                errors.append(f"{name} row {num}: '{col}' is empty")
        if row.get("reference") and row.get("reference") == row.get("target"):
            errors.append(f"{name} row {num}: reference and target are both "
                          f"{row['reference']!r}")

        cid = row.get("id", "")
        if "id" in fields:
            if not cid:
                errors.append(f"{name} row {num}: empty 'id'")
            elif not ID_SAFE_RE.match(cid):
                chars = ", ".join(repr(c) for c in illegal_chars(cid))
                errors.append(f"{name} row {num}: id {cid!r} contains illegal character(s): "
                              f"{chars}. The id becomes part of the result filenames, so only "
                              "[A-Za-z0-9._-] is allowed"
                              + (f" — use {sanitize_token(cid)!r}" if sanitize_token(cid) else ""))
            elif cid in seen:
                errors.append(f"{name} row {num}: duplicate id {cid!r} (also row {seen[cid]}); "
                              "the two contrasts would overwrite each other's results")
            else:
                seen[cid] = num

        if levels is None:
            continue
        variable = row.get("variable", "")
        for col in [variable] + split_blocking(row.get("blocking", "")):
            if col and col not in levels and col not in PIPELINE_OBS_COLS:
                warnings.append(f"{name} row {num}: column {col!r} is not in {meta_name} nor one "
                                f"the pipeline creates ({', '.join(PIPELINE_OBS_COLS)}); it must "
                                "already exist in the input object's obs, or the run stops")
        if variable in levels:
            present = levels[variable]
            for side in ("reference", "target"):
                level = row.get(side, "")
                if level and level not in present:
                    errors.append(
                        f"{name} row {num}: {side} {level!r} does not occur in column "
                        f"{variable!r} of {meta_name} (values: {', '.join(sorted(present))}). "
                        "The pipeline would skip this contrast silently")
    return errors, warnings


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def parse_contrast_spec(spec: str) -> dict:
    """'variable=condition,reference=control,target=treated,blocking=sex+donor' -> row.

    Comma-separated key=value pairs. Because the blocking list is itself comma-separated
    in the sheet, several blocking variables are joined with '+' here.
    """
    row: dict = {}
    for field in spec.split(","):
        if not field.strip():
            continue
        if "=" not in field:
            die(f"--contrast expects comma-separated key=value pairs, got {field!r} "
                f"in {spec!r} (join several blocking variables with '+')")
        key, val = field.split("=", 1)
        key = key.strip()
        if key not in KNOWN_COLS:
            die(f"--contrast: unknown key {key!r}; allowed: {', '.join(KNOWN_COLS)}")
        val = val.strip()
        row[key] = BLOCKING_DELIM.join(p.strip() for p in val.split("+")) if key == "blocking" \
            else val
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
        ext = os.path.splitext(args.infile)[1].lower()
        try:
            rows, fields = read_table(args.infile, "," if ext == ".csv" else "\t")
        except (OSError, csv.Error) as exc:
            die(f"cannot read {args.infile}: {exc}")
        missing = [c for c in REQUIRED_COLS if c not in fields]
        if missing:
            die(f"{args.infile}: missing required column(s): {', '.join(missing)} "
                f"(header: {', '.join(fields)})")
        if ext == ".csv":
            # A CSV cannot carry a comma-separated blocking list; accept the ';' spelling
            # the differentialabundance sheets use and convert it.
            for row in rows:
                if row.get("blocking"):
                    row["blocking"] = BLOCKING_DELIM.join(
                        p.strip() for p in row["blocking"].split(";") if p.strip())
    else:
        rows = [parse_contrast_spec(s) for s in args.specs]
        fields = [c for c in KNOWN_COLS if any(r.get(c) for r in rows)]
    if not rows:
        die("no contrast rows to write")

    out_fields = list(OUT_FIELD_ORDER) + [f for f in fields if f not in OUT_FIELD_ORDER]

    reports = []
    for num, row in enumerate(rows, start=2):  # row 1 is the header
        for col in REQUIRED_COLS:
            if not row.get(col):
                die(f"row {num}: '{col}' is empty; every contrast needs "
                    f"{', '.join(REQUIRED_COLS)}")
        if ";" in row.get("blocking", ""):
            die(f"row {num}: blocking {row['blocking']!r} is ';'-separated; this pipeline "
                f"splits on ',' — use {row['blocking'].replace(';', ',')!r}")
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
                f"overwrite each other's results — drop the duplicate row, or give the rows "
                f"distinct explicit ids")
        seen[cid] = num

    os.makedirs(args.dest, exist_ok=True)
    out_path = os.path.join(args.dest, args.out_name)
    if args.infile and os.path.exists(out_path) and os.path.samefile(args.infile, out_path):
        die(f"output {out_path} is the same file as --in; the source sheet is never "
            f"mutated — choose a different --dest or --out-name")
    with open(out_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=out_fields, extrasaction="ignore",
                                delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in out_fields})

    errors, warnings = check_file(out_path, metadata=args.metadata)
    for msg in warnings:
        warn(msg)
    if errors:
        die(f"the generated sheet {out_path} does not validate:\n       "
            + "\n       ".join(errors))

    print(f"contrasts: {out_path}  ({len(rows)} contrast(s))")
    for num, cid, action in reports:
        print(f"  row {num}: {cid}  ({action})")


# --------------------------------------------------------------------------- #
# check
# --------------------------------------------------------------------------- #
def cmd_check(args) -> None:
    errors, warnings = check_file(args.diffgenes_contrasts, metadata=args.metadata)
    for msg in warnings:
        warn(msg)
    if errors:
        for msg in errors:
            print(f"ERROR: {msg}", file=sys.stderr)
        sys.exit(1)
    rows, _ = read_contrasts(args.diffgenes_contrasts)
    print(f"contrasts OK: {args.diffgenes_contrasts}  ({len(rows)} contrast(s))"
          + (f", checked against {args.metadata}" if args.metadata else ""))
    for num, row in enumerate(rows, start=2):
        print(f"  row {num}: {row.get('id')}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build or validate the nf-core:scdownstream diffgenes_contrasts sheet.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="write a contrasts.tsv with validated ids into --dest")
    b.add_argument("--in", dest="infile",
                   help="draft contrasts TSV (or a differentialabundance-style CSV with "
                        f"';' blocking) with columns {','.join(REQUIRED_COLS)}[,blocking][,id]; "
                        "never modified")
    b.add_argument("--contrast", dest="specs", action="append", default=[],
                   help="one contrast as key=value pairs, e.g. "
                        "'variable=condition,reference=control,target=treated,"
                        "blocking=sex+donor' (repeatable; alternative to --in)")
    b.add_argument("--metadata", help="per-sample metadata TSV to check the columns and levels "
                                      "against")
    b.add_argument("--rebuild-ids", action="store_true",
                   help="regenerate every id to the house convention, replacing ids that "
                        "are safe but non-canonical")
    b.add_argument("--dest", default=".", help="output directory (default: .)")
    b.add_argument("--out-name", default=OUT_NAME, help=f"output filename (default: {OUT_NAME})")
    b.set_defaults(func=cmd_build)

    c = sub.add_parser("check", help="validate an existing contrasts sheet (exit 1 on error)")
    c.add_argument("--diffgenes_contrasts", "--diffgenes-contrasts", "--contrasts",
                   dest="diffgenes_contrasts", required=True,
                   help="path to the contrasts TSV")
    c.add_argument("--metadata", help="per-sample metadata TSV to check the columns and levels "
                                      "against")
    c.set_defaults(func=cmd_check)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
