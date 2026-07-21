# informatics_pipeline_skills

A collection of Claude Code **skills**, one per Nextflow nf-core-style pipeline, that help you
assemble everything needed to run a pipeline job on the UKDRI SLURM cluster. Each skill produces a
ready-to-submit **SLURM job script** and a validated **`params.yml`** (plus, optionally, a custom
process-resource config). **The repository never runs a pipeline** — it only generates these
artifacts, which you submit yourself with `sbatch`.

## Pipelines

| Skill | Pipeline |
|---|---|
| `nf-core_rnaseq` | bulk RNA-seq |
| `nf-core_scrnaseq` | single-cell RNA-seq |
| `nf-core_scdownstream` | single-cell downstream analysis *(UKDRI-modified)* |
| `nf-core_differentialabundance` | differential abundance *(UKDRI-modified)* |
| `nf-core_spatialvi` | spatial transcriptomics |
| `bigbio_quantmsdiann` | DIA proteomics (DIA-NN) |

Each pipeline folder contains its skill definition, job-script template, and pinned reference files.

## Key features

- **Validated parameters** — a `params.yml` holds only the values that differ from the pipeline
  defaults. Every parameter name and value is checked against the pipeline's own definition;
  unknown parameters or invalid choices are rejected.
- **Recommended defaults** — each skill ships the UKDRI-recommended settings (e.g. rnaseq
  `aligner: star_rsem`, scrnaseq `aligner: cellranger`), applied automatically and easy to override.
- **Species-aware genome selection** — pick mouse or human and the matching genome/annotation files
  are filled in for you; the species can also be inferred from a samplesheet or metadata file
  (scientific names like *Mus musculus* are recognised). Custom paths are always allowed.
- **Custom resource tuning (optional)** — request more CPUs, memory, or wall-time for specific
  processes when a dataset needs it, without changing the pipeline.
- **Multiple entry points** — pipelines with more than one workflow (e.g. scdownstream's
  `qc_clustering` → `downstream`) get one job script per entry point.
- **Reproducible references** — each skill pins the exact pipeline version (and commit, for
  in-development pipelines) so generated jobs match what actually runs.

## Usage

Invoke the relevant skill in Claude Code and provide your inputs (typically a `samplesheet.csv`
prepared beforehand, e.g. via the `ena`, `geo`, `arrayexpress`, or `pride` data-retrieval skills).
The skill gathers your choices, generates the job script and `params.yml`, and hands back the file
paths to submit with `sbatch`.

## For contributors

House style, conventions, and the full specification live in **[`DESIGN.md`](DESIGN.md)**. Read it
before authoring or modifying any skill.
