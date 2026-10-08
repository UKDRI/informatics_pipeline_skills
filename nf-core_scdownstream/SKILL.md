---
name: nf-core_scdownstream
description: >-
  Build SLURM job scripts + params.yml files for an nf-core:scdownstream run on the UKDRI cluster.
  This is a SUBSTANTIALLY MODIFIED UKDRI fork with THREE sequential entry points. Use when the user
  wants single-cell downstream analysis (QC, doublet detection, integration, clustering, cell-type
  annotation, marker genes, enrichment, cell-cell communication) or pseudobulk differential gene
  expression per contrast with nf-core:scdownstream — triggers: "scdownstream", "nf-core
  scdownstream", "single-cell downstream", "scvi integration", "celltypist", "cell type annotation",
  "clustering", "qc_clustering", "downstream", "differential_genes", "differential expression",
  "pseudobulk", "PyDESeq2", "DESeq2 per cell type", "contrasts", "condition", "treatment",
  "sample metadata", plus "samplesheet", "h5ad", "params.yml", "slurm job".
  Produces files only; never runs the pipeline.
---

# nf-core:scdownstream — job builder

## 1. Purpose
Generate ready-to-submit SLURM job scripts and validated `params_<entry>.yml` files for the
nf-core:scdownstream pipeline. This skill only produces files. The generated job scripts are what the
**`slurm` skill** uses to transfer each stage to the HPC and submit it with `sbatch`.

**This is a substantially modified UKDRI fork** (DESIGN.md §8), tracked on the **`dev_ukdri`** branch
of <https://github.com/UKDRI/scdownstream> (version `0.0.1dev`, pinned commit `e101d8c`). Its
`main.nf` path and parameter set are **not** the stock upstream ones, so validate every parameter
against the stored `assets/nextflow_schema.json` (the fork's schema) — not the public nf-core docs.
UKDRI usage guidance lives at the wiki:
<https://wiki.informatics.ukdri.ac.uk/en/Pipelines/nfcore_scdownstream>.

**Cluster prerequisite:** the deployed `/nfsdata/scripts/nf-core/dev/scdownstream/main.nf` must be at
`e101d8c` or later. An older checkout has no `differential_genes` entry, no `--metadata`, and writes
the old output names.

## 2. Three entry points (§4.7)
scdownstream exposes **three sequential entry points**, selected with Nextflow's `-entry <name>`.
Each has its own job script and its own `params_<entry>.yml`; each consumes the previous stage's
output `.h5ad` via `--base_adata`.

| Stage | Entry | Required input | Writes into its `--outdir` (= `$resdir/out`) |
|---|---|---|---|
| 1 | `qc_clustering` | `--input` samplesheet.csv | `<NAME>_qc_clustering.h5ad` (+ `.rds`, QC/clustering report) |
| 2 | `downstream` | `--base_adata` = stage 1 h5ad | `<NAME>_downstream.h5ad` (+ `.rds`, `<NAME>_downstream_markers.json.gz`, report) |
| 3 | `differential_genes` | `--base_adata` = stage 2 h5ad, plus `diffgenes_contrasts` | per group × contrast `<NAME>_<group>_<contrast id>.tsv`, DE report |

**`<NAME>` is the `name` param of that stage; unset, it falls back to `scdownstream`** (the fork's
`conf/modules.config`: `"${params.name ?: 'scdownstream'}_<stage>"`). The stage outputs are
published to the root of `--outdir`, gzip-compressed.

**Deriving the next stage's input — do this, don't guess:**

```
--input of stage N+1 = <stage N resdir>/out/<stage N name>_<stage N entry>.h5ad
```

Ask the user for a short study name **once** and pass the same `--set name=<study>` to all three
stages, so both `--base_adata` paths are known before stage 1 has even run. The templates seed
`name: scdownstream`, so without `--set name=` the files are `scdownstream_qc_clustering.h5ad` and
`scdownstream_downstream.h5ad`.

## 3. Required inputs
- **`qc_clustering`** — a **`samplesheet.csv`** prepared beforehand (see the `ena`/`geo`/
  `arrayexpress` skills): columns `sample` and at least one of `filtered` / `unfiltered` (paths to
  `h5ad`, `h5`, `rds` or `csv` matrices). If missing, direct the user to prepare it first. Optional:
  a **per-sample metadata TSV** (§4).
- **`downstream`** — the stage 1 `<NAME>_qc_clustering.h5ad`.
- **`differential_genes`** — the stage 2 `<NAME>_downstream.h5ad` (it must hold a **`counts` layer**
  of raw counts; stage 1's normalisation step stores them there, so the pipeline's own outputs
  qualify — an object from elsewhere may not) and a **contrasts TSV** (§6).

## 4. Per-sample metadata (`qc_clustering` only) — ask, never assemble
`--metadata` adds every column of a per-sample TSV to the cells' `obs`. Those columns are what
`differential_genes` contrasts (condition, treatment, diagnosis) and blocks on (donor, sex), what
`umap_color_by` can plot, and what scVI can use as covariates. **Only `qc_clustering` reads it.**

1. **Ask the user** whether they have per-sample metadata, and show the expected format: a
   **tab-separated** file with a header and one row per samplesheet `sample`:
   ```tsv
   sample	condition	donor	sex	age
   sample1	control	D01	F	71
   sample2	treated	D02	M	68
   ```
   - The `sample` column holds the samplesheet ids (another name needs
     `--set metadata_sample_col=<col>`); every other column is added to `obs`.
   - Not allowed as column names: `batch`, `label`, `sample_original`, `outlier` (the pipeline makes
     them — e.g. use `seq_batch`); avoid QC-metric, `doublet_score`, `celltypist:*` and `leiden_*`
     names, which later steps overwrite.
2. **If they give one**, validate the local copy:
   ```bash
   python3 scripts/metadata.py check --metadata sample_metadata.tsv --input samplesheet.csv
   ```
   Report every error back for the user to fix **in their own file** — never edit, rebuild or
   "repair" it yourself. Then pass it to the build with `--metadata <path on the cluster>` (it is
   written into `params_qc_clustering.yml`; an `organism`/`species` column also drives species
   inference) and suggest `--set umap_color_by=<the key columns>`. `build_job.py` re-runs the same
   check whenever that path is readable locally.
3. **If they have none, warn plainly and carry on** — the run works without it, but:
   - there will be no condition/treatment column, so `differential_genes` can only contrast columns
     the pipeline makes itself (`sample`, `batch`, `label`, clusters, cell types);
   - adding metadata later means rerunning `qc_clustering` (with `-resume`, so QC and integration
     come from the cache).

   `build_job.py` prints the same warning when `qc_clustering` is built without `metadata`.

**Never** assemble a metadata file yourself — not from GEO characteristics, an SDRF, ENA/BioSamples
attributes, or anywhere else — unless the user explicitly asks you to.

## 5. Gather parameters and generate `params_<entry>.yml`
Ask the user for: the input path, a results directory on `/data`, the **study name**, the
**species** (`--species mouse|human`; stages 1 and 2), the metadata question (§4), and any
non-default parameters. The Python API validates every key/value against
`assets/nextflow_schema.json` and writes only non-default values. Add or override any parameter with
`--set key=value` (repeatable); unknown keys or out-of-enum values are a hard error.

**qc_clustering:**
```bash
python3 scripts/build_job.py --entry qc_clustering \
    --species mouse \
    --metadata /data/$USER/PROJECT/scdownstream/sample_metadata.tsv \
    --input  /data/$USER/PROJECT/scdownstream/samplesheet_scdownstream.csv \
    --resdir /data/$USER/PROJECT/scdownstream/qc_clustering \
    --dest   /data/$USER/PROJECT/scdownstream/qc_clustering \
    --set name=study1 --set umap_color_by=condition,sex
```

**downstream** (input derived per §2):
```bash
python3 scripts/build_job.py --entry downstream \
    --species mouse \
    --input /data/$USER/PROJECT/scdownstream/qc_clustering/out/study1_qc_clustering.h5ad \
    --resdir /data/$USER/PROJECT/scdownstream/downstream \
    --dest   /data/$USER/PROJECT/scdownstream/downstream \
    --set name=study1
```

**differential_genes** (input derived per §2; no `--species`):
```bash
python3 scripts/build_job.py --entry differential_genes \
    --input /data/$USER/PROJECT/scdownstream/downstream/out/study1_downstream.h5ad \
    --resdir /data/$USER/PROJECT/scdownstream/differential_genes \
    --dest   /data/$USER/PROJECT/scdownstream/differential_genes \
    --set name=study1 \
    --set diffgenes_contrasts=/data/$USER/PROJECT/scdownstream/contrasts.tsv \
    --set diffgenes_group_col=leiden_1.0
```
Pass `--metadata <local metadata TSV>` here too to cross-check the contrasts against it (§6).

**Seeded values** (in `templates/params_<entry>.yml`; confirm or override):
- `qc_clustering`: `name`, `celltypist_model`, `clustering_resolutions` (the **first** resolution
  becomes the default `leiden` clustering), `automatic_cell_filtering`.
- `downstream`: `name`, `selected_clustering` (`leiden_1.0`), `celltypist_model`.
- `differential_genes`: `name`, `diffgenes_contrasts` (placeholder path — always replace),
  `diffgenes_group_col` (`leiden_1.0`), `diffgenes_sample_col` (`sample`).

The shipped `celltypist_model` (`Mouse_Whole_Brain`) is mouse-specific: change it for human data.

**Other `qc_clustering` options worth offering** (all off/default unless set):
- `doublet_removal: true` — remove called doublets (by default they are only annotated);
  `doublet_detection_threshold` sets how many methods must agree.
- `filtering_keep_outliers: true` — keep QC-failing cells, marked in `obs["outlier"]`, to see where
  they fall before removing them.
- `pca_n_comps` (50) / `neighbors_n_pcs` (all) — read the elbow plot in the QC/clustering report,
  then rerun stage 1 with `-resume` and e.g. `--set neighbors_n_pcs=20`.
- `umap_color_by` / `umap_color_by_embeddings` / `umap_for_plots` — obs columns (e.g. metadata
  columns) plotted on the PCA and scVI UMAPs in both reports.
- `ambient_correction` now **defaults to `none`** (inputs are expected to be CellBender-corrected);
  set `decontx`/`cellbender`/`soupx`/`scar` only if they are not.

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

## 6. Differential genes — contrasts and grouping
Stage 3 sums the `counts` layer into **pseudobulk** profiles per `diffgenes_sample_col` ×
`diffgenes_group_col` value (decoupler), drops profiles below `diffgenes_min_counts` (1000) /
`diffgenes_min_cells` (10), then runs **PyDESeq2** with design `~ variable [+ blocking…]` for every
group value × contrast. Log fold changes are **target vs reference**.

**Contrasts.** Ask the user which comparison(s) they want: the `obs` column (normally a metadata
column such as `condition` or `treatment`), its **reference** (baseline) and **target** levels, and
optional **blocking** covariates (e.g. `sex`, `donor`). Build the sheet — never hand-write the ids:
```bash
python3 scripts/contrasts.py build \
    --contrast 'variable=condition,reference=control,target=treated' \
    --contrast 'variable=condition,reference=control,target=treated,blocking=sex+donor' \
    --metadata sample_metadata.tsv --dest .
# -> contrasts.tsv with ids such as condition__treated__vs__control__block__sex__donor
python3 scripts/contrasts.py check --diffgenes_contrasts contrasts.tsv --metadata sample_metadata.tsv
```
The sheet differs from the differentialabundance one: it is **tab-separated**, `blocking` is
**comma**-separated (`--contrast` takes `sex+donor`), no field may contain whitespace, and `id` is
required (it becomes part of every result filename). `--in draft.tsv` (or a differentialabundance
`contrasts.csv`, whose `;` blocking is converted) also works. With `--metadata`, the check refuses a
reference/target level that does not occur in that column — the pipeline would otherwise **skip the
contrast silently** — and warns about a column the metadata does not have. The
`exclude_samples_col`/`exclude_samples_values` columns are accepted but **inactive** upstream.

**Grouping.** `diffgenes_group_col` decides what each DE analysis runs *within*: a clustering
(`leiden_1.0`, the seeded value, matching downstream's `selected_clustering`) or a cell-type column
(e.g. `celltypist:Mouse_Whole_Brain`, or `label`). `diffgenes_sample_col` is the biological sample —
keep `sample` (the pipeline always creates it) unless the user has a donor-level column that should
be the replicate.

**Tell the user** before submitting:
- A contrast is **skipped silently** for a group value when either side has fewer than
  `diffgenes_min_samples` (2) surviving pseudobulk samples — no error, no file. Check the DE report
  and `de_manifest.tsv` against the contrasts they expected.
- The design needs biological replicates on both sides; with one sample per condition nothing is
  tested.

## 7. Fill the SLURM template
`build_job.py` also writes the filled job script into `--dest`: the input-path line
(`samplesheet=` for `qc_clustering`, `h5adf=` for the other two) and the `resdir=` line are set from
`--input`/`--resdir`, and `exec=`/`main=` from `<repo-root>/assets/cluster.json` (the dev `main.nf`,
`/nfsdata/scripts/nf-core/dev/scdownstream/main.nf`). All three place `-entry <name>` first and
reference `params_<entry>.yml`. `qc_clustering` and `downstream` use
`-profile apptainer,gpu`; `differential_genes` uses `-profile apptainer` (none of its processes use a
GPU). Confirm the `#SBATCH --time`/`--cpus-per-task` suit the run.

## 8. Custom-config recommendations
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

## 9. Hand back
Tell the user the paths of the generated `run_nfcore_scdownstream_<entry>.sh` and
`params_<entry>.yml` files, and that the **`slurm` skill** submits each stage: it transfers a stage's
script with its `params_<entry>.yml` (and `sample_metadata.tsv` / `contrasts.tsv` where they are not
yet on the cluster) and runs `sbatch` from that directory. The stages are **sequential**. Because
every `--base_adata` path is derived in advance (§2), all three can be submitted in one sitting with
the `slurm` skill's `submit --after-ok <previous job id>`: each stage starts only if the one before
it succeeded. Submitting one at a time after `job_status` reports completion, or running each
`sbatch` by hand, is equally fine. Never submit the jobs yourself from this skill.

## Species selection
`--species mouse|human` sets the `species` field for `qc_clustering` and `downstream` (the pipeline
default is `human`, so `--species human` leaves it at its default; `--species mouse` writes
`species: mouse`). For `downstream` it also fills **`ortholog_hcop_directory`** — the HCOP ortholog
tables LIANA+ needs for non-human data, which no longer has a pipeline default — from the shared
`<repo-root>/assets/genomes.json`. `differential_genes` needs no species.

**A species is required for stages 1 and 2.** The templates deliberately do **not** seed `species`,
so if none can be resolved the build hard-errors instead of silently running mouse data as human.

If `--species` is omitted, it is inferred from a species/organism column in a tabular file: the
`qc_clustering` samplesheet or the `--metadata` TSV. A `downstream` `--input` is an `.h5ad`, which
cannot be scanned: pass `--species` (or `--metadata file.tsv`). Scientific names such as
*Mus musculus* / *Homo sapiens* are recognised; a file mixing species is not auto-selected.

## Deltas from upstream nf-core/scdownstream (DESIGN.md §8)
- Three `-entry` stages instead of one pass; `-entry` is always required (without it, stage 1 runs
  with a warning).
- Params added since the previous pin (`3009f37`): `metadata`, `metadata_sample_col`,
  `diffgenes_*`, `doublet_removal`, `filtering_keep_outliers`, `pca_n_comps`, `neighbors_n_pcs`,
  `umap_for_plots`, `umap_color_by`, `umap_color_by_embeddings`.
- Changed defaults: `ambient_correction` = `none`; `ortholog_hcop_directory` has none; the schema's
  `species` default is now `human`, matching `nextflow.config`.
- Output names: `<NAME>_qc_clustering.h5ad` / `<NAME>_downstream.h5ad` replace the old
  `integrated_scvi_finalized.h5ad` (§2).
- Custom modules: ADATA_ADDSAMPLE / ADATA_ADDMETADATA (sample and metadata columns), decoupler
  pseudobulk, PyDESeq2 per contrast, Quarto reports per stage, ADATA_PUBLISH (gzip stage outputs).
