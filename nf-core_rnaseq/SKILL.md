---
name: nf-core_rnaseq
description: >-
  Build a SLURM job script + params.yml for an nf-core/rnaseq run on the UKDRI cluster.
  Use when the user wants to run bulk RNA-seq quantification/alignment with nf-core:rnaseq —
  triggers: "rnaseq", "nf-core rnaseq", "bulk RNA-seq", "star_salmon", "star_rsem", "salmon",
  "gene counts", plus "samplesheet", "params.yml", "slurm job". Produces files only; never runs
  the pipeline.
---

# nf-core:rnaseq — job builder

## 1. Purpose
Generate a ready-to-submit SLURM job script (`run_nfcore_rnaseq.sh`) and a validated
`params.yml` for one nf-core/rnaseq run. This skill only produces files. The generated job script is
what the **`slurm` skill** uses to transfer the run to the HPC and submit it with `sbatch`.

## 2. Required inputs
- **`samplesheet.csv`** — prepared beforehand (see the `ena`/`geo`/`arrayexpress` skills). Columns:
  `sample,fastq_1,fastq_2,strandedness` (`strandedness` = `auto`|`forward`|`reverse`|`unstranded`).
- **Genome reference** — supplied by **species**: pass `--species mouse` or `--species human` and
  `build_job.py` fills the matching `fasta`+`gtf` (mm39 / hg38, Ensembl release-115 GTF). If
  `--species` is omitted, it is **inferred** from a species/organism column in the samplesheet or a
  `--metadata file.tsv` (scientific names like *Mus musculus* are recognised). For any other genome,
  give explicit paths with `--set fasta=... --set gtf=...` (these override `--species`).

## 3. Gather parameters
Ask the user for: the samplesheet path, a results directory on `/data`, the genome `fasta`/`gtf`,
and any non-default parameters. The **recommended** aligner is `star_rsem` (pipeline default is
`star_salmon`) — it is pre-set in `templates/params.yml`; confirm or override.

## 4. Generate `params.yml` (+ optional custom config)
Run the skill's Python API, which validates every key/value against
`assets/nextflow_schema.json` and writes only non-default values:

```bash
python3 scripts/build_job.py \
    --input /data/$USER/PROJECT/samplesheet.csv \
    --resdir /data/$USER/PROJECT/rnaseq \
    --species mouse \
    --dest /data/$USER/PROJECT/rnaseq
```
(Use `--species human` for hg38, or replace the auto-filled genome with `--set fasta=... --set gtf=...`.)
- Override the recommended aligner with `--set aligner=star_salmon` (must be one of the schema
  enum: `star_salmon`, `star_rsem`, `hisat2`, `bowtie2_salmon`).
- Unknown keys or out-of-enum values are rejected with a hard error.
- To tune process resources, pass `--resource 'process_high:memory=128.GB'` (repeatable); this
  writes a `custom.config` and you then add `-c custom.config` to the run command (§4.6 of DESIGN.md).

## 5. Fill the SLURM template
`build_job.py` also writes the filled `run_nfcore_rnaseq.sh` (samplesheet + resdir lines set) into
`--dest`. Confirm the `#SBATCH --time`/`--cpus-per-task` and the pinned `main.nf` version suit the run.

## 6. Hand back
Tell the user the paths of the generated `run_nfcore_rnaseq.sh` and `params.yml`, and that the
**`slurm` skill** takes it from here: it transfers both files to the HPC, submits
`run_nfcore_rnaseq.sh` with `sbatch` (from the directory holding `params.yml`, which the script
references by relative path), and reports the job id. Running `sbatch run_nfcore_rnaseq.sh` on the
cluster by hand is equally fine. Never submit the job yourself from this skill.

## Custom-config recommendations
(None specific to rnaseq yet. Scale `withLabel: 'process_high'` memory/cpus for very large genomes
or deep libraries as needed — see DESIGN.md §4.6.)
