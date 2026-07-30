# informatics_pipeline_skills

A collection of Claude Code **skills** for running Nextflow nf-core-style pipelines on the UKDRI SLURM
cluster. There are two kinds:

- **Pipeline skills** — one per pipeline. Each produces a ready-to-submit **SLURM job script** and a
  validated **`params.yml`** (plus, optionally, a custom process-resource config). They generate files
  and nothing else.
- **The `slurm` skill** — runs those job scripts on the cluster: transfer, submit, job status, cancel,
  and cleanup of intermediate files.

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

## Cluster operations — the `slurm` skill

| Command | Does |
|---|---|
| `transfer` | upload job scripts, params, samplesheets and input data to the HPC |
| `download` | pull a results directory back — scanned first, big files excluded, max 2 GB |
| `submit` | `sbatch` the job script from its own directory; reports the HPC folder and job id |
| `job_status` | SLURM state (pending/running/complete/fail/node_fail) plus the current pipeline step |
| `cancel` | `scancel` one job, then suggest cleaning up its work directory |
| `cleanup` | remove intermediate data (`work`, `out`, archives, dataset objects, …) |

It also ships a job template for unpacking `.zip`/`.tar.gz` input archives on the cluster.

**Safety, by design:** it always asks for your username and hostname and never guesses them; it never
uses passwords (passwordless SSH is yours to configure); it refuses to read from or write to anything
outside your own directories or at the top of a hierarchy; it never uses wildcards in a path; and it
changes nothing until it has shown you the exact command and you have confirmed it. Submissions are
capped at 100 jobs.

Downloads are deliberately narrow: only from your own directories **and only files you own** (both the
path and the file ownership are checked), scanned before anything moves, files over 500 MB excluded,
**2 GB total maximum**, and never started without your go-ahead. For the complete results tree — large
files included — you get an `rsync` command to run yourself.

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

Invoke the relevant pipeline skill in Claude Code and provide your inputs (typically a
`samplesheet.csv` prepared beforehand, e.g. via the `ena`, `geo`, `arrayexpress`, or `pride`
data-retrieval skills). It gathers your choices and generates the job script and `params.yml`.

Then use the `slurm` skill to transfer those files to the cluster and submit the job — it reports the
HPC folder and job id, and you check progress with `job_status` whenever you like. Submitting with
`sbatch` yourself works just as well.

## For contributors

House style, conventions, and the full specification live in **[`DESIGN.md`](DESIGN.md)**. Read it
before authoring or modifying any skill.
