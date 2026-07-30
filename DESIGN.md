# DESIGN.md — House Style for `informatics_pipeline_skills`

---

## 1. Purpose & scope

`informatics_pipeline_skills` is a collection of Claude Code **skills**. It holds two kinds:

- **Pipeline skills** — one per Nextflow nf-core-style pipeline. Each helps a user assemble the
  artifacts needed to run one pipeline job on the SLURM cluster:
  - a **SLURM job bash script** (an edited copy of the pipeline's template),
  - a **`params.yml`** file capturing the pipeline parameters that differ from defaults, and
  - *optionally*, a **custom process-resource config** (`-c custom.config`, §4.6) when the run needs
    non-default CPUs/memory/time.
- **One operations skill — `slurm`** (§9) — which transfers those artifacts **and the run's input data**
  to the HPC, submits jobs (subject to a 100-job cap), reports job and pipeline status, cancels a job,
  **downloads results back within a 2 GB cap**, and removes an allow-listed intermediate artifact on
  request. It also carries a small job template for unpacking compressed input archives on the cluster.

**A pipeline skill never executes a pipeline.** It only *generates* the artifacts above, and never
shells out to `sbatch`, `ssh`, or `scp` itself. **The `slurm` skill (§9) is what actually starts a
pipeline run**, by submitting the job script a pipeline skill produced; it also handles transfer,
monitoring, cancellation, and cleanup. The user invokes it separately once the artifacts exist — or
simply runs `sbatch` on the cluster by hand.

Because the `slurm` skill runs real commands on the cluster as the user, it is bound by the safety
contract in §9: credentials are always asked for and never inferred, passwords are never used, and no
file or folder is created, overwritten, or deleted without the user's permission.

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

Canonical **pipeline**-skill structure:

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

### The `slurm` folder — the one exception

The structure above describes **pipeline** skills. The `slurm` operations skill (§9) is what actually
**starts the pipeline runs** — it submits the job scripts the pipeline skills generated — but it is not
tied to any one pipeline and writes no `params.yml`, so it has **no pinned pipeline `assets/`** (no
`nextflow_schema.json`, `nextflow.config`, or `base.config`: there is no single parameter set for it to
validate against). It does ship **one** job template of its own, for unpacking compressed input data on
the cluster (§9.4.5):

```
slurm/
├── SKILL.md                 # follows §9, not the §3 pipeline-skill section order
├── templates/
│   └── run_uncompress.sh    # SLURM job: unzip / tar -xzf an archive on the HPC (§9.4.5)
└── scripts/
    └── slurm_ops.py         # subcommands: transfer | submit | job_status | cancel | cleanup (§9.4)
```

Like any template (§2), `run_uncompress.sh` is **copied and edited** per run, never mutated in place.

---

## 3. SKILL.md anatomy

Every skill folder contains a `SKILL.md` with YAML frontmatter followed by instructions. The section
order below is the **pipeline**-skill layout; the `slurm` skill's `SKILL.md` follows §9 instead.

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
6. **Hand back** — tell the user the final file paths, and point them at the **`slurm` skill** (§9)
   to transfer the files to the HPC and submit the job. Running `sbatch run_<pipeline>.sh` on the
   cluster by hand stays an equally valid route — say so, and never submit the job yourself from a
   pipeline skill (§1).

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

**Relative paths — where the job must be submitted from.** `-params-file params.yml` is a **relative**
path, as are `-c custom.config` (§4.6) and §4.8's `cp *.sh` / `rm -rf work`. Three consequences that
every skill has to respect:

- the job script, its `params.yml` (or `params_<entry>.yml`), and any `custom.config` must sit **in the
  same directory** — so `transfer` pushes them to one destination (§9.4.0);
- the job must be **submitted from that directory** (`cd <run dir> && sbatch run_<pipeline>.sh`), or
  Nextflow will not find the params file — this is what `slurm submit` does (§9.4);
- that directory is the job's working directory, where `work/`, `.nextflow/`, `.nextflow.log` and the
  SLURM `.out` are created — which is why §9.5 reads `WorkDir` rather than assuming `$resdir`.

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

This `rm -rf work` is **inside the job script**: it runs on the cluster, in the job's own working
directory, on a relative path, as part of a script the user submitted. It stays exactly as written.
It is *not* the same thing as the `slurm` skill's `cleanup` subcommand (§9.4), which is an
interactive remote removal — that one always names one explicit absolute path and is bound by both the
§9.3 path guard and the §9.4.1 allow-list (which is what makes `work`, `out`/`outs`, `.nextflow`, and
the bulk input/object files removable and everything else not).

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
- Getting the samplesheet, the other per-run text artifacts, **and the input data** onto the cluster is
  the `slurm` skill's `transfer` step — §9.4.0 lists what that covers. Compressed inputs are unpacked on
  the cluster by the job in §9.4.5.

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
  - Writes its generated files to the **user-specified destination** (`--dest`), and reads the shipped
    `templates/` copies without mutating them (§2, §3). It writes nowhere else.

The rules in this section govern the **pipeline** skills. The `slurm` skill's API keeps most of them
but necessarily departs on two (it makes remote calls, and its effects are not files) — the deltas are
spelled out in §9.6.

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

The **operations skill** is not a pipeline, so that rule does not apply to it: its folder is simply
`slurm`, and it ships no pipeline job script and no `params.yml`. Its one template is the
pipeline-independent `templates/run_uncompress.sh` (§2, §9.4.5) — named for what the job does, since
there is no pipeline id to derive a name from.

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

---

## 9. The `slurm` skill — submission, monitoring, and remote access

### 9.1 Purpose

`slurm` is the repository's single **operations skill** (§1) and the **only** place in the repo that
touches the cluster. It is the only skill permitted to run `ssh`, `scp`/`rsync`, `sbatch`, `squeue`,
`sacct`, `scontrol`, `scancel`, `find`, or `rm` against the HPC. Pipeline skills generate artifacts and stop (§1, §3 step 6);
`slurm` takes it from there:

- **`transfer`** — push the generated files **and the run's input data** to the HPC (§9.4.0),
- **`download`** — pull results back, bounded to **2 GB** with big files excluded (§9.4.6),
- **`submit`** — submit the job script with `sbatch`,
- **`job_status`** — report the SLURM state and where the pipeline currently is,
- **`cancel`** — cancel one job by job id with `scancel`,
- **`cleanup`** — remove one explicitly named path on request, restricted to the allow-listed
  artifact kinds in §9.4.1.

**Scope of the rules — they are not about one script.** Everything in §9.2 and §9.3 binds **every
cluster interaction, however it is issued**: a `slurm_ops.py` subcommand, and equally a raw `ssh`,
`rsync`, or `scp` typed into a Bash call. There is no "quick one-off" exemption. Two consequences:

- **Pulling data from the HPC is only ever done with `slurm_ops.py download`** (§9.4.6). Never
  hand-roll an `rsync`/`scp` pull and run it yourself — that path has no scan, no size cap, and no
  path guard.
- Anything the skill cannot do within those rules is **handed to the user as a command they run** —
  `transfer --print-only` (§9.4.0), the retrieval `rsync` (§9.4.2), the full-tree pull that a capped
  download leaves behind (§9.4.6) — never worked around by issuing the command directly.

It also ships one job template of its own, `templates/run_uncompress.sh`, for unpacking a `.zip` or
`.tar.gz` input archive on the cluster (§9.4.5) — submitted through `submit` like any other job.

**Every SLURM and SSH command is handled with extreme care.** The rules in §9.2 and §9.3 are hard
constraints, not advice: they apply to every subcommand, on every invocation, with no exceptions and
no "the user probably meant" shortcuts. When a rule below and a user request conflict, the rule wins
and the reason is stated plainly to the user.

### 9.2 Credentials — always asked, never inferred

- **Always ask the user for the `username` and the `hostname`.** Every invocation, for every
  subcommand. **Never infer or guess them** — not from `$USER`/`whoami`, `~/.ssh/config`, shell
  history, an earlier session, `git config`, the user's email address, a hostname in the wiki, or a
  path seen in this repo or in a samplesheet. The skill ships **no default user and no default host**.
- **Never use a password.** No password prompt, no password as a CLI argument, no `sshpass`, no
  password read from a file or environment variable, no interactive keyboard-interactive fallback.
  Key-based authentication only.
- **Passwordless SSH is the user's responsibility.** The user configures it *before* using this skill.
  It is **not** the skill's job: it never creates, edits, copies, or inspects SSH keys,
  `~/.ssh/config`, `known_hosts`, or `authorized_keys`, never runs `ssh-keygen` or `ssh-copy-id`, and
  never attempts to set up or repair key auth. If a connection fails for an authentication reason,
  report the failure plainly, tell the user to configure passwordless SSH to that host, and **stop** —
  do not retry with another method.
- Credentials are for the current invocation only: never written to a file, a config, or a log, and
  never persisted across sessions.

### 9.3 Path safety — the guard shared by every subcommand

A remote path may only be used when **all** of these hold:

1. **Absolute** — no relative path, no `~`, no unexpanded `$VAR` left in it.
2. **Inside one of the user's own standard directories**, i.e. it starts with one of the
   **user-directory prefixes** below, with `<username>` being exactly the username the user gave
   (§9.2). A path that does not contain that username as a path component is **rejected**: it points
   outside the user's own area. Always check this before the path is used in any command.
3. **Below the top of the hierarchy** — never operate *on* a user directory itself or on any root
   above it. The target must sit **at least one level below** the user-directory prefix.
4. **Literal — no wildcards or globs** — never `*`, `?`, `[...]`, or brace expansion in a path.

The guard applies identically to **all** the standard user directories — it is not specific to
`/data`:

| User-directory prefix | Allowed target (example) | Always rejected |
|---|---|---|
| `/data/<username>` | `/data/<username>/project_1` | `/data/<username>`, `/data` |
| `/nfsdata/<username>` | `/nfsdata/<username>/project_1` | `/nfsdata/<username>`, `/nfsdata` |
| `/home/<username>` | `/home/<username>/project_1` | `/home/<username>`, `/home` |
| `/shared/home/<username>` | `/shared/home/<username>/project_1` | `/shared/home/<username>`, `/shared/home`, `/shared` |
| `/scratch/<username>` | `/scratch/<username>/project_1` | `/scratch/<username>`, `/scratch` |

A path under any other root (a shared project area, another user's directory, `/tmp`, `/nfsdata`
software trees such as `/nfsdata/scripts` or `/nfsdata/apptainer`, `/` itself) is **outside the
guard** — refuse it and ask the user for a path under one of the prefixes above. The prefix list is a
constant in `slurm_ops.py`; extend it there, not by loosening the check.

Destruction and mutation rules layered on top of the guard:

- **Never run `rm -r *` or `rm -rf *`.** Never any `rm` with a glob, a relative path, or a bare `.`.
  A removal always names **one explicit full path**, e.g.
  `rm -rf /data/<username>/project_1/nfcore/scrnaseq/work`.
- **Never delete, overwrite, or create a file or folder without the user's permission.** Show the
  exact command and the exact absolute target, then get an explicit go-ahead. This applies to
  *creating* a remote destination directory just as much as to removing one — do not `mkdir -p`
  silently.
- **`transfer` never silently overwrites.** Check whether the remote file exists and ask before
  replacing it.
- Quote and escape every remote argument so a path cannot be re-split or re-expanded by the remote
  shell (see §9.6).
- When a path fails the guard, refuse the operation, name which check it failed, and ask the user for
  a conforming path. Never "fix" a path by appending or trimming components on your own.
- **The guard applies to a read source, not just a write target.** A `download` source (§9.4.6), a log
  path, a directory listing — all of them go through the same checks, so data is never *read* out of
  another user's directory either. "It only reads" is not a reason to relax any rule here.
- **Paths the cluster reports back are guarded too.** `scontrol`/`sacct` return a `WorkDir` and a
  `StdOut` that the skill did not choose — a job may have been launched from a shared area. Check them
  before reading them, and before offering one as a `cleanup` target: if such a path is outside the
  user's own directories, **say so and do not read it** rather than following it. In code this is
  `in_user_path()` / `require_user_path()`, the non-fatal form of the guard.

### 9.4 The six subcommands

One script, `scripts/slurm_ops.py`, with six `argparse` subcommands, so the credential prompt (§9.2)
and the path guard (§9.3) live in one place instead of being duplicated. All six take `--user` and
`--host` (§9.2).

| Subcommand | Does | Key rules |
|---|---|---|
| `transfer` | **Upload** (local → HPC): the run's text artifacts *and* its input data — see §9.4.0 for the list. `--print-only` prints the `rsync` command for the user to run instead of pushing | §9.3 guard on the remote directory; ask before creating it; ask before overwriting any existing remote file; uploads only — the other direction is `download` |
| `download` | **Download** (HPC → local): a results directory, scanned first, big files excluded, **capped at 2 GB total** (§9.4.6) | §9.3 guard on the **source** — never another user's directory; refuse rather than truncate when over the cap; confirmed by the user before it starts |
| `submit` | `sbatch <script>` in the remote run directory | **Pre-flight the 100-job limit with `squeue -u` and refuse if the user is at the cap** (§9.4.3); after submission, **report the folder on the HPC and the job id** to the user — both, explicitly |
| `job_status` | `sacct` / `scontrol show job <jobid>` | Report the state as one of **pending, running, complete, fail, node_fail**, plus the current pipeline step (§9.5) |
| `cancel` | `scancel <jobid>` | One job id, never a mass cancel; confirm first; afterwards **suggest** a `cleanup` of that run's directory (§9.4.4) |
| `cleanup` | `rm -rf <one explicit absolute path>` | §9.3 guard **and** the §9.4.1 allow-list — the target's own name must be a removable kind; the path comes from the user via `--path`; show the target (`ls`, `du -sh`) and require explicit confirmation before removing |

**`transfer`** moves a run's text artifacts **and its input data** onto the cluster (§9.4.0). It is
**one-directional**: it uploads and never fetches. Getting results back is `download` (§9.4.6), or a
printed `rsync` the user runs themselves (§9.4.2). A user who prefers to run the upload themselves gets
the push command printed instead (`--print-only`, §9.4.0).

**`submit`** always `cd`s into the directory holding the job script and runs `sbatch` **from there**,
because the script's `-params-file params.yml` and `-c custom.config` are relative paths (§4.5). Refuse
to submit if the params file the script names is not present in that directory — the run would fail
minutes later with a confusing Nextflow error. That directory is also the job's `WorkDir`, so it is
where `work/`, `.nextflow/`, `.nextflow.log` and the SLURM `.out` appear (§9.5).

**`cleanup`** takes an explicit full path under the user's project, subject to the whole of §9.3 under
**any** of the user-directory prefixes there — **and** to the allow-list in §9.4.1. So a path is only
removable when it *both* sits inside the user's own area and *is* one of the intermediate/regenerable
artifact kinds the pipeline skills produce. Any user directory itself (`/data/<username>`,
`/scratch/<username>`, `/shared/home/<username>`, …), any root above one (`/data`, `/scratch`,
`/shared/home`, …), a relative path, and anything containing a `*` remain hard rejects regardless of
the allow-list. The path is always given by the user; never widen it, and never delete a sibling or
parent "while we're there".

#### 9.4.0 What `transfer` pushes — the artifact list

Everything a pipeline entry point needs to run: the per-run text artifacts the pipeline skills generate
or expect (§3, §5, §6) **and** the input data itself.

**Per-run text artifacts**, for the pipelines in §8:

| Artifact | Produced by / required by |
|---|---|
| `run_*.sh` — including `run_<folder>_<entry>.sh` (§4.7) | every pipeline skill (§4) |
| `params.yml`, or `params_<entry>.yml` per entry point | every pipeline skill (§5) |
| `custom.config` | when process resources were tuned (§4.6) |
| `samplesheet.csv` — the `--input` sheet, any column layout (§6) | rnaseq, scrnaseq, spatialvi, scdownstream `qc_clustering`, differentialabundance (its *observations* sheet) |
| `contrasts.csv` — the contrasts sheet (`variable,reference,target,blocking`) | differentialabundance, referenced from `params.yml` as `contrasts` |
| the **`matrix` TSV** — abundance matrix (features × samples) | differentialabundance, referenced from `params.yml` as `matrix` |
| `*.sdrf.tsv` — the SDRF sample table (**not** a CSV samplesheet) | quantmsdiann, its `--input` |
| `metadata.tsv` | optional; the skills read it *locally* to infer species (§5), so push it only if the user wants it stored beside the run |

**Input data.** `transfer` also pushes the data a pipeline entry point consumes — essentially anything
in the §6 input chain that the user already holds locally:

| Kind | Examples / consumed by |
|---|---|
| Sequencing reads | `fastq` directories and FASTQ files; `sra` download directories |
| Aligner/counter outputs | Cell Ranger and Space Ranger **`outs` directories** (scrnaseq output, spatialvi `spaceranger_dir` input) |
| Proteomics raw data | `*.raw` files, `*.d/` directories (quantmsdiann, referenced from its `*.sdrf.tsv`) |
| Archives | `*.tar.gz`, `*.zip` — unpack them on the cluster with the job in §9.4.5 |
| Analysis objects | `*.rds`, `*.pkl`, `*.h5ad` (e.g. a scdownstream `--base_adata`, or per-sample matrices in a samplesheet) |
| Tables | any `*.csv` / `*.tsv` — samplesheets, contrasts, matrices, SDRF, metadata |

- **Names are the real ones.** `contrasts.csv` is plural — it matches the pipeline's `contrasts`
  parameter; the quantmsdiann input must end `.sdrf.tsv`. Do not "tidy" a filename in transit: a path
  written into `params.yml` must still resolve on the cluster after the push.
- **Use `rsync` for data, not `scp`.** Directories and multi-GB files go with
  `rsync -avh` (add `-P` for `--partial --progress`, so an interrupted push resumes instead of
  restarting). Preserve the directory structure a samplesheet expects — a Cell Ranger `outs` tree or a
  `.d/` directory is only valid as a whole.
- **Upload only, and confirmed.** Every §9.3 rule holds for a data push: the remote destination must
  pass the path guard, the directory is created only with permission, and **an existing remote file or
  directory is never silently overwritten** — ask first. `transfer` itself pulls nothing; that is
  `download`'s job (§9.4.6).
- **Say what it will cost before starting.** For a large push, report the local size (`du -sh`) and that
  the transfer runs on the user's connection until it finishes. Where the data is **public**, mention
  the cheaper route — download it directly on the cluster with the data-retrieval skills (`ena`, `geo`,
  `arrayexpress`, `pride`, `sra`, `fastq-download-script`) instead of uploading from a laptop. It is a
  recommendation, not a refusal: if the user wants to push their local copy, push it.
- **Print-the-command mode — `--print-only`.** Many users would rather run the upload themselves: from a
  terminal they control, in a `screen`/`tmux` session, or overnight. `transfer` therefore takes
  **`--print-only`**, which does everything except transfer — it resolves and guards the remote path
  (§9.3), then **prints the exact `rsync` command and stops**, mirroring the pull hand-off in §9.4.2:

  ```bash
  # push a samplesheet + params into the run directory
  rsync -avh samplesheet.csv params.yml run_nfcore_scrnaseq.sh \
      <username>@<hostname>:/data/<username>/project_1/nfcore/scrnaseq/

  # push a data directory (resumable — -P adds --partial --progress)
  rsync -avhP fastq <username>@<hostname>:/data/<username>/project_1/
  ```

  Trailing-slash convention for a push: **end the remote destination with `/`** (it is the directory the
  files land in), and give the local source **without** a trailing slash so the directory itself is
  copied rather than only its contents. In this mode the skill creates nothing remotely and asks for no
  confirmation — there is nothing to confirm, since the user runs it. Say plainly that the destination
  directory must already exist, or that `rsync` will need it created first.
- **Genome references are not per-run inputs.** The `fasta`/`gtf`/`spaceranger_reference` paths in §5
  point at shared cluster locations (`/nfsdata/genome/…`) — use those rather than uploading a reference,
  and never write into a shared reference tree (§9.3 rejects it anyway).
- Push destination is the run directory the job script will use — the `$resdir` / samplesheet paths of
  §4.3 — and it must pass §9.3. The templates default those to `/data/${USER}/…` and
  `/nfsdata/${USER}/…`, both of which are user-directory prefixes in §9.3.
- **Keep the job script and its params file together.** They are pushed to the **same directory**, since
  the script references `params.yml` / `custom.config` by relative path and `submit` runs `sbatch` from
  there (§4.5, §9.4). Data files may live anywhere the samplesheet points, as long as it passes §9.3.
- **Concrete paths only.** §4.3 writes paths as `UPPERCASE` placeholders and `${USER}`, which
  `build_job.py` fills in (§7). By the time a path reaches this skill it must be **fully resolved** —
  `/data/<username>/project_1/…`, never `/data/${USER}/RESULTS_DIR` or `PATH_TO_SAMPLE_SHEET`. §9.3
  rejects an unexpanded `$VAR`; do not expand one on the user's behalf, ask for the real path.

#### 9.4.1 What `cleanup` may remove — the allow-list

`cleanup` is restricted to the intermediate, regenerable, and bulk-input artifacts that follow the
pipeline skills' output conventions (§4.3, §4.8). The decision is made on the **final component of the
path** — its directory name, or its file extension:

| Kind | Removable targets | Where these come from |
|---|---|---|
| Pipeline directories | `work`, `out`, `outs`, `sra`, `fastq`, `.nextflow` | `work` + `.nextflow` = the Nextflow workdir/cache in the **launch directory** (§4.8); `out` = `$outdir` (`$resdir/out`, §4.3); `outs` = Cell Ranger / Space Ranger per-sample output dirs; `sra`/`fastq` = download areas written by the `sra` and `fastq-download-script` skills |
| Compressed inputs | `*.zip`, `*.tar.gz`, `*.tgz`, `*.gz` | Downloaded/compressed inputs that can be fetched again |
| Zarr archives | `*.zarr` | A directory, removed as a whole (spatial data) |
| Dataset objects | `*.rds`, `*.h5ad`, `*.h5`, `*.pkl`, `*.h5seurat` | Analysis objects a pipeline can regenerate |
| Proteomics raw inputs | `*.d` directories, `*.raw` files | Bruker `.d/` directories and Thermo `.raw` files |

- **Match on kind, not just on name.** A directory-name entry matches **only a directory**; a file
  extension matches **only a file**; `*.zarr` and `*.d` are directories. And the name must match
  **exactly**, not as a substring — `/…/project_1/work` yes, `/…/project_1/workflows` no. This is what
  keeps the SLURM `slurm-<jobid>.out` logs and the `*.sh` / `*.out` copies §4.8 places in `$resdir`
  from ever being mistaken for the `out` directory entry.
- **Anything not on this list is refused** — a `results` folder, `$resdir` **itself** (it holds the
  `nextflow_report.html` from §4.5's `-with-report $resdir/…` plus the `*.sh`/`*.out` copies from §4.8),
  a `params.yml`, a job script, a samplesheet, `contrasts.csv`, a `matrix` TSV, an `.sdrf.tsv`, a log, an
  unrecognised directory. Say which rule the target failed and stop; do not offer to remove a parent
  instead.
- **Several allow-listed kinds are also pipeline *inputs*.** "Regenerable" is not "worthless" — name the
  cost in the confirmation prompt:
  - `integrated_scvi_finalized.h5ad` is the **required `--base_adata` input** of scdownstream's
    `downstream` entry (§4.7); regenerating it means re-running the entire `qc_clustering` stage.
  - an `outs` directory can be the **`spaceranger_dir` input** of a spatialvi processed-data run, and
    `.h5`/`.h5ad` files are the per-sample inputs listed in a scdownstream samplesheet.
  - `.raw` / `.d` data referenced by a `*.sdrf.tsv`, and `fastq`/`sra` downloads referenced by a
    samplesheet, must be re-downloaded before that run can be repeated.
- The allow-list is a set of **constants in `slurm_ops.py`** — `CLEANUP_DIR_NAMES`,
  `CLEANUP_DIR_SUFFIXES` (`.zarr`, `.d`), `CLEANUP_FILE_SUFFIXES`, and `CLEANUP_RESULT_DIRS` (the
  `out`/`outs` warning). Extend those — never bypass the check for a one-off request.
- `out` / `outs` hold pipeline **results**. They are removable, but say so plainly in the confirmation
  prompt — echo the full path and state that these are results, not scratch.
- **No globbing, ever** (§9.3). To clear several files of an allowed kind, list them first with `ls`,
  show the user the exact list, and then remove them **one explicit full path at a time** — the skill
  never hands a `*` to the remote shell and never expands one locally into a single blind command.

Typical shape:

```bash
python3 scripts/slurm_ops.py cleanup --user <username> --host <hostname> \
    --path /data/<username>/project_1/nfcore/scrnaseq/work
# → guard: absolute ✓, under a user-directory prefix as /<username>/ ✓,
#          at least one level below /data/<username> ✓, no glob ✓
# → allow-list: final component is `work` ✓ (§9.4.1)
# → shows `ls` + `du -sh` of the target, asks the user
# → rm -rf /data/<username>/project_1/nfcore/scrnaseq/work   (only after confirmation)

# refused — passes §9.3 but is not a removable kind:
#   --path /data/<username>/project_1/nfcore/scrnaseq/params.yml
#   --path /data/<username>/project_1/results
```

#### 9.4.2 Getting results back — the two routes

There are exactly **two** ways results come back, and the user chooses:

| Route | When | Who runs it |
|---|---|---|
| `download` (§9.4.6) | the wanted files fit in **2 GB** once big files are excluded | the skill, after the user confirms |
| the `rsync` command below | anything larger, the complete tree including big files, or simply the user's preference | **the user**, on their own machine |

**Always offer both** — state the size the scan found and let the user decide; never assume. And when
`job_status` reports `complete`, volunteer them (§9.5) rather than waiting to be asked.

This section is about the second route: **tell the user the exact `rsync` command** to fetch the output
directory themselves — the pull counterpart of `transfer --print-only` (§9.4.0):

```bash
# whole results directory — out/ plus the report and the job's own logs
rsync -avh <username>@<hostname>:/data/<username>/project_1/nfcore/scrnaseq scrnaseq

# or just the pipeline outputs
rsync -avh <username>@<hostname>:/data/<username>/project_1/nfcore/scrnaseq/out out
```

- Flags: **`-a`** (recursive, preserves permissions/times/symlinks), **`-v`** (verbose), **`-h`**
  (human-readable sizes). For a large or previously interrupted transfer, offer **`-avhP`** — `-P` adds
  `--partial --progress`, so a resumed run picks up where it stopped.
- **Default to the run's results directory `$resdir`** (§4.3), not `$outdir` alone: besides `out/`, that
  directory collects the `nextflow_report.html` (written there by §4.5's `-with-report $resdir/…`) and
  the job-script and SLURM-log copies (`*.sh`, `*.out`) that §4.8 places there at the end of the run —
  so syncing `$resdir` retrieves the outputs *and* the provenance. Offer `$resdir/out` as the narrower
  alternative when the user only wants pipeline results.
- **A cancelled or failed run has no §4.8 copies**, since the job never reached its finalize block — for
  those, the SLURM `.out` and `.nextflow.log` are still in the launch directory (`WorkDir`, §9.5), so
  point the user there instead of at a `$resdir` that may hold only a partial `out/`.
- Give the full absolute remote path, with **no trailing slash** on it.
- Destination is the **basename of the directory being fetched**, so the copy lands in a matching local
  folder. Warn the user that rsync creates it: if a folder of that name already exists in their current
  directory, the copy nests inside it (`out/out`) — so run the command from a clean location, or give a
  different local destination name.
- The remote source is the path `submit` reported (§9.4) — quote it exactly; never guess a results path
  the skill has not seen.
- The skill **prints this command; it does not run it.** It is the user's transfer, on their machine, in
  whatever directory they choose — never execute it for them, and never invent a local destination path
  on their behalf. A pull the skill performs itself goes through `download` (§9.4.6) and nothing else:
  a hand-rolled `rsync`/`scp` pull run from Bash is forbidden (§9.1).
- Suggest fetching results **before** any `cleanup` of `out`/`outs` (§9.4.1) — once removed, they are
  gone from the cluster.

#### 9.4.3 Submission limit — a maximum of 100 jobs

A user may have **at most 100 jobs on the cluster at once**. `submit` therefore always runs a
**pre-flight check before `sbatch`**:

```bash
squeue -u <username> -h -o "%i" | wc -l      # the user's current job count
```

- If the count is **already at or above 100**, **refuse the submission.** Do not submit and hope; do not
  submit "just one more". Report the current count, and tell the user to wait for jobs to finish or to
  `cancel` (§9.4.4) what they no longer need, then ask again.
- Count the jobs `squeue -u <username>` reports for that user — both running and pending, since a
  pending job occupies a slot in the queue just the same.
- Use `--user` from §9.2 for `-u`; never `squeue` for another user, and never fall back to a bare
  `squeue` over the whole cluster.
- This matters more than it looks: a Nextflow driver job **submits many child jobs of its own** as the
  pipeline progresses (§4.6), so one submission can grow into dozens of queue entries. The check is a
  **snapshot taken before submission** — it cannot bound what a running pipeline goes on to spawn, so
  report the count to the user when it is already high rather than only at the cap.
- The limit is a **constant in `slurm_ops.py`** (`MAX_JOBS = 100`), not a magic number sprinkled through
  the code.

#### 9.4.4 Cancelling a job — `cancel`

- `scancel <jobid>` — **one explicit job id**, taken from the user (normally the id `submit` reported,
  §9.4). **Never a mass cancel:** no bare `scancel -u <username>`, no job-id ranges, no wildcards, no
  "cancel everything that looks stuck".
- **Confirm before cancelling.** Echo the job id and what the job is (`squeue`/`scontrol` shows its name
  and work dir) and get an explicit go-ahead — cancelling ends real compute mid-flight.
- Cancel only the user's **own** job: the job id must belong to `--user` (check with
  `squeue -u <username>` / `sacct`), and refuse otherwise rather than letting the scheduler decide.
- After a successful cancel, **suggest cleaning up that run's directory** — a cancelled Nextflow run
  leaves a large, half-finished `work` tree and a `.nextflow` cache behind. `work` and `.nextflow` sit
  in the directory the job was **launched from**, which is not necessarily `$resdir`: the job scripts
  delete `work` by relative path (§4.8), so read the actual location from `scontrol show job <jobid>`
  (`WorkDir`) rather than assuming. Point the user at `cleanup` (§9.4.1) with that concrete path, e.g.:

  ```
  Cancelled job 1234567 (nf-core:scrnaseq, /data/<username>/project_1/nfcore/scrnaseq).
  That run's work directory is still on disk. To remove it:
    python3 scripts/slurm_ops.py cleanup --user <username> --host <hostname> \
        --path /data/<username>/project_1/nfcore/scrnaseq/work
  ```

  It stays a **suggestion**: the removal still goes through `cleanup`'s own allow-list, path guard, and
  confirmation (§9.3, §9.4.1). Never chain a deletion onto a cancel automatically — and note that
  keeping `work` is what makes a later `-resume` (§4.5) possible, so a user who intends to resume should
  *not* clean it up.

#### 9.4.5 Unpacking compressed inputs — `templates/run_uncompress.sh`

Input data often arrives compressed — PRIDE projects ship `.zip`, and other sources ship `.tar.gz` —
whether it was pushed by `transfer` (§9.4.0) or downloaded straight onto the cluster by a data skill.
Unpacking a multi-GB archive is real work, so it belongs in **its own SLURM job**, not on a login node.

The `slurm` skill ships `templates/run_uncompress.sh` for exactly this. A data-retrieval skill that
lands an archive on the cluster uses the same template rather than inventing its own.

- **Follows the §4 job-script conventions** that apply: the §4.1 `#SBATCH` header (`--partition=htc`,
  `--time`, `set -e`, `set -o pipefail`), §4.3 `UPPERCASE` placeholders for the paths, and the §4.3
  mkdir-guard idiom for the destination. §4.2 (`exec`/`main`) and §4.5 (`nextflow run`) do **not**
  apply — there is no Nextflow in this job.
- **Two archive forms**, chosen by extension, each with an explicit destination:

  ```bash
  # CHANGE to the archive and the directory to unpack into
  archive=/data/${USER}/PROJECT/ARCHIVE_NAME
  destdir=/data/${USER}/PROJECT/DEST_DIR

  unzip -n "$archive" -d "$destdir"           # .zip     — -n: never overwrite an existing file
  tar -xzkf "$archive" -C "$destdir"          # .tar.gz  — -k: keep existing files, don't overwrite
  ```

  The `${USER}`/`UPPERCASE` forms are the template's placeholders (§4.3); once filled, the resulting
  absolute paths must satisfy §9.3 like any other path this skill handles.
- **List before extracting.** `unzip -l` / `tar -tzf` is read-only — use it to show the user what the
  archive contains and where it will land, before the extraction job is submitted. An archive with
  absolute or `../` member paths is refused, not "fixed".
- **Never overwrite silently** (§9.3): unpack into a **named destination directory**, created with
  permission, and keep the non-overwriting flags — `unzip -n` and `tar -k`, since a plain `tar -xzf`
  **replaces existing files without asking**. Use an overwriting form only if the user explicitly asks
  for it.
- **Submitted like any other job** — through `submit` (§9.4), so it is subject to the 100-job check
  (§9.4.3) and reports its HPC folder and job id back; check it with `job_status` (§9.5).
- **The archive is not deleted afterwards.** Once the user has confirmed the unpacked data looks right,
  the `.zip`/`.tar.gz` is a normal `cleanup` candidate (§9.4.1) — an explicit, separately confirmed step.

#### 9.4.6 Downloading results — `download` and the 2 GB cap

The one route by which the skill itself pulls data off the cluster (§9.1). It is deliberately narrow:
small enough to be safe and quick, with everything larger handed to the user as a command (§9.4.2).

**Rule 0 — only the user's own results, checked two ways.** **Another user's data is never downloaded,
and no flag overrides this.**

1. **The path** must contain the username, under one of the §9.3 user-directory prefixes. The guard runs
   on the source **before the scan**, so a foreign path is never even listed. It governs a *read* source
   exactly as it governs a write target — "it's only reading" is never a reason to relax it.
2. **The ownership** must match, because a path under `/data/<username>/…` can still hold files that
   belong to someone else (a group-writable directory, a copy from a colleague). **Let the cluster
   decide the identity — never compare owner strings.** `find`'s `%U` is a *numeric uid* while `%u` is a
   *name*, and GNU `stat` uses those two letters the other way round; comparing either against `--user`
   is how every file in a user's own tree once came back flagged as foreign. So:
   - **pre-flight the account** with `id -u <username>` — if the HPC does not recognise it, stop and say
     so, rather than running checks against a name the system cannot resolve;
   - **the source directory**: `find <dir> -maxdepth 0 ! -user <username> -print` — any output means it
     belongs to someone else, and the download is refused;
   - **each file**: one traversal tags them with `find … \( ! -user <username> -printf 'F\t%s\t%p\n'
     -o -printf 'O\t%s\t%p\n' \)`, so `find` resolves ownership and the script only reads a tag. **Any
     file tagged `F` is a hard stop**: report the offenders and refuse the whole download. Do not filter
     them out and continue — an `--exclude` that silently drops files is how the wrong data gets copied.
     Tell the user to narrow the source to a directory holding only their own results.

Two further points the implementation honours:

- **Never `-L` / `--copy-links`.** `rsync -avh` copies a symlink *as a symlink*, so a link inside the
  results tree pointing at someone else's data is never dereferenced into the download. The scan uses
  `find` without `-L` for the same reason, so scan and transfer agree on what is in scope.
- A refusal names the rule and asks for a path under the user's own directory. It never offers a
  workaround.

**The flow — scan, exclude, check, confirm, pull:**

1. **Scan** the source read-only with the ownership-tagging `find` from rule 0, pruning the Nextflow
   scratch dirs `work` and `.nextflow` unless `--include-work` is given.
2. **Exclude big files** — anything larger than the per-file threshold (`--max-file-size`, default
   **500 MB**). Report how many were excluded and their total size, listing the largest.
3. **Check the total** of what remains against the **2 GB ceiling**.
4. **Report the plan and stop**, as every state-changing subcommand does (§9.6) — a download writes to
   the user's disk, so it is gated by `--confirm` too.
5. **Pull** with `rsync -avh --max-size=<threshold> --exclude=work --exclude=.nextflow`. `--max-size`
   uses rsync's 1024-based suffixes, the same arithmetic as the scan: the scan predicts, rsync enforces.

**Over the cap → refuse.** If what remains after exclusion still exceeds 2 GB, **refuse and transfer
nothing** — never a silently truncated subset. Print the total, the largest files still selected, and
the three ways forward: narrow the source to a subdirectory, lower `--max-file-size`, or run the full
`rsync` themselves. The same applies when *every* file is above the threshold: say so rather than
running an empty transfer.

**Limits are constants in `slurm_ops.py`** — `MAX_DOWNLOAD_BYTES` (a hard ceiling that no flag raises),
`DEFAULT_MAX_FILE_SIZE_BYTES`, `DOWNLOAD_SKIP_DIRS` (`work`, `.nextflow`). Sizes are **1024-based**
throughout, matching rsync's `K`/`M`/`G` suffixes: "2 GB" here means 2 GiB (`2 * 1024**3`) and "500 MB"
means 500 MiB, so the scan's arithmetic and `--max-size` cannot disagree.

**Local destination.** `--dest` defaults to the basename of `--remote`. It is created only as part of a
confirmed download, and a **non-empty existing directory is refused** unless `--overwrite` is given —
the same no-silent-overwrite rule `transfer` applies remotely (§9.3), because this direction writes to
the user's own disk.

**The flags**, all of which may tighten the limits and none of which loosen the 2 GB cap or Rule 0:
`--remote` (source, guarded), `--dest`, `--max-file-size`, `--include-work`, `--progress` (adds `-P`
for a resumable pull), `--overwrite`, `--confirm`, and **`--print-only`** — which prints both the
scanned-subset command *and* the full-tree command and transfers nothing, the pull twin of
`transfer --print-only` (§9.4.0). Offer `--print-only` whenever the user would rather drive the
transfer themselves.

**Hand back two things after every download** — always both:

1. **The full-results `rsync`, large files included** — no `--max-size`, so it is the complete tree.
   Print it whenever anything was excluded, and name what it would add (count and size from the scan) so
   the user can judge whether it is worth it. **The user runs this; the skill never does.** The 2 GB cap
   bounds what the *skill* transfers, not what the user may fetch.

   ```bash
   # everything, large files included — run this yourself
   rsync -avhP <username>@<hostname>:/data/<username>/project_1/nfcore/scrnaseq scrnaseq
   ```
2. **A suggestion to `cleanup` once the data is verified locally** — typically that run's `work`
   directory, with the reminder that removing `out`/`outs` is irreversible on the cluster. Two things
   to get right here: `work`/`.nextflow` live in the **launch** directory, which is not necessarily the
   directory just downloaded (§9.4.4, §9.5) — take the path from `scontrol`'s `WorkDir` rather than
   assuming it sits under the results dir; and it stays a **suggestion**, going through `cleanup`'s own
   allow-list, path guard, and confirmation (§9.3, §9.4.1). **Never chain a cleanup onto a download**,
   and never run one just because a download succeeded.

### 9.5 Progress reporting from the logs

`job_status` reports more than the raw SLURM state — it tells the user *where the pipeline is*:

- Read the job's stdout/stderr path from `scontrol show job <jobid>` (`StdOut` / `StdErr`). That file
  lives in the launch directory (`WorkDir`) — always the authoritative copy. Only a run that **completed
  its finalize block** also has a `*.out` copy in `$resdir` (§4.8); a cancelled or failed run does not,
  so read `WorkDir` rather than expecting one.
- `scontrol` only knows **live and recently-finished** jobs; for an older job id fall back to
  `sacct -j <jobid>` (which is also where the final state comes from).
- Also read the Nextflow log in the launch directory (`.nextflow.log` / `nextflow.log`), i.e. beside
  `work` and `.nextflow` — again `WorkDir`, not necessarily `$resdir`.
- From those, infer the **step the pipeline is currently at** — the process Nextflow most recently
  submitted or is running — and report it alongside the state.
- Always report the job state as one of **pending, running, complete, fail, node_fail** (distinguish
  `node_fail` from an ordinary `fail`: it means the node died, not the pipeline).
- **Read-only.** Never truncate, edit, move, or delete a log. Tail the relevant portion rather than
  dumping a whole large file.

**No active monitoring.** `job_status` is a **single on-demand check**, not a watcher: it does not poll
in a loop, sleep and re-check, tail a log continuously, schedule a follow-up, or hold the session open
waiting for a job to finish. The user asks whenever they want to know, passing the **job id that
`submit` reported** (§9.4) — which is exactly why `submit` must state the job id and the HPC folder
back to the user. Report the state and the current step once, then stop.

When the state is `complete`, close the loop by offering **both** retrieval routes (§9.4.2) — the capped
`download` (§9.4.6) and the full-tree `rsync` the user runs themselves — followed by the reminder that
`cleanup` can free the run's scratch once the data is safely local. Offer; do not start either.

### 9.6 Python API — deltas from §7

The `slurm` skill keeps most of §7 but necessarily departs on two points:

- **Still applies:** Python **standard library only, plus `pyyaml`**; an `argparse` CLI with one clear
  entry point; writing nothing outside the paths the user named.
- **Differs — network calls.** §7's "no network calls at runtime" is a *pipeline*-skill rule. Remote
  calls over SSH are this skill's entire purpose, so that rule does not apply here.
- **Differs — determinism.** This skill's output is remote side effects, not byte-identical files, so
  §7's determinism rule is replaced by: **echo every remote command to the user before it runs**, and
  **confirm every state-changing command** (create, overwrite, submit, remove) first (§9.3).
- **How confirmation works — the `--confirm` gate.** Every state-changing subcommand (`transfer`,
  `download`, `submit`, `cancel`, `cleanup`) runs in two steps: **without `--confirm` it does the
  read-only probes, prints the exact plan — host, target paths, the command it would run, sizes — and
  exits changing nothing.** The skill shows that plan to the user, and only after they agree does it
  re-run the same command with `--confirm`. Never pass `--confirm` on the first invocation; the flag
  *is* the user's permission, so inventing it defeats §9.3. Replacing files that already exist needs a
  second, separate flag (`--overwrite`) — remote ones for `transfer`, a non-empty local directory for
  `download` — and `job_status` is read-only and needs no gate.
- **Limits live in named constants**, never inline: `MAX_JOBS` (§9.4.3), `MAX_DOWNLOAD_BYTES` and
  `DEFAULT_MAX_FILE_SIZE_BYTES` and `DOWNLOAD_SKIP_DIRS` (§9.4.6), the cleanup allow-list sets
  (§9.4.1), and `USER_DIR_PREFIXES` (§9.3). A cap may be tightened by a flag but **never raised past
  its constant** — `MAX_DOWNLOAD_BYTES` in particular has no override.
- Shell out to the system `ssh` / `scp` / `rsync` binaries via `subprocess` with an **argument list,
  never `shell=True`** — that is what makes the quoting rule in §9.3 enforceable. No third-party SSH
  library.
- Fail loudly and stop. On a guard violation, an auth failure, or a non-zero remote exit status,
  report what happened and halt — never retry with a weaker check, a different auth method, or a
  broadened path.
