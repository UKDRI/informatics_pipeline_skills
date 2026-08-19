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
- **`contrasts` CSV** — describes the comparisons to run. Columns
  `id,variable,reference,target,blocking` (plus the optional `exclude_samples_col` /
  `exclude_samples_values`), where `id` names the contrast's output files (see §2.1), `variable` is a
  column of the samplesheet, `reference`/`target` are values in that column, and `blocking` is a
  **semicolon**-separated list of additional blocking variables (may be empty). Goes in `params.yml`.
  Only `variable`, `reference` and `target` are structurally required; `id` is **optional to the
  pipeline** — which invents one from the raw values when it is missing — but this skill always writes
  it, because the invented one lands in every output path. Generate the sheet with
  `scripts/contrasts.py build` (§2.1) rather than by hand.
  *Delimiter note:* the pinned `assets/nextflow_schema.json` `help_text` says "colon-separated" — it
  is stale and the asset is a verbatim copy, so it is not edited. Both R templates split on `;`
  (`strsplit(opt$blocking_variables, split = ';')` in `deseq_de.R` and `limma_de.R`). A colon list is
  **not** rejected: it is read as one variable name, `make.names()` mangles it, and the model is
  silently wrong.
- **`matrix` TSV** — the abundance matrix (features × samples). There must be a column for every row
  of the samplesheet. Goes in `params.yml`. (Not required when supplying CEL files for affy
  preprocessing.) For RNA-seq this is the **merged gene counts matrix** from the nf-core/rnaseq run —
  `star_rsem/rsem.merged.gene_counts.tsv` or `star_salmon/salmon.merged.gene_counts.tsv` under that
  run's `out/`, depending on its aligner (DESIGN.md §6 is the authoritative list). Hand the counts over
  **exactly as rnaseq wrote them: do not round them to integers and do not pre-process them.** For
  `--study-type mass_spec` the feature-ID column must be named `Genes` — see §4.1 below.
- **gene lengths TSV** (`transcript_length_matrix`) — **RNA-seq only**, and the recommended companion to
  the counts matrix: the `*.merged.gene_lengths.tsv` sitting beside it in the *same* aligner directory.
  Optional to the pipeline, but supplying it is what lets DESeq2 model gene-length bias across samples —
  and is why the counts need no integer rounding. Goes in `params.yml`; seeded as a placeholder by
  `templates/params_rnaseq.yml` (§4.1). Leave it unset only when the counts did not come from
  nf-core/rnaseq and no matching lengths file exists.

If any of these is missing, ask the user for it before building.

### 2.1 Contrast ids
A contrast's `id` is not cosmetic — it is `ext.prefix` for `DESEQ2_DIFFERENTIAL`,
`LIMMA_DIFFERENTIAL` and `FILTER_DIFFTABLE`, which the R templates paste straight into filenames
(`<id>.deseq2.results.tsv`, `<id>.limma.results.tsv`, `<id>.deseq2.model.txt`), **and** a
`publishDir` path component for `GPROFILER2_GOST` and `PROTEUS`. `GSEA_GSEA` uses
`"${meta.id}.${gene_sets.baseName}."`. So an id carrying `/`, `;`, `:`, a space or a shell
metacharacter yields broken paths, stray nested directories, or results the user cannot glob — and
nothing upstream catches it: the fork ships no `schema_contrasts.json`, and when the column is empty
`workflows/differentialabundance.nf` invents an id with `it.values().join('_')`, raw observation
values and all.

**The quiet failure matters more than the loud one.** The report Rmd looks each contrast's results up
as `paste0(gsub(' |;', '_', d), differential_file_suffix)`, while the modules write `meta.id`
**verbatim** — so an id containing a space or a `;` makes the report look for a filename that was never
written. The run succeeds, nothing errors, and that contrast is just absent from the report. (The GSEA
table names use the id verbatim, so upstream disagrees with itself here.) Writing the `id` column is
safe: the report derives its own only when the column is missing
(`if (! 'id' %in% colnames(contrasts))`).

**House convention** — `variable__target__vs__reference`, with `__block__<b1>__<b2>…` appended when
`blocking` is set:

```csv
id,variable,reference,target,blocking
condition__treated__vs__control,condition,control,treated,
condition__treated__vs__control__block__sex__batch,condition,control,treated,sex;batch
Braak_stage__Braak_5-6__vs__braak0,Braak stage,braak0,Braak 5-6,
```

- separator `__` (double underscore); target before reference, because that is the direction of the
  reported fold change; the literal token `block` marks the start of the blocking-variable list;
- **every** id — generated or hand-written — may contain only `[A-Za-z0-9._-]`. `-` and `.` are
  allowed on purpose: an id is only pasted into filenames and used as an R list name, never passed
  through `make.names()`, so neither gets mangled downstream;
- **when an id is generated**, runs of anything else collapse to a single `_` and runs of `_` collapse
  to one (`AD/CTRL` → `AD_CTRL`, `Braak 5-6` → `Braak_5-6`), so a generated token never contains `__`
  and the separator stays unambiguous. That is a property of generation only — `check` validates the
  charset and uniqueness, not the shape, so a hand-written id containing `__` is accepted as it is;
- ids must be **unique** — two contrasts sharing one id overwrite each other's output files;
- only the `id` is sanitized. `variable`, `reference`, `target` and `blocking` keep the **verbatim**
  samplesheet spellings, since the pipeline matches them against the observations table.

**Generate them, don't type them:**

```bash
# from a draft sheet holding just variable,reference,target[,blocking] — never modified
python3 scripts/contrasts.py build --in draft_contrasts.csv --dest /data/$USER/PROJECT
# or straight from the contrasts you agreed with the user
python3 scripts/contrasts.py build \
    --contrast 'variable=condition,reference=control,target=treated' \
    --contrast 'variable=condition,reference=control,target=treated,blocking=sex;batch' \
    --dest /data/$USER/PROJECT
# validate a sheet the user already has (exit 1 on error)
python3 scripts/contrasts.py check --contrasts contrasts.csv
```

`build` writes `<dest>/contrasts.csv` (or `--out-name`) with the `id` column first; it keeps a
pre-existing id that is already safe (`--rebuild-ids` regenerates every id to the convention) and
reports every id it derived or replaced. **This is the one place an unsafe id is repaired rather than
rejected** — that is what `build` is for; it warns on each replacement and never touches the `--in`
file.

`check` — the same validator — only ever reads, so it **hard-errors** instead: on an unsafe or
duplicate id, an empty id, a missing required column, and a colon-separated `blocking`. It **warns**
when there is no `id` column at all (the pipeline tolerates that and invents ids, so it is not an
error), on an unrecognised column, and on a blocking variable R's `make.names()` would rewrite.

`build_job.py` runs the same check on the `contrasts` path automatically and **refuses to write
`params.yml`** if it fails. When that path is a cluster path (the usual case) there is nothing to
read locally, so it says so — run `contrasts.py check` on the local copy before transferring.

**One divergence to know about.** The pipeline strips `NA` from the `blocking` column with
`it.blocking.replace('NA', '')`, which removes the *substring* — so a blocking variable actually named
`NAcc` becomes `cc` in the model while the generated id keeps `NAcc`. `contrasts.py` treats only a
whole value of `NA` as "no blocking" and warns when a name contains `NA`; renaming the observations
column is the only real fix.

## 3. Gather parameters
Ask the user for: the samplesheet path (`--input`), a results directory on `/data`, the `contrasts`
CSV and `matrix` TSV paths, the gene lengths TSV for an RNA-seq run (`transcript_length_matrix`, §2), a
`study_name`, the **species** (`--species mouse|human`), the **study type** (`--study-type`, see §4.1
below), and any other non-default parameters.

If the contrasts still have to be written — or the user's sheet has no `id` column — build it first
with `scripts/contrasts.py build` (§2.1), then pass that file to `build_job.py`.

UKDRI house recommendations, applied automatically from `templates/params.yml` and overridable with
`--set`:

| Parameter | Pipeline default | Recommended |
|---|---|---|
| `gprofiler2_run` | `false` | `true` |
| `gprofiler2_min_diff` | `1` | `5` |
| `transcript_length_matrix` | *unset* | the rnaseq gene lengths TSV (RNA-seq runs; §2) |

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
    --set matrix=/data/$USER/PROJECT/rnaseq/out/star_rsem/rsem.merged.gene_counts.tsv \
    --set transcript_length_matrix=/data/$USER/PROJECT/rnaseq/out/star_rsem/rsem.merged.gene_lengths.tsv \
    --set study_name=my_study \
    --dest /data/$USER/PROJECT/differentialabundance
```
- `contrasts`, `matrix`, `study_name` — and, for RNA-seq, `transcript_length_matrix` — ship as
  `/data/$USER/PROJECT/…` placeholders in the templates. Nextflow does **not** expand `$USER` in a params
  file, so always override every one of them with `--set` (as above) or hand-edit them before submitting.
- Unknown keys or out-of-enum values (e.g. `--set study_type=bogus`) are rejected with a hard error.
- If the `contrasts` path is a readable local file it is validated first (§2.1); a bad contrast id
  aborts the build and no `params.yml` is written.
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
| `rnaseq` (default) | `params_rnaseq.yml` | the nf-core/rnaseq handoff: `matrix` (merged gene counts) + `transcript_length_matrix` (merged gene lengths) as `star_rsem/…` placeholders — override both with `--set`. DESeq2's own defaults already fit, so nothing else is set |
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
samplesheet, the `contrasts.csv` that `contrasts.py build` wrote (§2.1), the `matrix` TSV and — for an
RNA-seq run — the gene lengths TSV to the HPC, submits
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
