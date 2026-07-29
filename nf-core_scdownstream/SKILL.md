---
name: nf-core_scdownstream
description: >-
  Build SLURM job scripts + params.yml files for an nf-core:scdownstream run on the UKDRI cluster.
  This is a SUBSTANTIALLY MODIFIED UKDRI fork with TWO sequential entry points. Use when the user
  wants single-cell downstream analysis (QC, doublet detection, integration, clustering, cell-type
  annotation) with nf-core:scdownstream — triggers: "scdownstream", "nf-core scdownstream",
  "single-cell downstream", "scvi integration", "celltypist", "cell type annotation", "clustering",
  "qc_clustering", "downstream", plus "samplesheet", "h5ad", "params.yml", "slurm job".
  Produces files only; never runs the pipeline.
---

# nf-core:scdownstream — job builder

## 1. Purpose
Generate ready-to-submit SLURM job scripts and validated `params_<entry>.yml` files for the
nf-core:scdownstream pipeline. This skill only produces files. The generated job scripts are what the
**`slurm` skill** uses to transfer each stage to the HPC and submit it with `sbatch`.

**This is a substantially modified UKDRI fork** (DESIGN.md §8), tracked on the **`dev_ukdri`** branch
of <https://github.com/UKDRI/scdownstream> (version `0.0.1dev`, pinned commit `3009f37`). Its
`main.nf` path and parameter set are **not** the stock upstream ones, so validate every parameter
against the stored `assets/nextflow_schema.json` (the fork's schema) — not the public nf-core docs.
UKDRI usage guidance lives at the wiki:
<https://wiki.informatics.ukdri.ac.uk/en/Pipelines/nfcore_scdownstream>.

## 2. Two entry points (§4.7)
scdownstream exposes **two distinct, sequential entry points**, selected with Nextflow's
`-entry <name>`. They are separate stages with different inputs and parameter sets — not
interchangeable modes. Each has its own job script and its own `params_<entry>.yml`.

| Entry | Required input flag | Input | Produces / consumes |
|---|---|---|---|
| `qc_clustering` | `--input` | `samplesheet.csv` | writes `…/out/integrated_scvi_finalized.h5ad` |
| `downstream` | `--base_adata` | that `.h5ad` | downstream analysis on the qc_clustering output |

Run order: `run_nfcore_scdownstream_qc_clustering.sh` first; its output
`integrated_scvi_finalized.h5ad` becomes the `--base_adata` input of
`run_nfcore_scdownstream_downstream.sh`.

## 3. Required inputs
- **`qc_clustering`** — a **`samplesheet.csv`** prepared beforehand (see the `ena`/`geo`/
  `arrayexpress` skills). It lists the per-sample single-cell input matrices (e.g. 10x `.h5`/`.mtx`
  or `.h5ad`) to QC, integrate and cluster. If missing, direct the user to prepare it first.
- **`downstream`** — the **`integrated_scvi_finalized.h5ad`** written by a completed `qc_clustering`
  run, passed via `--base_adata`. If that file does not exist yet, the `qc_clustering` stage must be
  run first.

## 4. Gather parameters
Ask the user for: the input path (samplesheet for `qc_clustering`, the finalized `.h5ad` for
`downstream`), a results directory on `/data`, and any non-default parameters. Common non-defaults
(pre-set in the shipped `templates/params_<entry>.yml`, confirm or override):

- `qc_clustering`: `name`, `species`, `celltypist_model`, `clustering_resolutions`,
  `automatic_cell_filtering`.
- `downstream`: `name`, `species`, `selected_clustering`, `celltypist_model`.

## 5. Generate `params_<entry>.yml` (+ optional custom config)
Run the skill's Python API with `--entry`. It validates every key/value against
`assets/nextflow_schema.json` (the fork's schema) and writes only non-default values.

**qc_clustering:**
```bash
python3 scripts/build_job.py --entry qc_clustering \
    --input /data/$USER/PROJECT/scdownstream/samplesheet_scdownstream.csv \
    --resdir /data/$USER/PROJECT/scdownstream/qc_clustering \
    --dest   /data/$USER/PROJECT/scdownstream/qc_clustering
```

**downstream** (input = the h5ad from qc_clustering):
```bash
python3 scripts/build_job.py --entry downstream \
    --input /data/$USER/PROJECT/scdownstream/qc_clustering/out/integrated_scvi_finalized.h5ad \
    --resdir /data/$USER/PROJECT/scdownstream/downstream \
    --dest   /data/$USER/PROJECT/scdownstream/downstream
```

- Add or override any parameter with `--set key=value` (repeatable), e.g.
  `--set species=human --set selected_clustering=leiden_1.0`.
- Unknown keys or out-of-enum values are rejected with a hard error naming the offender.

### 5.1 `celltypist_model` value check
`celltypist_model` is a free-text value checked (advisory, **warn — never error**) against
`assets/celltypist_models.json`:

1. a value containing a path separator `/` is treated as a **custom-model file path** and accepted
   (no name check), e.g. `--set celltypist_model=/data/$USER/models/my_model.pkl`;
2. otherwise a trailing `.pkl` is normalised and the name is matched against the known CellTypist
   models (e.g. `Mouse_Whole_Brain`, `Human_Lung_Atlas`) — a match is a valid built-in model;
3. an unknown name **warns** ("not in the CellTypist model list; for a custom model give a file
   path instead") but the value **is still written** to `params_<entry>.yml`. The list is a
   refreshable snapshot, so a legitimate-but-unlisted name is not an error.

## 6. Fill the SLURM template
`build_job.py` also writes the filled job script into `--dest`: the input-path line
(`samplesheet=` for `qc_clustering`, `h5adf=` for `downstream`) and the `resdir=` line are set from
your `--input`/`--resdir`. Both scripts already pin the dev `main.nf`
(`/nfsdata/scripts/nf-core/dev/scdownstream/main.nf`), use `-profile apptainer,gpu`, place
`-entry <name>` first, and reference `params_<entry>.yml`. Confirm the `#SBATCH --time`/
`--cpus-per-task` suit the run.

## 7. Custom-config recommendations
- **Large datasets (> 250,000 cells):** bump the per-process memory limit to `225.GB` via a custom
  process-resource config (DESIGN.md §4.6). The `#SBATCH` header sizes only the Nextflow driver job;
  a `-c` config sizes the individual per-process cluster jobs that actually do the work. Generate one
  with, e.g.:
  ```bash
  python3 scripts/build_job.py --entry qc_clustering ... \
      --resource process_high:memory=225.GB
  ```
  which writes a `custom.config`; then add `-c custom.config` to the `nextflow run` command (each job
  script has a commented `-c $conf` line ready to uncomment). Alternatively point `conf=` at your own
  `custom.config`. See `assets/base.config` for the default per-process resources and the valid
  `withName`/`withLabel` selectors.

## 8. Hand back
Tell the user the paths of the generated `run_nfcore_scdownstream_<entry>.sh` and
`params_<entry>.yml`, and that the **`slurm` skill** submits each stage: it transfers a stage's script
and its `params_<entry>.yml` together (the script references that file by relative path) and runs
`sbatch` from that directory. The two stages are **sequential** — submit
`run_nfcore_scdownstream_qc_clustering.sh` first, and only once its
`integrated_scvi_finalized.h5ad` exists submit `run_nfcore_scdownstream_downstream.sh` with that file
as `--base_adata`. Use the `slurm` skill's `job_status` on the first job id to know when it has
completed. Running each `sbatch` by hand is equally fine. Never submit the jobs yourself from this
skill.

## Species selection
Pass `--species mouse|human` to set the `species` field (applies to both entry points). The
pipeline default is `human`, so `--species human` leaves `species` at its default (omitted from
params.yml); `--species mouse` writes `species: mouse`. `--set species=...` also works.

If `--species` is omitted, it is inferred from a species/organism column in the samplesheet (or a `--metadata file.tsv`); scientific names such as *Mus musculus* / *Homo sapiens* are recognised. A file mixing species is not auto-selected — pass `--species` explicitly.
