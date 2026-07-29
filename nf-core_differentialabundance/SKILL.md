---
name: nf-core_differentialabundance
description: >-
  Build a SLURM job script + params.yml for an nf-core/differentialabundance run (UKDRI fork)
  on the UKDRI cluster. Use when the user wants differential expression / abundance analysis —
  triggers: "differentialabundance", "differential abundance", "differential expression", "DESeq2",
  "limma", "contrasts", "abundance matrix", "GSEA", "gprofiler2", plus "samplesheet", "params.yml",
  "slurm job". Produces files only; never runs the pipeline.
---

# nf-core:differentialabundance — job builder

## 1. Purpose
Generate a ready-to-submit SLURM job script (`run_nfcore_differentialabundance.sh`) and a validated
`params.yml` for one nf-core/differentialabundance run. This skill only produces files. The generated
job script is what the **`slurm` skill** uses to transfer the run to the HPC and submit it with
`sbatch`.

## Modified from upstream
This is a **substantially modified UKDRI fork** of nf-core/differentialabundance, tracked on the
`dev_ukdri` branch (version 1.5.0, commit `163d07f`) — **not** the stock public nf-core release.
Because of that:
- The valid parameter set, value enums, and defaults come **only** from the stored
  `assets/nextflow_schema.json` (the pinned `dev_ukdri` schema), **not** from the public nf-core
  docs at nf-co.re — some params differ. `build_job.py` validates against that stored schema.
- The pipeline `main.nf` in the job script points at a **dev build** on the cluster
  (`/nfsdata/scripts/nf-core/dev/differentialabundance/main.nf`), not a released tag.
- For usage guidance, use the **UKDRI wiki**:
  <https://wiki.informatics.ukdri.ac.uk/en/Pipelines/nfcore_differentialabundance>

## 2. Required inputs
Three distinct inputs (all prepared beforehand — see the `ena`/`geo`/`arrayexpress` skills for the
samplesheet):
- **`samplesheet.csv`** — the **observations** (samples) sheet, passed via `--input` (CLI flag in
  the run script). One row per observation; must include the sample-identifier column
  (`observations_id_col`, default `sample`) and any variables referenced by the contrasts.
- **`contrasts` CSV** — describes the comparisons to run. Columns: `variable,reference,target,blocking`
  where `variable` is a column of the samplesheet, `reference`/`target` are values in that column,
  and `blocking` is a colon-separated list of additional blocking variables (may be empty). Goes in
  `params.yml`.
- **`matrix` TSV** — the abundance matrix (features × samples; e.g. counts from nf-core/rnaseq).
  There must be a column for every row of the samplesheet. Goes in `params.yml`. (Not required when
  supplying CEL files for affy preprocessing.)

If any of these is missing, ask the user for it before building.

## 3. Gather parameters
Ask the user for: the samplesheet path (`--input`), a results directory on `/data`, the `contrasts`
CSV and `matrix` TSV paths, a `study_name`, and any non-default parameters. `study_type` defaults to
`rnaseq` (enum: `rnaseq`, `affy_array`, `maxquant`, `geo_soft_file`, `mass_spec`) — set it with
`--set study_type=...` only if the data is not RNA-seq. There is no UKDRI house recommendation for
this pipeline yet.

## 4. Generate `params.yml` (+ optional custom config)
Run the skill's Python API, which validates every key/value against
`assets/nextflow_schema.json` and writes only non-default values:

```bash
python3 scripts/build_job.py \
    --input /data/$USER/PROJECT/samplesheet.csv \
    --resdir /data/$USER/PROJECT/differentialabundance \
    --set contrasts=/data/$USER/PROJECT/contrasts.csv \
    --set matrix=/data/$USER/PROJECT/matrix.tsv \
    --set study_name=my_study \
    --dest /data/$USER/PROJECT/differentialabundance
```
- Unknown keys or out-of-enum values (e.g. `--set study_type=bogus`) are rejected with a hard error.
- To tune process resources, pass `--resource 'process_high:memory=128.GB'` (repeatable); this
  writes a `custom.config` and you then add `-c custom.config` to the run command (DESIGN.md §4.6).

## 5. Fill the SLURM template
`build_job.py` also writes the filled `run_nfcore_differentialabundance.sh` (samplesheet + resdir
lines set) into `--dest`. Confirm the `#SBATCH --time`/`--cpus-per-task` and the pinned dev `main.nf`
path (`/nfsdata/scripts/nf-core/dev/differentialabundance/main.nf` — verify on the cluster) suit the
run.

## 6. Hand back
Tell the user the paths of the generated `run_nfcore_differentialabundance.sh` and `params.yml`, and
that the **`slurm` skill** takes it from here: it transfers the job script, `params.yml`, the
samplesheet, `contrasts.csv` and the `matrix` TSV to the HPC, submits
`run_nfcore_differentialabundance.sh` with `sbatch` (from the directory holding `params.yml`, which the
script references by relative path), and reports the job id. Running `sbatch` on the cluster by hand is
equally fine. Never submit the job yourself from this skill.

## Custom-config recommendations
(None specific to differentialabundance yet. Scale process memory/cpus via `-c custom.config` for
very large matrices as needed — see DESIGN.md §4.6.)

## Species selection
If the analysis needs a GTF (feature annotation), pass `--species mouse|human` to fill `gtf`
(mm39 / hg38, Ensembl release-115), or give it explicitly with `--set gtf=...`.

If `--species` is omitted, it is inferred from a species/organism column in the samplesheet (or a `--metadata file.tsv`); scientific names such as *Mus musculus* / *Homo sapiens* are recognised. A file mixing species is not auto-selected — pass `--species` explicitly.
