# DESIGN.md — House Style for `informatics_pipeline_skills`

---

## 1. Purpose & scope

`informatics_pipeline_skills` is a collection of Claude Code **skills**, one per Nextflow
nf-core-style pipeline. Each skill helps a user assemble the artifacts needed to run one pipeline
job on the SLURM cluster:

- a **SLURM job bash script** (an edited copy of the pipeline's template),
- a **`params.yml`** file capturing the pipeline parameters that differ from defaults, and
- *optionally*, a **custom process-resource config** (`-c custom.config`, §4.6) when the run needs
  non-default CPUs/memory/time.

**The repository never runs a pipeline.** It only *generates* these artifacts. Execution happens
later, by the user, on the cluster via `sbatch`.

Pipelines covered:

- `nf-core:rnaseq`
- `nf-core:scrnaseq`
- `nf-core:differentialabundance` *(substantially modified from upstream — see §8)*
- `bigbio:quantmsdiann`
- `nf-core:spatialvi`
- `nf-core:scdownstream` *(substantially modified from upstream — see §8)*

**Audience of this document:** Claude, when authoring or maintaining a skill or its API scripts.

---

## 2. Repository & skill folder layout

Each pipeline lives in its own top-level folder. The folder name is the pipeline id with the
colon replaced by an underscore (see the table in §8).

Canonical per-skill structure:

```
<pipeline_folder>/
├── SKILL.md                 # skill definition (frontmatter + instructions)
├── assets/
│   ├── nextflow_schema.json # pinned copy; authoritative param list — valid keys, value enums, defaults (§5, §7)
│   ├── nextflow.config      # pinned copy; runtime config / defaults reference
│   └── base.config          # pinned copy of conf/base.config; default process-resource reference (§4.6)
├── templates/
│   ├── run_<pipeline>.sh    # SLURM job bash template
│   └── params.yml           # recommended/example params, pre-filled (§5)
└── scripts/
    └── *.py                 # Python API for this skill
```

Repo root additionally holds `DESIGN.md` (this file), `CLAUDE.md`, and `LICENSE`.

Rules:

- **`assets/`** holds reference/validation files that are *read, never copied per-run*. The files
  below are **pinned to the same pipeline version/branch as the `main.nf` in `run_<pipeline>.sh`**;
  any pipeline-specific asset (last bullet) carries its own provenance:
  - `nextflow_schema.json` — verbatim copy from the pipeline repo; the **authoritative parameter
    source** used for validation: the complete set of valid keys, their value enums, and their
    defaults (see §5 and §7).
  - `nextflow.config` — verbatim copy from the pipeline repo; kept as the runtime-config / defaults
    reference (it defaults only a subset of params, so it is *not* the validation source).
  - `base.config` — verbatim copy of the repo's `conf/base.config`; the reference for default
    per-process resources and the available `withName`/`withLabel` selectors used when writing an
    optional custom config (see §4.6 and §7).
  - A skill may add **pipeline-specific validation assets** here too. For example, scdownstream
    stores `celltypist_models.json` (the CellTypist model list) to validate its `celltypist_model`
    value offline (see §5, §7, §8).
- **`templates/`** holds files that are *copied and edited* per run — never mutated in place.
  A single-entry pipeline has one `run_<pipeline>.sh` + `params.yml`; a pipeline with multiple
  `-entry` workflows has one `run_<folder>_<entry>.sh` **and** one `params_<entry>.yml` per entry
  point (see §4.7 and §8).
- **`scripts/`** holds the Python API for that skill (see §7). Even if a script is generic, each
  skill keeps its own copy so skills stay self-contained.
- The seeded example `nf-core_rnaseq/templates/run_nfcore_rnaseq.sh` is the reference template
  that all conventions in §4 are derived from.

---

## 3. SKILL.md anatomy

Every skill folder contains a `SKILL.md` with YAML frontmatter followed by instructions.

**Frontmatter (required):**

```yaml
---
name: <pipeline-folder-name>            # e.g. nf-core_rnaseq
description: >-
  One-paragraph summary of what the skill does, with explicit trigger keywords
  (pipeline name, aliases, "samplesheet", "params.yml", "slurm", ...).
---
```

**Standard section order in the body:**

1. **Purpose** — what this skill produces (a `run_*.sh` + `params.yml` for this pipeline).
2. **Required inputs** — the `samplesheet.csv` and its expected columns for *this* pipeline
   (see §6), plus any genome/reference inputs.
3. **Gather parameters** — how to elicit the user's non-default choices.
4. **Generate `params.yml`** — invoke the skill's Python script (§7) to emit `params.yml`, seeded
   with the pipeline's **recommended non-default values** (§5) applied by default and reported to
   the user (who may override), plus *optionally* a custom process-resource config (§4.6) if the
   user wants non-default resources.
5. **Fill the SLURM template** — copy `templates/run_<pipeline>.sh`, replace placeholders (§4), and
   add `-c custom.config` only if one was generated.
6. **Hand back** — tell the user the final file paths and how to submit (`sbatch run_<pipeline>.sh`).

**Convention:** a skill always **edits a copy** of the template into the user's working area; it
does not modify the file under `templates/`.

`SKILL.md` also records any pipeline-specific **custom-config recommendations** (§4.6) as prose —
e.g. resource-scaling rules keyed to dataset size. The flow: SKILL.md states the trigger and value,
the user opts in, and the Python API (§7) generates the `custom.config` and wires `-c`.

---

## 4. SLURM job script conventions

Derived directly from `nf-core_rnaseq/templates/run_nfcore_rnaseq.sh`. Every pipeline's
`run_<pipeline>.sh` follows this shape.

### 4.1 Header (`#SBATCH` directives)

```bash
#!/bin/bash
#
#SBATCH --job-name=<pipeline:id>      # e.g. nf-core:rnaseq
#SBATCH --partition=htc               # cluster partition/queue
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=1
#SBATCH --time=72:00:00               # D-HH:MM:SS
set -e
set -o pipefail
```

- `--job-name` = the pipeline id (with the colon, e.g. `nf-core:rnaseq`).
- `--partition` defaults to `htc`.
- User-tunable directives: `--time`, `--cpus-per-task`, `--partition`. The rest stay fixed.
- Optional directives may be added when useful, e.g. `#SBATCH --mail-type=END`.
- Always keep `set -e` and `set -o pipefail`.

### 4.2 Parameters block

```bash
# parameters
exec=/nfsdata/bin/nextflow-<version>-dist
main=/nfsdata/scripts/nf-core/<pipeline-dir>/<ver>/main.nf
```

- `exec` — pinned path to the Nextflow distribution.
- `main` — pinned path to the pipeline's `main.nf`. The version is explicit — a release tag, or a
  `dev` build for in-development pipelines (e.g. scdownstream, spatialvi) — never a floating "latest".
  For dev builds, the exact source commit is recorded in the §5 provenance table. The template ships
  the pinned default; a user can point at a different checkout with `build_job.py --main /path/main.nf`
  (§7), which rewrites this line.

### 4.3 Paths & placeholders

User-edited paths use **UPPERCASE placeholder tokens** so they are obvious to replace:

```bash
# CREATE AND CHANGE PATH TO SAMPLESHEET
samplesheet=/nfsdata/${USER}/PATH_TO_SAMPLE_SHEET
# CHANGE RESULTS_DIR to your folder on /data
resdir=/data/${USER}/RESULTS_DIR
outdir=$resdir/out
```

Use the mkdir-guard idiom for both `$resdir` and `$outdir`:

```bash
if [ ! -d $resdir ]; then
        mkdir -p $resdir
        echo "Created '$resdir'."
fi
```

### 4.4 Environment exports

```bash
# singularity / apptainer cache
export NXF_SINGULARITY_CACHEDIR=/nfsdata/apptainer
export NXF_APPTAINER_CACHEDIR=/nfsdata/apptainer
```

### 4.5 The `nextflow run` invocation — the key convention

CLI flags on the job script are **limited to run-level flags** — the profile, the required input,
the output dir, the params file, the report, and `-resume` (plus optional `-c` §4.6 / `-entry`
§4.7). **Every pipeline parameter that differs from the pipeline's default goes into `params.yml`,
never as a CLI flag.**

```bash
echo "Running nextflow..."
$exec run $main \
   -profile apptainer \
   --input $samplesheet \
   --outdir $outdir \
   -params-file params.yml \
   -with-report \
   -resume
#  -c custom.config \        # OPTIONAL: process-resource overrides (§4.6)
echo "Done."
```

Allowed on the command line (and only these, plus the optional `-c`, §4.6, and `-entry`, §4.7):

- `-profile <profiles>` — e.g. `apptainer`, or `apptainer,gpu`
- the pipeline's **required input flag** — usually `--input` (the samplesheet), but entry/pipeline-
  specific (e.g. `--base_adata` for scdownstream's `downstream` entry, §4.7)
- `--outdir`
- `-params-file params.yml` (or `params_<entry>.yml` for multi-entry pipelines, §4.7)
- `-with-report` *(optionally with a file path, e.g. `-with-report $resdir/nextflow_report.html`)*
- `-resume`
- `-c custom.config` *(optional; see §4.6 — omit when not tuning resources)*
- `-entry <name>` *(only for pipelines with multiple entry-point workflows; see §4.7)*

Anything else (genome, gtf, aligner, protocol, feature flags, …) belongs in `params.yml` (§5).

### 4.6 Optional custom process-resource config (`-c`)

**Optional — omit entirely when the pipeline's default resources are fine; it is not part of every
job script.** Use it to tune *process execution resources* (CPUs, memory, wall-time) and other
process/executor directives without touching the pipeline itself.

- Invoke by adding **`-c custom.config`** to the `nextflow run` command (§4.5). `-c` **appends and
  overrides only the specific parts** it declares — it does **not** replace the whole configuration
  (that would be `-C`). Multiple `-c` files may be given; later ones win.
- Contents are Groovy in the `process` scope — **resource directives, not pipeline parameters**
  (parameters always stay in `params.yml`, §5):

  ```groovy
  // custom.config — override resources for specific processes / labels
  process {
      withName: 'STAR_ALIGN' {
          cpus   = 16
          memory = 64.GB
          time   = 24.h
      }
      withLabel: 'process_high' {
          cpus = 24
      }
  }
  ```

- **Where the defaults come from:** each pipeline's `assets/base.config` (a copy of the repo's
  `conf/base.config`) lists the default per-process resources and the valid `withName`/`withLabel`
  selectors — start from there when deciding what to override.
- **Layer distinction (important):** the `#SBATCH` header (§4.1) sizes the **Nextflow head/driver
  job** that orchestrates the run; a `-c` config sizes the **individual per-process cluster jobs
  Nextflow submits**. They are different layers — editing one does not change the other.
- The file is generated on demand by the skill's Python API (§7); there is no committed template.
- **Recommendations live in `SKILL.md` (prose).** *When* to add a custom config and *what* to
  override are advisory, human-authored guidance written in the pipeline's `SKILL.md` (§3) — not
  auto-derived by the API. For example, scdownstream's `SKILL.md` states that when a single-cell
  dataset exceeds **250,000 cells**, processes should be given an increased memory limit:

  ```groovy
  // custom.config — scdownstream, large dataset (> 250,000 cells)
  process {
      memory = { 225.GB }
  }
  ```

### 4.7 Multiple entry points (`-entry`)

Some pipelines expose more than one workflow, selected with Nextflow's `-entry <name>`. These are
**distinct, often sequential stages** with different inputs and parameter sets — not interchangeable
modes.

- **One template per entry point** — do **not** consolidate them into a single branching script.
  Each stays a simple, linear, hand-editable copy (§3), named `run_<folder>_<entry>.sh` (§8) with
  its own `params_<entry>.yml` (§5).
- Place **`-entry <name>` first**, right after `run $main`.
- The **required input flag is entry-specific** — it is whatever that entry consumes, not always
  `--input`.
- Everything else follows §4.5/§5 unchanged: only the allowed flags on the command line, all other
  non-default parameters in that entry's `params_<entry>.yml`.

**Worked example — `nf-core:scdownstream`** has two entry points that run in sequence:

| Entry | Required input | Produces / consumes |
|---|---|---|
| `qc_clustering` | `--input` (samplesheet.csv) | writes `…/out/integrated_scvi_finalized.h5ad` |
| `downstream` | `--base_adata` (that `.h5ad`) | downstream analysis on the qc_clustering output |

So `run_nfcore_scdownstream_qc_clustering.sh` is run first; its output h5ad becomes the
`--base_adata` input of `run_nfcore_scdownstream_downstream.sh`.

### 4.8 Finalize / cleanup

```bash
echo "Finalizing..."
cp *.sh $resdir/
cp *.out $resdir/
rm -rf work        # clean the Nextflow workdir
echo "ALL DONE."
```

---

## 5. `params.yml` conventions

- Contains **only** parameters whose value differs from the pipeline's default. Keep it minimal
  and auditable — a reader should see exactly what was customized.
- Each YAML key is the nf-core parameter name **without** the leading `--`; the value is the
  desired setting.
- Produced by the skill's Python script (§7) via `yaml.safe_dump`.
- For a pipeline with multiple `-entry` workflows (§4.7) there is **one params file per entry**,
  named `params_<entry>.yml`, each wired to its own job script's `-params-file`.
- **Dynamic but validated against the stored schema.** Parameter names are not hard-coded: the
  valid set, value enums, and defaults for a pipeline all come from that pipeline's stored
  `assets/nextflow_schema.json` (§2) — the authoritative, complete parameter list (unlike
  `nextflow.config`, which only defaults a subset and omits core params such as `fasta`/`gtf`).
  The Python script (§7):
  - **rejects any unknown key** with a hard error naming it, so `params.yml` can only contain real
    parameters of the pinned pipeline version;
  - **rejects an out-of-enum value** with a hard error for params the schema constrains (e.g.
    `aligner ∈ {star_salmon, star_rsem, hisat2, bowtie2_salmon}`);
  - keeps **only non-default values**, where the *effective default* is the `nextflow.config` value
    if the param is set there (what Nextflow actually applies at runtime), otherwise the schema
    default. Schema and config defaults can diverge (e.g. scdownstream `species`: schema `mouse`,
    config `human`), so comparing against the config value avoids silently dropping a needed value.
- **External value lists (advisory).** For a *free-text* value not expressible as a schema enum, a
  pipeline may check it against a stored reference list in `assets/`. Unlike the schema checks above
  (hard errors), this **warns but still writes** — the list is a refreshable snapshot and legitimate
  values (e.g. custom file paths) may not appear in it. Example: scdownstream's `celltypist_model`
  is checked against `assets/celltypist_models.json` (see §7, §8).
- Parameters for pipelines are defined in the pipeline's github repo: `nextflow.config` and `nextflow_schema.json`.
  The github repos are: https://github.com/nf-core/rnaseq, https://github.com/nf-core/scrnaseq, https://github.com/UKDRI/differentialabundance, https://github.com/UKDRI/scdownstream, https://github.com/nf-core/spatialvi/tree/dev, and https://github.com/bigbio/quantmsdiann
  Usage can be obtained from nf-core docs e.g. https://nf-co.re/rnaseq/3.26.0. For scdownstream and differentialabundance usage is explained at: https://wiki.informatics.ukdri.ac.uk/en/Pipelines/nfcore_scdownstream and https://wiki.informatics.ukdri.ac.uk/en/Pipelines/nfcore_differentialabundance


**Classification rule** — which side a parameter lands on:

| Parameter kind                                  | Where it goes            |
|-------------------------------------------------|--------------------------|
| Required input (`--input`, or entry-specific e.g. `--base_adata`) | CLI flag in `run_*.sh`   |
| Output dir (`--outdir`)                         | CLI flag in `run_*.sh`   |
| Nextflow run/report (`-profile`, `-with-report`, `-resume`, `-params-file`) | CLI flag in `run_*.sh` |
| **Any other param that differs from default**   | `params.yml`             |
| A param left at its pipeline default            | omitted entirely         |

**Worked example (rnaseq).** The seeded template passes `--fasta`, `--gtf`, and `--aligner` as
CLI flags. Under this convention they move into `params.yml`:

```yaml
# params.yml — nf-core:rnaseq
fasta: /nfsdata/genome/ucsc/mm39/mm39.fa.gz
gtf: /nfsdata/genome/ensembl/release-115/GRCm39/chrMus_musculus.GRCm39.115.chr.gtf.gz
aligner: star_rsem
```

…and the job script's invocation keeps only the flags listed in §4.5. (In the built rnaseq skill,
`aligner` is the shipped recommendation while `fasta`/`gtf` are filled from `--species` — see
"Species-based genome selection" below; the point of this example is the CLI-vs-`params.yml` split.)

### Recommended parameters

Each skill ships its `templates/params.yml` (or `params_<entry>.yml`) **pre-populated with the
pipeline's recommended non-default values** — UKDRI house recommendations that differ from the
pipeline defaults and generally give better results. The skill **applies them by default**, reports
them to the user, and lets the user override or remove any of them. Each recommended value is still
a normal `params.yml` entry: validated against `assets/nextflow_schema.json` and only present
because it differs from the default.

Current recommendations:

| Pipeline | Parameter | Pipeline default | Recommended |
|---|---|---|---|
| `nf-core:rnaseq` | `aligner` | `star_salmon` | `star_rsem` |
| `nf-core:scrnaseq` | `aligner` | `simpleaf` | `cellranger` |

Other pipelines have no house recommendation yet — add rows here as they are established.

### Species-based genome selection

Pipelines with species-dependent parameters (a genome `fasta`/`gtf`, or a `species` field) fill
those from a built-in species map, so the user picks a species instead of remembering file paths.
`build_job.py` exposes **`--species mouse|human`** for these skills; each skill's CONFIG
`species_map` declares which schema params it fills:

| Skill | filled from `--species` |
|---|---|
| `nf-core:rnaseq`, `nf-core:scrnaseq` | genome `fasta` + `gtf` |
| `nf-core:differentialabundance` | `gtf` |
| `nf-core:scdownstream` | the `species` field itself |

Reference files (dynamic — override any with `--set`):

| species | fasta | gtf |
|---|---|---|
| mouse | `/nfsdata/genome/ucsc/mm39/mm39.fa.gz` | `/nfsdata/genome/ensembl/release-115/GRCm39/chrMus_musculus.GRCm39.115.chr.gtf.gz` |
| human | `/nfsdata/genome/ucsc/hg38/hg38.fa.gz` | `/nfsdata/genome/ensembl/release-115/GRCh38/chrHomo_sapiens.GRCh38.115.chr.gtf.gz` |

**Inferring species.** When `--species` is omitted, the skill infers it from a species/organism
column in a metadata/samplesheet file — `--metadata file.tsv` if given, otherwise the `--input`
samplesheet (when tabular; a non-tabular input such as an `.h5ad` is ignored). Scientific names are
recognised (*Mus musculus* → mouse, *Homo sapiens* → human, plus the common names) via the
`SPECIES_ALIASES` map. A file mixing species auto-selects nothing (it warns); the user then passes
`--species` explicitly.

**Precedence.** Species is resolved as explicit `--species` → `--metadata` → `--input`; the resolved
species then fills the mapped params, and an explicit `--set` always wins over the filled value. A
user can supply custom paths (`--set fasta=/path --set gtf=/path`) instead of, or alongside, species
selection. The `GENOMES` and `SPECIES_ALIASES` maps are constants in each skill's `build_job.py`
(self-contained, §7).

`nf-core:spatialvi` is species-dependent too but uses a Space Ranger reference directory
(`spaceranger_reference`) with no house default paths yet — set it explicitly with
`--set spaceranger_reference=...` (see its SKILL.md). `bigbio:quantmsdiann` has no species/genome
parameter.

### Obtaining & refreshing the `assets/` configs

Both `assets/` files are downloaded verbatim from the pipeline repo at the raw URL for the **same
pinned version/branch**, e.g.:

```bash
curl -L https://raw.githubusercontent.com/nf-core/rnaseq/master/nextflow_schema.json \
     -o nf-core_rnaseq/assets/nextflow_schema.json
curl -L https://raw.githubusercontent.com/nf-core/rnaseq/master/nextflow.config \
     -o nf-core_rnaseq/assets/nextflow.config
curl -L https://raw.githubusercontent.com/nf-core/rnaseq/master/conf/base.config \
     -o nf-core_rnaseq/assets/base.config
```

`nextflow_schema.json` is the validation source — the script reads its parameter properties (keys,
enums, defaults) with stdlib `json` (§7). `nextflow.config` (Groovy) is kept as the runtime/defaults
reference, and `base.config` (the repo's `conf/base.config`) is the process-resource reference
(§4.6). All three are pinned to the ref below:

| Pipeline | Source (branch/tag) | Stored version | Pinned commit (dev-tracked) |
|---|---|---|---|
| nf-core:rnaseq | `nf-core/rnaseq` @ `master` | 3.26.0 | — (release) |
| nf-core:scrnaseq | `nf-core/scrnaseq` @ `master` | 4.2.0 | — (release) |
| nf-core:differentialabundance | `UKDRI/differentialabundance` @ `dev_ukdri` | 1.5.0 | `163d07f` |
| bigbio:quantmsdiann | `bigbio/quantmsdiann` @ `main` | 2.2.0 | — (release) |
| nf-core:spatialvi | `nf-core/spatialvi` @ `dev` | 1.0dev | `d0fd35d` |
| nf-core:scdownstream | `UKDRI/scdownstream` @ `dev_ukdri` | 0.0.1dev | `3009f37` |

**UKDRI forks** (`differentialabundance`, `scdownstream`) are tracked on their **`dev_ukdri`**
branch — the repo default; `master` there is stale/not a normal branch and must not be used.

**Re-download all three files whenever a pipeline version is bumped** (i.e. when the `main.nf` pin
in `run_<pipeline>.sh` changes) so the validation source and references stay in sync with what
actually runs. For any **dev-tracked source** — a moving branch (`dev`, `dev_ukdri`) or a version
ending in `dev` — also **record the exact commit** the stored files came from in the table above and
update it on every refresh, since the branch moves and the version string alone is not a pin.

Pipeline-specific validation assets are fetched from their own source, independently of pipeline
version bumps — e.g. scdownstream's CellTypist model list (source: <https://www.celltypist.org/models>):

```bash
curl -L https://celltypist.cog.sanger.ac.uk/models/models.json \
     -o nf-core_scdownstream/assets/celltypist_models.json
```

---

## 6. Input / samplesheet conventions

- A `samplesheet.csv` is prepared **before** the skill runs — commonly via the `ena`, `geo`,
  `arrayexpress`, or `pride` data-retrieval skills — and is referenced by `--input`. (Some entry
  points take a different input instead — e.g. scdownstream's `downstream` consumes an `.h5ad` via
  `--base_adata`, §4.7.)
- The exact column layout depends on the pipeline; each `SKILL.md` documents the columns its
  pipeline expects (e.g. rnaseq: `sample,fastq_1,fastq_2,strandedness`).
- The skill does not fabricate a samplesheet silently; if one is missing, it directs the user to
  generate it first.

---

## 7. Python API conventions

- **Dependencies:** Python standard library **only, plus `pyyaml`**. No other third-party packages.
- **Responsibilities:**
  - Build `params.yml` (emit with `yaml.safe_dump`, keys unquoted, stable order). Parameter
    handling is **dynamic but validated**: the script parses the pipeline's stored
    `assets/nextflow_schema.json` (JSON, stdlib) to derive the valid keys, value enums, and defaults
    (no hard-coded allowlist, so new params/versions need no code change). It **rejects an unknown
    key** and **rejects an out-of-enum value** with a hard error naming the offender, and keeps only
    non-default values — comparing each against its effective runtime default (the `nextflow.config`
    value if set there, else the schema default; the two can diverge) (§5).
  - **Seed the pipeline's recommended non-default values** (§5) by default, report them to the user,
    and let user-supplied values override them. Recommendations live in the shipped
    `templates/params.yml`, so they are validated the same way as any other entry.
  - **Fill species-dependent params from the species** using the built-in `GENOMES` map, when the
    skill's CONFIG declares a `species_map` (§5, "Species-based genome selection"). The species comes
    from `--species`, else is inferred from a species/organism column in `--metadata` or the
    `--input` samplesheet (scientific names via `SPECIES_ALIASES`, e.g. *Mus musculus* → mouse).
    Applied after the recommendations and before `--set`, so explicit `--set` wins.
  - **Value constraints (where a pipeline defines one).** Validate a parameter's value against a
    stored reference list in `assets/` and **warn (not error)** on a miss. For scdownstream's
    `celltypist_model`:
    1. if the value contains a path separator `/`, treat it as a **custom model file path** and
       accept it (skip the name check);
    2. otherwise normalise a trailing `.pkl` and match it against the `models[].filename` entries in
       `assets/celltypist_models.json` — a match is a valid built-in model;
    3. otherwise **warn** ("not in the CellTypist model list; for a custom model give a file path")
       and still write the value.
  - Fill the SLURM template's placeholders when generating the job script copy: the input-path and
    `resdir` lines always, and the `main=` line when `--main /path/main.nf` is given (else the
    pinned default is kept, §4.2).
  - **Optionally** generate a custom process-resource config (Groovy, §4.6) from user-specified
    `cpus`/`memory`/`time` overrides — only when requested. Use `assets/base.config` as the
    reference for default resources and the valid `withName`/`withLabel` selectors, and warn when an
    override targets a selector not present there. When generated, wire `-c custom.config` into the
    job script; otherwise leave it out entirely.
  - Where relevant, validate or derive the `samplesheet.csv`.
- **Style:**
  - `argparse`-based CLI, one clear entry point per script.
  - **Deterministic output** — same inputs produce byte-identical files (no timestamps, no
    randomness, sorted iteration).
  - **No network calls at runtime.** The valid-parameter set is read from the *local* stored
    `assets/nextflow_schema.json`; downloading and refreshing the assets is a separate setup step (§5),
    performed by the skill author, not the script. Sample-data retrieval is the job of the
    dedicated data skills.
  - Writes outputs into the skill's `templates/` area (or a user-specified path), never elsewhere.

---

## 8. Naming & the two heavily-modified pipelines

Folder and file naming for all six pipelines:

| Pipeline id                     | Folder                        | Job script                          |
|---------------------------------|-------------------------------|-------------------------------------|
| `nf-core:rnaseq`                | `nf-core_rnaseq`              | `run_nfcore_rnaseq.sh`              |
| `nf-core:scrnaseq`              | `nf-core_scrnaseq`            | `run_nfcore_scrnaseq.sh`            |
| `nf-core:differentialabundance` | `nf-core_differentialabundance` | `run_nfcore_differentialabundance.sh` |
| `bigbio:quantmsdiann`           | `bigbio_quantmsdiann`         | `run_bigbio_quantmsdiann.sh`        |
| `nf-core:spatialvi`             | `nf-core_spatialvi`           | `run_nfcore_spatialvi.sh`           |
| `nf-core:scdownstream`          | `nf-core_scdownstream`        | `run_nfcore_scdownstream_qc_clustering.sh`, `run_nfcore_scdownstream_downstream.sh` *(two entry points, §4.7)* |

Rule: folder = pipeline id with `:` → `_`; job script = `run_` + folder name with any remaining
`-` normalized to `_` (see `run_nfcore_rnaseq.sh`). **Multi-entry pipelines** (§4.7) append the
entry name: `run_<folder>_<entry>.sh`, each paired with `params_<entry>.yml`.

**Substantially modified pipelines.** `nf-core:differentialabundance` and `nf-core:scdownstream`
diverge from upstream nf-core — their `main.nf` paths and parameter sets are **not** the stock
nf-core ones. Their `SKILL.md` **must** document the deltas from upstream (renamed/added/removed
params, custom modules) so `params.yml` is written against the modified interface, not the
public nf-core docs.

`nf-core:scdownstream` additionally exposes **two entry points** (§4.7): `qc_clustering`
(samplesheet → `integrated_scvi_finalized.h5ad`) and `downstream` (that h5ad via `--base_adata` →
downstream analysis). They run in sequence and each has its own job script + `params_<entry>.yml`.
It also stores `assets/celltypist_models.json` (the CellTypist model list); its `celltypist_model`
value is checked against that list — accepting a known model name or a custom-model file path,
warning otherwise — per §7. Its `SKILL.md` carries prose custom-config recommendations (§4.6),
e.g. bump process memory to `225.GB` for datasets exceeding 250,000 cells.
