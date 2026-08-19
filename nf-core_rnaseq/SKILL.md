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
  `build_job.py` fills the matching `fasta`+`gtf` from the shared `<repo-root>/assets/genomes.json`.
  If `--species` is omitted, it is **inferred** from a species/organism column in the samplesheet or a
  `--metadata file.tsv` (scientific names like *Mus musculus* are recognised). For any other genome,
  give explicit paths with `--set fasta=... --set gtf=...` (these override `--species`).
  `templates/params.yml` seeds neither, so **the build hard-errors** if no species can be resolved and
  neither path was set — rather than emitting a `params.yml` with no genome.

## 3. Gather parameters
Ask the user for: the samplesheet path, a results directory on `/data`, the **species**
(`--species mouse|human` — or explicit `fasta`/`gtf` paths for any other genome), and any non-default
parameters. The **recommended** aligner is `star_rsem` (pipeline default is
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
(Use `--species human` for the human genome, or replace the auto-filled pair with
`--set fasta=... --set gtf=...`. To add a species or bump a reference release, edit
`<repo-root>/assets/genomes.json` only — it is shared by every species-dependent skill.)
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

**What feeds nf-core:differentialabundance.** The run's `out/<aligner>/` directory holds the two files a
downstream differential-abundance run consumes — `rsem.merged.gene_counts.tsv` +
`rsem.merged.gene_lengths.tsv` under `star_rsem/` (the recommended aligner), or
`salmon.merged.gene_counts.tsv` + `salmon.merged.gene_lengths.tsv` under `star_salmon/`. They become the
`nf-core_differentialabundance` skill's `matrix` and `transcript_length_matrix`, passed on **as written —
the counts are never rounded to integers**, because the gene lengths let DESeq2 model length bias.
DESIGN.md §6 is the authoritative table; mention the paths when handing back if the user plans that step,
including when the two jobs are chained on an `afterok` dependency (the path has to be written before the
file exists).

## Custom-config recommendations
(None specific to rnaseq yet. Scale `withLabel: 'process_high'` memory/cpus for very large genomes
or deep libraries as needed — see DESIGN.md §4.6.)
