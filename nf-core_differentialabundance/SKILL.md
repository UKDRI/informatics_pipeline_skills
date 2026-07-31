---
name: nf-core_differentialabundance
description: >-
  Build a SLURM job script + params.yml for an nf-core/differentialabundance run (UKDRI fork)
  on the UKDRI cluster. Use when the user wants differential expression / abundance analysis —
  triggers: "differentialabundance", "differential abundance", "differential expression", "DESeq2",
  "limma", "contrasts", "abundance matrix", "GSEA", "gprofiler2", "gene set enrichment", "mass_spec",
  "proteomics", "DIA", "quantms", plus "samplesheet", "params.yml", "slurm job".
  Produces files only; never runs the pipeline.
---

# nf-core:differentialabundance — job builder

## 1. Purpose
Generate a ready-to-submit SLURM job script (`run_nfcore_differentialabundance.sh`) and a validated
`params.yml` for one nf-core/differentialabundance run. This skill only produces files. The generated
job script is what the **`slurm` skill** uses to transfer the run to the HPC and submit it with
`sbatch`.

## Modified from upstream
This is a **substantially modified UKDRI fork** of nf-core/differentialabundance, tracked on the
`dev_ukdri` branch (version 1.5.0, commit `4c3883c`) — **not** the stock public nf-core release.
Because of that:
- The valid parameter set, value enums, and defaults come **only** from the stored
  `assets/nextflow_schema.json` (the pinned `dev_ukdri` schema), **not** from the public nf-core
  docs at nf-co.re — some params differ. `build_job.py` validates against that stored schema.
- The pipeline `main.nf` in the job script points at a **dev build** on the cluster
  (`/nfsdata/scripts/nf-core/dev/differentialabundance/main.nf`), not a released tag.
- **`study_type: mass_spec` is a fork addition** (upstream 1.5.0 offers only `rnaseq`,
  `affy_array`, `maxquant`, `geo_soft_file`). It routes DIA proteomics through limma, which is why
  it needs its own results-column names — see §4.1 below. `limma_normalisation` is likewise
  fork-only (its default already matches the UKDRI chain, so the skill does not set it).
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
  supplying CEL files for affy preprocessing.) For `--study-type mass_spec` the feature-ID column must
  be named `Genes` — see §4.1 below.

If any of these is missing, ask the user for it before building.

## 3. Gather parameters
Ask the user for: the samplesheet path (`--input`), a results directory on `/data`, the `contrasts`
CSV and `matrix` TSV paths, a `study_name`, the **species** (`--species mouse|human`), the
**study type** (`--study-type`, see §4.1 below), and any other non-default parameters.

UKDRI house recommendations, applied automatically from `templates/params.yml` and overridable with
`--set`:

| Parameter | Pipeline default | Recommended |
|---|---|---|
| `gprofiler2_run` | `false` | `true` |
| `gprofiler2_min_diff` | `1` | `5` |

## 4. Generate `params.yml` (+ optional custom config)
Run the skill's Python API. It rejects unknown keys and out-of-enum values against
`assets/nextflow_schema.json`, and writes only values that differ from the effective runtime default in
`assets/nextflow.config`:

```bash
python3 scripts/build_job.py \
    --species mouse \
    --study-type rnaseq \
    --input /data/$USER/PROJECT/samplesheet.csv \
    --resdir /data/$USER/PROJECT/differentialabundance \
    --set contrasts=/data/$USER/PROJECT/contrasts.csv \
    --set matrix=/data/$USER/PROJECT/matrix.tsv \
    --set study_name=my_study \
    --dest /data/$USER/PROJECT/differentialabundance
```
- `contrasts`, `matrix` and `study_name` ship as `/data/$USER/PROJECT/…` placeholders in the template.
  Nextflow does **not** expand `$USER` in a params file, so always override all three with `--set`
  (as above) or hand-edit them before submitting.
- Unknown keys or out-of-enum values (e.g. `--set study_type=bogus`) are rejected with a hard error.
- To tune process resources, pass `--resource 'process_high:memory=128.GB'` (repeatable); this
  writes a `custom.config` and you then add `-c custom.config` to the run command (DESIGN.md §4.6).

### 4.1 Study type / assay
`study_type` (enum: `rnaseq`, `affy_array`, `maxquant`, `geo_soft_file`, `mass_spec`; default
`rnaseq`) selects the assay. Pass it as `--study-type <value>`; `--set study_type=<value>` is
equivalent, and giving both with different values is an error.

Beyond writing the parameter (when it is non-default — `rnaseq` is the default, so it is
omitted), the choice layers a matching
`templates/params_<study_type>.yml` file of recommended values over the base `params.yml`, and
switches which species files are used:

| `--study-type` | Overlay file | Effect |
|---|---|---|
| `rnaseq` (default) | *(none needed)* | DESeq2's defaults already fit |
| `mass_spec` | `params_mass_spec.yml` | limma results columns (`logFC` / `P.Value` / `adj.P.Val`), the exploratory assay chain ending in `vsn`, and all four feature columns → `Genes`. Also switches the species-filled gene sets and background, and drops `gtf` — see "Species selection" |
| `affy_array`, `maxquant`, `geo_soft_file` | *(none yet)* | base recommendations only |

`limma_normalisation` is **not** set: the pipeline default is already
`median,quantile,cyclic_loess,vsn`, so setting it would be a no-op.

For `mass_spec`, `features_id_col`, `features_metadata_cols`, `differential_feature_id_column` and
`differential_feature_name_column` are all set to `Genes` — the DIA-NN / quantms column, which is
also what the gene-symbol GMT and the gene-name background are keyed on. **The abundance matrix must
therefore carry a `Genes` column** — those names are used as-is, with no GTF and no ID conversion. If the user's proteomics matrix keys rows
on something else (e.g. `Protein.Group`), override all four with `--set`.

To add recommended *values* for another assay later, drop a `templates/params_<study_type>.yml` file
in — no code change is needed. An assay that also needs *different reference files* additionally needs
one line in `CONFIG["variants"]["species_map"]` in `scripts/build_job.py`.

### 4.2 Gene set enrichment (gprofiler2)
Enrichment is **on by default in this skill** — `gprofiler2_run: true` is a UKDRI recommendation; the
pipeline default is `false`. The gene sets come from the curated UKDRI gProfiler GMTs, picked from the
species *and* the study type:

| `--study-type` | gene sets (`gene_sets_files`) | background (`gprofiler2_background_file`) |
|---|---|---|
| every other value | `gene_sets_ensg` — GMT keyed on Ensembl gene IDs | `auto` — the filtered abundance matrix |
| `mass_spec` | `gene_sets_name` — GMT keyed on gene symbols | `background_gene_names` — a gene-symbol list |

Note the switch is on the literal value `mass_spec`, not on "is it proteomics": `maxquant` is
proteomics but gets the Ensembl-ID GMT and the `auto` background.

Notes:
- Because a GMT is always supplied, the skill deliberately leaves `gprofiler2_organism` and
  `gprofiler2_token` **unset** — either would take priority over `gene_sets_files` and silently
  replace the curated gene sets with a live g:Profiler query.
- Restrict the sources with e.g. `--set gprofiler2_sources=KEGG,REAC` if the user asks.
- To skip enrichment entirely: `--set gprofiler2_run=false`.
- GSEA (`gsea_run`, pipeline default `false`) is a separate route but reads the **same**
  `gene_sets_files` parameter. Since that is always filled from `--species`, enabling GSEA would run it
  against the full gProfiler GMT; override `gene_sets_files` with a GSEA-appropriate set (it accepts a
  comma-separated list) if the user wants one.

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
This is the single place the species→file mapping is defined; §4.1 and §4.2 refer back to it.

`--species mouse|human` fills these parameters from the shared `<repo-root>/assets/genomes.json`,
by its key names — the paths themselves live only in that file:

| Parameter | `genomes.json` key | When |
|---|---|---|
| `gtf` | `gtf` | every study type **except** `mass_spec` |
| `gene_sets_files` | `gene_sets_ensg` | every study type except `mass_spec` |
| `gene_sets_files` | `gene_sets_name` | `--study-type mass_spec` |
| `gprofiler2_background_file` | `background_gene_names` | `--study-type mass_spec` only; otherwise left at its `auto` default |

So either way exactly two parameters are species-filled: `gtf` + `gene_sets_files` for RNA-seq, and
`gene_sets_files` + `gprofiler2_background_file` for `mass_spec`. Override any of them with `--set`,
which always wins.

**No GTF for `mass_spec`.** Proteomics takes the gene name directly from the matrix's `Genes` column
with no ID conversion, so no annotation is needed and `gtf` is deliberately left unset. Supplying one
anyway with `--set gtf=...` still works if a run needs it.

If `--species` is omitted, it is inferred from a species/organism column in the samplesheet (or a
`--metadata file.tsv`); scientific names such as *Mus musculus* / *Homo sapiens* are recognised. A
file mixing species is not auto-selected — pass `--species` explicitly.

Because a wrong-species GMT would produce plausible-looking but meaningless enrichment, the script
**hard-errors** if no species can be resolved and any mapped parameter would be left unset. Either
pass `--species`, add an organism column, or set the paths explicitly.

To add a species or bump a reference release, edit `<repo-root>/assets/genomes.json` only — it is
shared by every species-dependent skill and no Python change is needed.
