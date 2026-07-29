---
name: bigbio_quantmsdiann
description: >-
  Build a SLURM job script + params.yml for a bigbio/quantmsdiann run on the UKDRI cluster.
  Use when the user wants to run DIA (data-independent acquisition) proteomics quantification
  with DIA-NN via bigbio:quantmsdiann — triggers: "quantmsdiann", "bigbio quantmsdiann",
  "DIA-NN", "DIA proteomics", "data-independent acquisition", "SDRF", "protein FASTA",
  "spectral library", plus "params.yml", "slurm job". Produces files only; never runs the
  pipeline.
---

# bigbio:quantmsdiann — job builder

## 1. Purpose
Generate a ready-to-submit SLURM job script (`run_bigbio_quantmsdiann.sh`) and a validated
`params.yml` for one bigbio/quantmsdiann run. quantmsdiann is a DIA-NN-based quantitative
mass-spectrometry workflow (bigbio, built to nf-core conventions) for **data-independent
acquisition (DIA) proteomics**: it takes annotated MS runs plus a protein sequence database,
predicts/uses a spectral library, and runs DIA-NN to produce precursor/peptide/protein
quantification matrices and a QC report. This skill only produces files. The generated job script is
what the **`slurm` skill** uses to transfer the run to the HPC and submit it with `sbatch`.
Pinned version: 2.2.0 (`main` branch).

## 2. Required inputs
- **SDRF sample table** (`--input`, must end `.sdrf.tsv`) — this is NOT a plain CSV samplesheet.
  It is a PRIDE Sample-to-Data-Relation-Format file describing each MS run and its experimental
  design, prepared beforehand (see the `pride` skill, which writes a project's SDRF). The pipeline
  reads acquisition method, labelling, enzyme, modifications and mass tolerances from the SDRF, and
  downloads/locates the spectrum files referenced in it. If missing, direct the user to the `pride`
  skill first; do not fabricate one.
- **Protein database** (`database`) — a protein sequence FASTA (`.fasta`/`.fa`) on the cluster.
  This is mandatory and is never part of the SDRF, so it must be supplied via `params.yml`. For DIA
  data the FASTA **must not** contain decoys (DIA-NN creates them internally); include contaminants
  as needed. If the user has not given a FASTA path, ask for it before building.

## 3. Gather parameters
Ask the user for: the SDRF path (`.sdrf.tsv`), a results directory on `/data`, and the protein
`database` FASTA path. Then any non-default DIA-NN / search parameters (e.g. `precursor_mass_tolerance`,
`fragment_mass_tolerance`, `pg_level`, `scoring_mode`, a precomputed `speclib`). There is no UKDRI
house recommendation for this pipeline yet, so the only value pre-set in `templates/params.yml` is
the mandatory `database` (an example path the user must edit).

## 4. Generate `params.yml` (+ optional custom config)
Run the skill's Python API, which validates every key/value against
`assets/nextflow_schema.json` and writes only non-default values:

```bash
python3 scripts/build_job.py \
    --input /data/$USER/PROJECT/PXD000000.sdrf.tsv \
    --resdir /data/$USER/PROJECT/quantmsdiann \
    --set database=/data/$USER/databases/UP000005640_9606.fasta \
    --dest /data/$USER/PROJECT/quantmsdiann
```
- `database` is required and has no default; leave the template's example in place only after
  editing it to a real FASTA, or override with `--set database=...`.
- Add non-default search/DIA-NN options with more `--set key=value` flags, e.g.
  `--set pg_level=1` or `--set scoring_mode=proteoforms` (must be one of the schema enum:
  `generic`, `proteoforms`, `peptidoforms`).
- Unknown keys or out-of-enum values are rejected with a hard error naming the offender.
- To tune process resources, pass `--resource 'process_high:memory=128.GB'` (repeatable); this
  writes a `custom.config` and you then add `-c custom.config` to the run command (DESIGN.md §4.6).

## 5. Fill the SLURM template
`build_job.py` also writes the filled `run_bigbio_quantmsdiann.sh` (the `sdrf=` and `resdir=` lines
set) into `--dest`. The run command uses only the allowed flags (`-profile apptainer`, `--input $sdrf`,
`--outdir $outdir`, `-params-file params.yml`, `-with-report`, `-resume`, and the commented optional
`-c $conf`). Confirm the `#SBATCH --time`/`--cpus-per-task` and the pinned `main.nf` version/path
(`/nfsdata/scripts/bigbio/quantmsdiann_2.2.0/main.nf` — confirm it exists on the cluster) suit the run.

## 6. Hand back
Tell the user the paths of the generated `run_bigbio_quantmsdiann.sh` and `params.yml`, and that the
**`slurm` skill** takes it from here: it transfers the job script, `params.yml` and the `.sdrf.tsv` to
the HPC, submits `run_bigbio_quantmsdiann.sh` with `sbatch` (from the directory holding `params.yml`,
which the script references by relative path), and reports the job id. That skill also unpacks a
compressed PRIDE download (`.zip`/`.tar.gz`) on the cluster if the `.raw`/`.d` data still needs
extracting. Running `sbatch` by hand is equally fine. Never submit the job yourself from this skill.

## Custom-config recommendations
(None specific to quantmsdiann yet. DIA-NN in-silico library generation and quantification can be
memory- and CPU-heavy for large experiments or big FASTA databases — scale the relevant
`withName`/`withLabel` memory/cpus/time as needed per DESIGN.md §4.6, using `assets/base.config` as
the reference for the default resources and available selectors.)
