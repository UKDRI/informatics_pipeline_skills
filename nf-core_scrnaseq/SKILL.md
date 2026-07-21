---
name: nf-core_scrnaseq
description: >-
  Build a SLURM job script + params.yml for an nf-core/scrnaseq run on the UKDRI cluster.
  Use when the user wants to run single-cell RNA-seq quantification/alignment with
  nf-core:scrnaseq — triggers: "scrnaseq", "nf-core scrnaseq", "single-cell RNA-seq", "10x",
  "cellranger", "simpleaf", "alevin", "kallisto", "star solo", "cell counts", plus "samplesheet",
  "params.yml", "slurm job". Produces files only; never runs the pipeline.
---

# nf-core:scrnaseq — job builder

## 1. Purpose
Generate a ready-to-submit SLURM job script (`run_nfcore_scrnaseq.sh`) and a validated
`params.yml` for one nf-core/scrnaseq run. The repo does not execute the pipeline; the user submits
the script with `sbatch` on the cluster.

## 2. Required inputs
- **`samplesheet.csv`** — prepared beforehand (see the `ena`/`geo`/`arrayexpress` skills). Columns:
  `sample,fastq_1,fastq_2,expected_cells` (`expected_cells` = expected number of cells per sample;
  a sample split across lanes uses one row per fastq pair with the same `sample` name).
- **Genome reference** — a genome `fasta` and matching `gtf` annotation (paths on the cluster).
  With the recommended `cellranger` aligner the reference must be **10x-compatible** (Cell Ranger
  builds/uses its own reference from the `fasta`/`gtf`); if missing, ask the user for them before
  building.

## 3. Gather parameters
Ask the user for: the samplesheet path, a results directory on `/data`, the genome `fasta`/`gtf`,
and any non-default parameters. The **recommended** aligner is `cellranger` (pipeline default is
`simpleaf`) — it is pre-set in `templates/params.yml`; confirm or override.

## 4. Generate `params.yml` (+ optional custom config)
Run the skill's Python API, which validates every key/value against
`assets/nextflow_schema.json` and writes only non-default values:

```bash
python3 scripts/build_job.py \
    --input /data/$USER/PROJECT/samplesheet.csv \
    --resdir /data/$USER/PROJECT/scrnaseq \
    --set fasta=/data/$USER/genomes/genome.fa.gz \
    --set gtf=/data/$USER/genomes/genes.gtf.gz \
    --dest /data/$USER/PROJECT/scrnaseq
```
- Override the recommended aligner with `--set aligner=simpleaf` (must be one of the schema
  enum: `kallisto`, `star`, `simpleaf`, `cellranger`, `cellrangerarc`, `cellrangermulti`).
- Unknown keys or out-of-enum values are rejected with a hard error.
- To tune process resources, pass `--resource 'process_high:memory=128.GB'` (repeatable); this
  writes a `custom.config` and you then add `-c custom.config` to the run command (§4.6 of DESIGN.md).

## 5. Fill the SLURM template
`build_job.py` also writes the filled `run_nfcore_scrnaseq.sh` (samplesheet + resdir lines set) into
`--dest`. Confirm the `#SBATCH --time`/`--cpus-per-task` and the pinned `main.nf` version suit the run.

## 6. Hand back
Tell the user the paths of the generated `run_nfcore_scrnaseq.sh` and `params.yml`, and that they
submit with `sbatch run_nfcore_scrnaseq.sh` from the results directory.

## Custom-config recommendations
(None specific to scrnaseq yet. Scale `withLabel: 'process_high'` memory/cpus for large cell
numbers or many samples as needed — see DESIGN.md §4.6.)

## Species selection
Pass `--species mouse|human` to `build_job.py` to auto-fill the genome `fasta`+`gtf`
(mm39 / hg38, Ensembl release-115). Override with `--set fasta=... --set gtf=...`. Note the
recommended `aligner: cellranger` also needs a matching 10x-compatible reference.

If `--species` is omitted, it is inferred from a species/organism column in the samplesheet (or a `--metadata file.tsv`); scientific names such as *Mus musculus* / *Homo sapiens* are recognised. A file mixing species is not auto-selected — pass `--species` explicitly.
