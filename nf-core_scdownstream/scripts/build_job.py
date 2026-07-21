#!/usr/bin/env python3
"""Build a SLURM job script + params.yml for an nf-core-style pipeline run.

House-style engine (see repo DESIGN.md). Self-contained per skill: each skill's
scripts/ holds its own copy. Per-skill differences live in the CONFIG block below;
the logic underneath is identical across skills.

Stdlib + pyyaml only. No network calls: everything is read from the skill's
assets/ (schema, config lists) and templates/.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import yaml

# --------------------------------------------------------------------------- #
# Per-skill configuration (the ONLY part that differs between skills)
# --------------------------------------------------------------------------- #
CONFIG = {
    "pipeline_id": "nf-core:scdownstream",
    # entry name -> template / params file / required-input schema key.
    # "" is the single-entry case (no -entry flag).
    "entries": {
        "qc_clustering": {
            "template": "run_nfcore_scdownstream_qc_clustering.sh",
            "params_file": "params_qc_clustering.yml",
            "input_flag": "input",
            "input_var": "samplesheet",  # bash variable in the template holding the input path
        },
        "downstream": {
            "template": "run_nfcore_scdownstream_downstream.sh",
            "params_file": "params_downstream.yml",
            "input_flag": "base_adata",
            "input_var": "h5adf",  # bash variable in the template holding the input path
        },
    },
    # param -> assets JSON file for advisory free-text value lists (warn, not error).
    "value_lists": {"celltypist_model": "celltypist_models.json"},
    # schema param -> GENOMES key; filled from --species (mouse/human), overridable via --set.
    "species_map": {'species': 'species'},
}

# --------------------------------------------------------------------------- #
# Paths (resolved relative to this script: <skill>/scripts/build_job.py)
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Species -> reference files (auto-mapped by --species; override any path with --set)
# --------------------------------------------------------------------------- #
GENOMES = {
    "human": {
        "species": "human",
        "fasta": "/nfsdata/genome/ucsc/hg38/hg38.fa.gz",
        "gtf": "/nfsdata/genome/ensembl/release-115/GRCh38/chrHomo_sapiens.GRCh38.115.chr.gtf.gz",
    },
    "mouse": {
        "species": "mouse",
        "fasta": "/nfsdata/genome/ucsc/mm39/mm39.fa.gz",
        "gtf": "/nfsdata/genome/ensembl/release-115/GRCm39/chrMus_musculus.GRCm39.115.chr.gtf.gz",
    },
}

# Scientific / common names -> GENOMES species key (used to infer --species from metadata).
SPECIES_ALIASES = {
    "mus musculus": "mouse", "mouse": "mouse",
    "homo sapiens": "human", "human": "human",
}


def detect_species(path):
    """Infer a GENOMES species key from a metadata/samplesheet TSV or CSV.

    Looks for a species/organism column and maps its value(s) via SPECIES_ALIASES
    (e.g. 'Mus musculus' -> 'mouse'). Returns the species if exactly one is found,
    else None (a mix warns and returns None). Non-tabular inputs (e.g. .h5ad) are ignored.
    """
    import csv
    if not path or not os.path.isfile(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".csv", ".tsv", ".txt"):
        return None
    delim = "," if ext == ".csv" else "\t"
    try:
        with open(path, newline="") as fh:
            rows = list(csv.reader(fh, delimiter=delim))
    except Exception:
        return None
    if not rows:
        return None
    header = [h.strip().lower() for h in rows[0]]
    cols = [i for i, h in enumerate(header)
            if h in ("species", "organism", "organism_name", "scientific_name",
                     "characteristics[organism]")]
    if not cols:
        return None
    found = set()
    for row in rows[1:]:
        for i in cols:
            if i < len(row):
                key = SPECIES_ALIASES.get(row[i].strip().lower())
                if key:
                    found.add(key)
    if len(found) == 1:
        return next(iter(found))
    if len(found) > 1:
        warn(f"multiple species in {os.path.basename(path)}: {sorted(found)}; not auto-selecting")
    return None


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
ASSETS_DIR = os.path.join(SKILL_DIR, "assets")
TEMPLATES_DIR = os.path.join(SKILL_DIR, "templates")


def die(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    sys.exit(f"ERROR: {msg}")


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Schema (the authoritative parameter source: keys, enums, defaults)
# --------------------------------------------------------------------------- #
def load_schema() -> dict:
    """Return {param_name: property_dict} flattened across the schema's groups."""
    path = os.path.join(ASSETS_DIR, "nextflow_schema.json")
    if not os.path.isfile(path):
        die(f"missing schema: {path}")
    schema = json.load(open(path))
    props: dict = {}
    for container in ("$defs", "definitions"):
        for group in schema.get(container, {}).values():
            props.update(group.get("properties", {}))
    props.update(schema.get("properties", {}))
    if not props:
        die(f"no parameters found in {path}")
    return props


def validate_params(params: dict, schema: dict, value_lists: dict) -> None:
    """Hard-error on unknown keys and out-of-enum values; warn on value-list misses."""
    unknown = sorted(k for k in params if k not in schema)
    if unknown:
        die("unknown parameter(s) not in nextflow_schema.json: " + ", ".join(unknown))
    for key, val in params.items():
        enum = schema[key].get("enum")
        if enum is not None and val not in enum and str(val) not in [str(e) for e in enum]:
            die(f"invalid value for '{key}': {val!r} — allowed: {enum}")
    for key, list_file in value_lists.items():
        if key in params:
            check_value_list(key, str(params[key]), list_file)


def check_value_list(key: str, value: str, list_file: str) -> None:
    """Advisory check of a free-text value against a stored list (warn, never error).

    A value containing a path separator is treated as a custom file path and accepted.
    Otherwise it is matched (ignoring a trailing .pkl) against the list's names.
    """
    if "/" in value:
        return  # custom file path
    path = os.path.join(ASSETS_DIR, list_file)
    if not os.path.isfile(path):
        warn(f"value list {list_file} missing; cannot check '{key}'")
        return
    data = json.load(open(path))
    names = [m.get("filename", "") for m in data.get("models", [])]
    norm = lambda s: s[:-4] if s.endswith(".pkl") else s
    if norm(value) not in [norm(n) for n in names]:
        warn(f"'{key}' = {value!r} not in {list_file}; "
             f"if this is a custom model, give a file path instead.")


def config_defaults() -> dict:
    """Best-effort {param: default} from the params{} scope of assets/nextflow.config.

    Nextflow applies these at runtime, so they — not the schema defaults, which can diverge —
    determine what a run actually uses. Used only to decide whether a value is non-default (§5).
    """
    import re
    path = os.path.join(ASSETS_DIR, "nextflow.config")
    defaults = {}
    if not os.path.isfile(path):
        return defaults
    text = open(path).read()
    m = re.search(r"params\s*\{", text)
    if not m:
        return defaults
    i, depth, start = m.end(), 1, m.end()
    while i < len(text) and depth:
        depth += (text[i] == "{") - (text[i] == "}")
        i += 1
    block = text[start:i - 1]
    for line in block.splitlines():
        mm = re.match(r"\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*(?://.*)?$", line)
        if not mm:
            continue
        raw = mm.group(2).strip()
        if len(raw) >= 2 and raw[0] in "'\"" and raw[-1] == raw[0]:
            raw = raw[1:-1]
        defaults[mm.group(1)] = raw
    return defaults


def strip_defaults(params: dict, schema: dict) -> dict:
    """Drop entries whose value equals the effective runtime default.

    Effective default = the nextflow.config value if the param is set there (what Nextflow uses
    at runtime), else the schema default. Schema and config defaults can diverge, so comparing
    against the config value avoids silently dropping a value the run actually needs.
    """
    cfg = config_defaults()
    norm = lambda x: str(x).strip().lower()
    sentinel = object()
    out = {}
    for key, val in params.items():
        default = cfg[key] if key in cfg else schema.get(key, {}).get("default", sentinel)
        if default is not sentinel and norm(val) == norm(default):
            continue
        out[key] = val
    return out


# --------------------------------------------------------------------------- #
# params.yml
# --------------------------------------------------------------------------- #
def load_recommended(params_file: str) -> dict:
    """Load the shipped templates/<params_file> (recommended non-default values)."""
    path = os.path.join(TEMPLATES_DIR, params_file)
    if not os.path.isfile(path):
        return {}
    return yaml.safe_load(open(path)) or {}


def parse_overrides(pairs: list) -> dict:
    out = {}
    for p in pairs or []:
        if "=" not in p:
            die(f"--set expects key=value, got {p!r}")
        k, v = p.split("=", 1)
        out[k.strip()] = yaml.safe_load(v)  # coerce true/false/int/float where possible
    return out


def write_params(params: dict, dest_file: str) -> str:
    with open(dest_file, "w") as fh:
        yaml.safe_dump(params, fh, default_flow_style=False, sort_keys=True)
    return dest_file


# --------------------------------------------------------------------------- #
# SLURM template + optional custom.config
# --------------------------------------------------------------------------- #
def fill_template(template: str, dest_file: str, var_values: dict) -> str:
    """Rewrite whole `var=...` assignment lines in the template with the given values.

    Replacing the entire assignment (rather than an embedded token) avoids double-prefix
    bugs and keeps the template's own default hint intact for anyone hand-editing it.
    """
    import re
    path = os.path.join(TEMPLATES_DIR, template)
    if not os.path.isfile(path):
        die(f"missing template: {path}")
    text = open(path).read()
    for var, value in var_values.items():
        pat = re.compile(rf"^(\s*){re.escape(var)}=.*$", re.MULTILINE)
        if not pat.search(text):
            warn(f"template {template} has no '{var}=' line to fill")
        text = pat.sub(lambda m: f"{m.group(1)}{var}={value}", text, count=1)
    with open(dest_file, "w") as fh:
        fh.write(text)
    return dest_file


def base_config_selectors() -> set:
    """withLabel/withName selectors declared in assets/base.config."""
    path = os.path.join(ASSETS_DIR, "base.config")
    sels = set()
    if os.path.isfile(path):
        import re
        for m in re.finditer(r"with(?:Label|Name):\s*'?([A-Za-z0-9_:.*]+)'?", open(path).read()):
            sels.add(m.group(1))
    return sels


def gen_custom_config(resources: list, dest_file: str) -> str:
    """resources: list of 'selector:key=value'. Emits a Groovy process{} override file."""
    selectors = base_config_selectors()
    blocks = {}
    for spec in resources:
        try:
            selector, kv = spec.split(":", 1)
            key, value = kv.split("=", 1)
        except ValueError:
            die(f"--resource expects selector:key=value, got {spec!r}")
        if selectors and selector not in selectors:
            warn(f"selector '{selector}' not found in base.config withLabel/withName set")
        blocks.setdefault(selector, []).append((key.strip(), value.strip()))
    lines = ["// custom.config — process-resource overrides (generated)", "process {"]
    for selector, kvs in blocks.items():
        kind = "withName" if selector.isupper() or "_" in selector and selector[0].isupper() else "withLabel"
        lines.append(f"    {kind}: '{selector}' {{")
        for k, v in kvs:
            lines.append(f"        {k} = {v}")
        lines.append("    }")
    lines.append("}")
    with open(dest_file, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return dest_file


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    entries = CONFIG["entries"]
    ap = argparse.ArgumentParser(description=f"Build a {CONFIG['pipeline_id']} job.")
    if list(entries) != [""]:
        ap.add_argument("--entry", required=True, choices=sorted(entries),
                        help="pipeline entry point")
    if CONFIG.get("species_map"):
        ap.add_argument("--species", choices=sorted(GENOMES),
                        help="fill species-dependent params (genome fasta/gtf, or the 'species' "
                             "param) from the built-in mouse/human map; override any with --set")
        ap.add_argument("--metadata", help="TSV/CSV (metadata or samplesheet) to infer --species "
                                           "from a species/organism column when --species is omitted")
    ap.add_argument("--input", required=True, help="path to the required input (samplesheet / h5ad / SDRF)")
    ap.add_argument("--resdir", required=True, help="results directory")
    ap.add_argument("--main", help="override the pinned main.nf path in the SLURM template")
    ap.add_argument("--set", dest="sets", action="append", default=[],
                    help="override/add a param: key=value (repeatable)")
    ap.add_argument("--resource", dest="resources", action="append", default=[],
                    help="custom-config resource override: 'selector:key=value' (repeatable)")
    ap.add_argument("--dest", default=".", help="output directory for the generated files")
    args = ap.parse_args()

    entry = getattr(args, "entry", "") if list(entries) != [""] else ""
    spec = entries[entry]
    os.makedirs(args.dest, exist_ok=True)

    schema = load_schema()

    # recommended defaults -> species-mapped files -> user --set overrides
    params = load_recommended(spec["params_file"])
    recommended_keys = sorted(params)
    species_map = CONFIG.get("species_map", {})
    species = getattr(args, "species", None)
    if not species and species_map:
        for src in filter(None, (getattr(args, "metadata", None), args.input)):
            detected = detect_species(src)
            if detected:
                species = detected
                print(f"  species inferred from {os.path.basename(src)}: {species}")
                break
    if species and species_map:
        for param_key, genome_key in species_map.items():
            params[param_key] = GENOMES[species][genome_key]
    params.update(parse_overrides(args.sets))  # --set wins over recommended + species
    validate_params(params, schema, CONFIG["value_lists"])
    params = strip_defaults(params, schema)

    params_out = os.path.join(args.dest, spec["params_file"])
    write_params(params, params_out)

    # fill the SLURM template (rewrite the input-path, resdir, and optional main.nf lines)
    script_out = os.path.join(args.dest, spec["template"])
    subs = {spec["input_var"]: args.input, "resdir": args.resdir}
    if getattr(args, "main", None):
        subs["main"] = args.main
    fill_template(spec["template"], script_out, subs)

    # optional custom.config
    custom_out = None
    if args.resources:
        custom_out = gen_custom_config(args.resources, os.path.join(args.dest, "custom.config"))

    # report
    print(f"pipeline : {CONFIG['pipeline_id']}" + (f"  (entry: {entry})" if entry else ""))
    print(f"params   : {params_out}  ({len(params)} non-default value(s))")
    if recommended_keys:
        print(f"  recommended applied (override with --set): {', '.join(recommended_keys)}")
    print(f"job      : {script_out}")
    if custom_out:
        print(f"custom   : {custom_out}  (add '-c custom.config' to the run command)")


if __name__ == "__main__":
    main()
