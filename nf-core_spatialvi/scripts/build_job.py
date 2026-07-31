#!/usr/bin/env python3
"""Build a SLURM job script + params.yml for an nf-core-style pipeline run.

House-style engine (see repo DESIGN.md). Self-contained per skill: each skill's
scripts/ holds its own copy. Per-skill differences live in the CONFIG block below;
the logic underneath is identical across skills.

Stdlib + pyyaml only. No network calls: everything is read from the skill's
assets/ (schema, config lists) and templates/, plus the shared cluster reference
map at <repo-root>/assets/genomes.json (DESIGN.md 2).
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
    "pipeline_id": "nf-core:spatialvi",
    # entry name -> template / params file / required-input schema key.
    # "" is the single-entry case (no -entry flag).
    "entries": {
        "": {
            "template": "run_nfcore_spatialvi.sh",
            "params_file": "params.yml",
            "input_flag": "input",
            "input_var": "samplesheet",  # bash variable in the template holding the input path
        },
    },
    # param -> assets JSON file for advisory free-text value lists (warn, not error).
    "value_lists": {},
    # schema param -> genomes.json key; filled from --species (mouse/human), overridable via --set.
    "species_map": {},
}

# --------------------------------------------------------------------------- #
# Paths (resolved relative to this script: <skill>/scripts/build_job.py)
# --------------------------------------------------------------------------- #
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
ASSETS_DIR = os.path.join(SKILL_DIR, "assets")
TEMPLATES_DIR = os.path.join(SKILL_DIR, "templates")
# Cluster reference data shared by every skill. Not pipeline-version pinned, so it lives once
# at the repo root instead of being duplicated per skill (DESIGN.md §2).
SHARED_ASSETS_DIR = os.path.join(os.path.dirname(SKILL_DIR), "assets")


def die(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    sys.exit(f"ERROR: {msg}")


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Species -> reference files (auto-mapped by --species; override any path with --set)
# --------------------------------------------------------------------------- #
def load_genomes() -> tuple:
    """Return (genomes, species_aliases) from the shared <repo-root>/assets/genomes.json.

    Adding a species or bumping a reference release is an edit to that file alone — no
    parameter names or paths are hard-coded here. Only called when the skill's CONFIG
    declares a species_map, so skills without one need no genomes.json.
    """
    path = os.path.join(SHARED_ASSETS_DIR, "genomes.json")
    if not os.path.isfile(path):
        die(f"missing shared reference map: {path}\n"
            f"       it belongs at the repo root, alongside the skill folders (DESIGN.md §2)")
    try:
        data = json.load(open(path))
    except ValueError as exc:
        die(f"{path} is not valid JSON: {exc}")
    genomes, aliases = data.get("genomes"), data.get("species_aliases", {})
    if not isinstance(genomes, dict) or not genomes:
        die(f"{path}: 'genomes' must be a non-empty object")
    if not isinstance(aliases, dict):
        die(f"{path}: 'species_aliases' must be an object")
    return genomes, {str(k).strip().lower(): v for k, v in aliases.items()}


def detect_species(path, aliases: dict):
    """Infer a genomes.json species key from a metadata/samplesheet TSV or CSV.

    Looks for a species/organism column and maps its value(s) via the species_aliases map
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
                key = aliases.get(row[i].strip().lower())
                if key:
                    found.add(key)
    if len(found) == 1:
        return next(iter(found))
    if len(found) > 1:
        warn(f"multiple species in {os.path.basename(path)}: {sorted(found)}; not auto-selecting")
    return None


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
        mm = re.match(r"\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*$", line)
        if not mm:
            continue
        raw = mm.group(2).strip()
        # A quoted value is taken whole: '//' inside it is part of the value (URLs, s3://),
        # not a trailing comment. Only an unquoted value can carry a '// ...' comment.
        quoted = re.match(r"""^(['"])(.*?)\1""", raw)
        raw = quoted.group(2) if quoted else re.sub(r"//.*$", "", raw).strip()
        defaults[mm.group(1)] = raw
    return defaults


def strip_defaults(params: dict, schema: dict) -> dict:
    """Drop entries whose value equals the effective runtime default.

    The effective default is the nextflow.config value, because that is what Nextflow actually
    applies at runtime. A schema `default` is documentation only: nf-validation does not inject
    it into params. So a param absent from nextflow.config has NO runtime default, and a value
    supplied for it must never be stripped — dropping it would substitute null for the value.
    """
    cfg = config_defaults()
    norm = lambda x: str(x).strip().lower()
    out = {}
    for key, val in params.items():
        if key in cfg and norm(val) == norm(cfg[key]):
            continue  # equals what Nextflow applies at runtime -> redundant
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
# Assay variants (CONFIG["variants"]; absent in skills without assay-specific defaults)
# --------------------------------------------------------------------------- #
def resolve_variant(args, overrides: dict, variants: dict):
    """Return the effective value of the variant param (e.g. study_type), or None.

    Precedence: the dedicated flag (--study-type) -> --set study_type=... -> the
    nextflow.config default. Giving both spellings with different values is an error.
    """
    param = variants["param"]
    flagged = getattr(args, "variant", None)
    from_set = overrides.get(param)
    if flagged and from_set is not None and str(from_set) != str(flagged):
        die(f"--{param.replace('_', '-')}={flagged} conflicts with --set {param}={from_set}; "
            f"give only one")
    value = flagged or from_set
    if value is None:
        value = config_defaults().get(param)
    return str(value) if value is not None else None


def variant_overlay(value: str, variants: dict):
    """Return (overlay_params, overlay_filename) for a variant value; ({}, None) if none."""
    pattern = variants.get("params_file_pattern")
    if not (pattern and value):
        return {}, None
    name = pattern.format(value=value)
    if not os.path.isfile(os.path.join(TEMPLATES_DIR, name)):
        return {}, None
    return load_recommended(name), name


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    entries = CONFIG["entries"]
    variants = CONFIG.get("variants") or {}
    variant_param = variants.get("param")
    # Loaded before the parser so --species / the variant flag can take their choices from them.
    schema = load_schema()
    genomes, species_aliases = load_genomes() if CONFIG.get("species_map") else ({}, {})

    ap = argparse.ArgumentParser(description=f"Build a {CONFIG['pipeline_id']} job.")
    if list(entries) != [""]:
        ap.add_argument("--entry", required=True, choices=sorted(entries),
                        help="pipeline entry point")
    if variant_param:
        pattern = variants.get("params_file_pattern", "")
        ap.add_argument(f"--{variant_param.replace('_', '-')}", dest="variant",
                        choices=schema.get(variant_param, {}).get("enum"),
                        help=f"{variant_param} for this run; also applies the matching "
                             f"templates/{pattern.format(value='<value>')} overlay of recommended "
                             f"values and any variant-specific species files, when they exist")
    if CONFIG.get("species_map"):
        ap.add_argument("--species", choices=sorted(genomes),
                        help="fill species-dependent params (genome fasta/gtf, gene sets, or the "
                             "'species' param) from assets/genomes.json; override any with --set")
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

    # base recommendations -> variant overlay -> species-mapped files -> user --set overrides
    overrides = parse_overrides(args.sets)
    params = load_recommended(spec["params_file"])
    recommended_keys = set(params)

    overlay_file = None
    variant_value = resolve_variant(args, overrides, variants) if variant_param else None
    if variant_value:
        overlay, overlay_file = variant_overlay(variant_value, variants)
        params.update(overlay)
        recommended_keys |= set(overlay)
        params[variant_param] = variant_value

    species_map = dict(CONFIG.get("species_map", {}))
    if variant_value:
        species_map.update((variants.get("species_map") or {}).get(variant_value, {}))
    species = getattr(args, "species", None)
    if not species and species_map:
        for src in filter(None, (getattr(args, "metadata", None), args.input)):
            detected = detect_species(src, species_aliases)
            if detected:
                species = detected
                print(f"  species inferred from {os.path.basename(src)}: {species}")
                break
    if species and species_map:
        for param_key, genome_key in species_map.items():
            if genome_key not in genomes[species]:
                die(f"assets/genomes.json: species '{species}' has no '{genome_key}' entry "
                    f"(needed for param '{param_key}')")
            params[param_key] = genomes[species][genome_key]
    params.update(overrides)  # --set wins over recommended + variant + species

    # A species-dependent param left unset would silently run against the wrong reference.
    unresolved = sorted(k for k in species_map if k not in params)
    if unresolved:
        die(f"could not resolve a species, so {', '.join(unresolved)} would be left unset; "
            f"pass --species {'|'.join(sorted(genomes))}, add a species/organism column to the "
            f"samplesheet, or set them explicitly with --set")

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
    if variant_value:
        print(f"{variant_param:<9}: {variant_value}" +
              (f"  (overlay: templates/{overlay_file})" if overlay_file else ""))
    if species:
        print(f"species  : {species}  ({', '.join(sorted(species_map))})")
    print(f"params   : {params_out}  ({len(params)} non-default value(s))")
    if recommended_keys:
        print(f"  recommended applied (override with --set): {', '.join(sorted(recommended_keys))}")
    print(f"job      : {script_out}")
    if custom_out:
        print(f"custom   : {custom_out}  (add '-c custom.config' to the run command)")


if __name__ == "__main__":
    main()
