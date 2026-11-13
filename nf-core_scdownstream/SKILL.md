---
name: nf-core_scdownstream
description: >-
  Build SLURM job scripts + params.yml files for an nf-core:scdownstream run on the UKDRI cluster.
  This is a SUBSTANTIALLY MODIFIED UKDRI fork with FIVE stages (--stage): three sequential ones plus
  model training and annotation. Use when the user wants single-cell downstream analysis (QC, doublet
  detection, integration, clustering, cell-type annotation, marker genes, enrichment, cell-cell
  communication), pseudobulk differential gene expression per contrast, training their own
  CellTypist / scANVI cell type models on an annotated reference, or annotating an already processed
  object with such models — triggers: "scdownstream", "nf-core scdownstream", "single-cell
  downstream", "scvi integration", "scanvi", "reference mapping", "celltypist", "cell type
  annotation", "annotate", "train a cell type model", "train_models", "clustering", "qc_clustering",
  "downstream", "marker genes", "presto", "AUC", "COSG", "differential_genes", "differential
  expression", "pseudobulk", "PyDESeq2", "DESeq2 per cell type", "contrasts", "condition",
  "treatment", "sample metadata", plus "samplesheet", "h5ad", "params.yml", "slurm job".
  Produces files only; never runs the pipeline.
---

# nf-core:scdownstream — job builder

## 1. Purpose
Generate ready-to-submit SLURM job scripts and validated `params_<entry>.yml` files for the
nf-core:scdownstream pipeline. This skill only produces files. The generated job scripts are what the
**`slurm` skill** uses to transfer each stage to the HPC and submit it with `sbatch`.

**This is a substantially modified UKDRI fork** (DESIGN.md §8), tracked on the **`dev_ukdri`** branch
of <https://github.com/UKDRI/scdownstream> (version `0.0.1dev`, pinned commit `20bb8f0`). Its
`main.nf` path and parameter set are **not** the stock upstream ones, so validate every parameter
against the stored `assets/nextflow_schema.json` (the fork's schema) — not the public nf-core docs.
UKDRI usage guidance lives at the wiki:
<https://wiki.informatics.ukdri.ac.uk/en/Pipelines/nfcore_scdownstream>.

**Cluster prerequisites:**
- **Nextflow ≥ 25.10.0** — the fork refuses to start with anything older
  (`manifest.nextflowVersion = '!>=25.10.0'`, needed by nf-schema 2.7.3). The job runs the command in
  `<repo-root>/assets/cluster.json` (`nextflow`); Nextflow ≥ 26.04 parses the pipeline with its
  strict syntax parser, which this commit supports.
- The deployed `/nfsdata/scripts/nf-core/dev/scdownstream/main.nf` must be at `20bb8f0` or later.
  Before it there is no `--stage train_models` / `--stage annotate` (the run stops with "Invalid or
  missing --stage"), and `downstream` still selects markers by `markers_thr_adj_pvalue` and rejects
  the `markers_method` / `markers_min_auc` / COSG params the templates may now carry. Before `4c21ae8`, the per-sample QC columns (§3) and the contrast exclusions (§6) are read and silently
  **ignored**, and `min_genes`/`min_counts` are no floors under automatic filtering (§5). Before
  `325fa4e` the checkout does not parse under Nextflow 26.04's strict parser at all; under an older
  Nextflow it has no `--stage` param and, without the `-entry` the job scripts no longer pass, runs
  `qc_clustering` for every stage. Before `6ae8cd9` it also lacks the marker-gene params (see
  "Deltas" below); before `e101d8c` it has no `differential_genes` stage, no `--metadata`, and
  writes the old output names.

## 2. Five stages (§4.7)
scdownstream runs as **three sequential stages** plus **two independent ones**, each selected with
the required pipeline param **`--stage <name>`** — it replaces Nextflow's `-entry <name>`, which the
strict syntax parser does not support. Each stage has its own job script and its own
`params_<entry>.yml`; each sequential stage consumes the previous stage's output `.h5ad` via
`--base_adata`. `build_job.py --entry <name>` picks the stage,
and the job script passes `--stage <name>` on the command line — so `stage` is never written into a
`params_<entry>.yml`; do not `--set stage=…` (a command-line `--stage` would override it anyway).

| Stage | `--stage` / `--entry` | Required input | Writes into its `--outdir` (= `$resdir/out`) |
|---|---|---|---|
| 1 | `qc_clustering` | `--input` samplesheet.csv | `<NAME>_qc_clustering.h5ad` (+ QC/clustering report, MultiQC) |
| 2 | `downstream` | `--base_adata` = stage 1 h5ad (or an `annotate` h5ad) | `<NAME>_downstream.h5ad`, `<NAME>_downstream_markers.json.gz`, report |
| 3 | `differential_genes` | `--base_adata` = stage 2 h5ad, plus `diffgenes_contrasts` | per group × contrast `differential_genes/deseq2/<group>/<NAME>_<group>_<contrast id>.tsv`, `<NAME>_differential_genes.json.gz`, `report/<NAME>_differential_genes_report.html` |
| — | `train_models` | `--train_adata` = an annotated reference h5ad, plus `train_label_col` | `models/celltypist/<MODEL>.pkl`, `models/scanvi/<MODEL>/model.pt`, `models/scvi/<MODEL>/model.pt`, `models/<MODEL>_reference.h5ad`, `models/evaluation/`, `report/<MODEL>_training_report.html` |
| — | `annotate` | `--base_adata` = a processed h5ad, plus a CellTypist and/or scANVI model | `<NAME>_annotate.h5ad`, `annotate/<NAME>_annotate_predictions.tsv`, `report/<NAME>_annotate_report.html` |

No stage writes `.rds` files any more; to work in R, read the `.h5ad` with anndataR
(`anndataR::read_h5ad(path, as = "SingleCellExperiment")` or `as = "Seurat"`) or zellkonverter.
The two independent stages are covered in §7: `train_models` produces models that `qc_clustering`
and `annotate` consume, and `annotate`'s output is a valid `--base_adata` for `downstream`.

**`<NAME>` is the `name` param of that stage; unset, it falls back to `scdownstream`** (the fork's
`conf/modules.config`: `"${params.name ?: 'scdownstream'}_<stage>"`) — except for the
`differential_genes` DE tables and report, which fall back to `differential_genes` (`main.nf`),
while its JSON still falls back to `scdownstream`. The templates seed `name`, so this only matters
if it is removed. `<MODEL>` (train_models) is `train_name`, falling back to `name`, then
`reference`. Stages 1 and 2 (and `annotate`) publish their `.h5ad` to the root of `--outdir`,
gzip-compressed, with `X`, every layer and `raw.X` stored as sparse CSR. Stage 3 writes its DE
tables into `differential_genes/deseq2/<group>/` (one folder per `diffgenes_group_col` value) and
its marker-gene JSON to the root of `--outdir`. Every stage's HTML report is in `report/`; the
pseudobulk `.h5ad`s are published only with `save_intermediates: true`.

**Deriving the next stage's input — do this, don't guess:**

```
--input of stage N+1 = <stage N resdir>/out/<stage N name>_<stage N stage>.h5ad
```

(`annotate` slots in the same way: qc_clustering → annotate → downstream uses
`<annotate resdir>/out/<name>_annotate.h5ad` as downstream's input.)

Ask the user for a short study name **once** and pass the same `--set name=<study>` to all
stages, so both `--base_adata` paths are known before stage 1 has even run. The templates seed
`name: scdownstream`, so without `--set name=` the files are `scdownstream_qc_clustering.h5ad` and
`scdownstream_downstream.h5ad`.

## 3. Required inputs
- **`qc_clustering`** — a **`samplesheet.csv`** prepared beforehand (see the `ena`/`geo`/
  `arrayexpress` skills): columns `sample` and at least one of `filtered` / `unfiltered` (paths to
  `h5ad`, `h5`, `rds` or `csv` matrices). If missing, direct the user to prepare it first. Optional:
  a **per-sample metadata TSV** (§4), and these optional samplesheet columns:
  - **Gene symbols, per sample only** — there is no global `--symbol_col` any more. `symbol_col`
    empty/absent = `index` (the row names are symbols, e.g. CellRanger `.h5`); a var column name
    (e.g. `gene_symbols`); or `none` to convert `geneid_col` (default `index`) to symbols online
    via MyGene.info. `none` is **human-only**, needs internet on the compute nodes, and **fails
    with `celltypist_model` set** ("Symbol column none not found") — for mouse data or with
    CellTypist, the input must already carry symbols. Mitochondrial QC ignores `symbol_col`: it
    looks for `MT-`/`mt-` in the var index or a `gene_name(s)`/`gene_symbol(s)` column, so
    Ensembl-only input gets 0 % mito and `max_mito_percentage` removes nothing.
  - **Per-sample QC thresholds** — `min_genes`, `max_genes`, `min_counts_cell`, `max_counts`,
    `max_mito_percentage`, `min_cells`, `min_counts_gene`, `automatic_cell_filtering` override the
    matching global param (`min_counts_cell` → `min_counts`) for that sample. A value wins,
    including `0`/`false`; an empty cell falls back to the global value. Use them for a sample that
    needs stricter or different filtering; leave them out otherwise. The applied thresholds are in
    each sample's MultiQC section.
- **`downstream`** — the stage 1 `<NAME>_qc_clustering.h5ad`.
- **`differential_genes`** — the stage 2 `<NAME>_downstream.h5ad` (it must hold a **`counts` layer**
  of raw counts; stage 1's normalisation step stores them there, so the pipeline's own outputs
  qualify — an object from elsewhere may not) and a **contrasts TSV** (§6).
- **`train_models`** — an **annotated reference `.h5ad`** (e.g. a published atlas, or an earlier
  scdownstream output with curated labels), and three facts about it that only the user knows: the
  `obs` column with the labels, where its **raw** counts are (`X` or a layer), and ideally a donor
  column to hold out (§7.1).
- **`annotate`** — a **processed `.h5ad`** with raw counts in `layers["counts"]` (every scdownstream
  output has them; without that layer `X` is used, and normalised data there gives wrong predictions
  **without an error**), plus at least one model (§7.2).

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
    --species human \
    --metadata /data/$USER/PROJECT/scdownstream/sample_metadata.tsv \
    --input  /data/$USER/PROJECT/scdownstream/samplesheet_scdownstream.csv \
    --resdir /data/$USER/PROJECT/scdownstream/qc_clustering \
    --dest   /data/$USER/PROJECT/scdownstream/qc_clustering \
    --set name=study1 --set umap_color_by=condition,sex
```

**downstream** (input derived per §2):
```bash
python3 scripts/build_job.py --entry downstream \
    --species human \
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
  becomes the default `leiden` clustering), `automatic_cell_filtering: true`, and with it
  `min_genes: 10` / `min_counts: 20` — see "Automatic cell filtering" below.
- `downstream`: `name`, `selected_clustering` (`leiden_1.0`), `celltypist_model`.
- `differential_genes`: `name`, `diffgenes_contrasts` (placeholder path — always replace),
  `diffgenes_group_col` (`leiden_1.0`), `diffgenes_sample_col` (`sample`).
- `annotate`: `name`, `celltypist_model` (so the stage always has a model; replace or extend it
  with the user's models, §7.2).
- `train_models`: **nothing** — every value depends on the reference (§7.1). The build warns when
  `train_label_col` (required) or `train_name` is unset.

The shipped `celltypist_model` (`Adult_Human_PrefrontalCortex`, adult human dorsolateral prefrontal
cortex) is human- and tissue-specific: change it for mouse data (e.g. `Mouse_Whole_Brain`) or other
tissues — ask the user when the species or tissue differs.

**Keep every analysis parameter in the params file — never move one onto the command line.** Under
Nextflow 26 a command-line value reaches the pipeline as **text**: `--train_evaluate false` is the
word `"false"`, which counts as *true*, and numbers are not numbers. The job scripts pass only
`--stage`, the input path and `--outdir`; `--set` writes typed YAML.

**Other `qc_clustering` options worth offering** (all off/default unless set):
- `doublet_removal: true` — remove called doublets (by default they are only annotated);
  `doublet_detection_threshold` sets how many methods must agree.
- `filtering_keep_outliers: true` — keep QC-failing cells, marked in `obs["outlier"]`, to see where
  they fall before removing them.
- `pca_n_comps` (50) / `neighbors_n_pcs` (all) — read the elbow plot in the QC/clustering report,
  then rerun stage 1 with `-resume` and e.g. `--set neighbors_n_pcs=20`.
- `umap_color_by` / `umap_color_by_embeddings` / `umap_for_plots` — obs columns (e.g. metadata
  columns) plotted on the PCA and scVI UMAPs in both reports.
- **Automatic cell filtering** (seeded on). Each sample gets N-MAD thresholds: genes and counts per
  cell below median − 2.5 MAD or above median + 5 MAD, mito % above median + 5 MAD, are removed.
  `min_genes`/`min_counts` are **floors** under the lower bounds (fixed `max_*` are unused). The
  pipeline default `min_genes` 200 often overrides the N-MAD bound and drops small cells (nuclei),
  so the template seeds the fork's recommended low floors `10`/`20`: they only stop empty barcodes
  passing when the N-MAD bound clamps to 0. With `--set automatic_cell_filtering=false`, also
  `--set min_genes=200 --set min_counts=0` (or other fixed values), since the floors then become
  the fixed thresholds. Cells left empty after gene filtering are always removed, even with
  `filtering_keep_outliers`.
- `ambient_correction` now **defaults to `none`** (inputs are expected to be CellBender-corrected);
  set `decontx`/`cellbender`/`soupx`/`scar` only if they are not.
- **Reference mapping / own models** (e.g. from `train_models`, §7.1):
  `--set celltypist_model=<built-in>,<…>/models/celltypist/<MODEL>.pkl`,
  `--set integration_methods=scvi,scanvi` and
  `--set scanvi_model=<…>/models/scanvi/<MODEL>/model.pt` add `celltypist:<MODEL>` and
  `scanvi:<MODEL>` (+ `:conf`) predictions, which can then be `selected_clustering` /
  `diffgenes_group_col`. `scanvi_model` needs `scanvi`, and `scanvi` needs `scvi`, in
  `integration_methods`; `scvi_query_max_epochs` (100) sets the fine-tuning epochs. `scanvi`
  without `scanvi_model` trains scANVI on the samplesheet labels (`scanvi:labels`). scANVI cannot
  be combined with a `--base_adata` extension — use `annotate` (§7.2) for an existing object.
- `report_max_celltype_labels` (50) — the reports' "Predicted labels" UMAPs and tables show only
  the top N CellTypist labels; raise it for models with many labels.

**Marker genes (`downstream`)** — each group of `selected_clustering` vs all other cells, on the
log-normalised `X`. Two methods, **both run by default** (`markers_method: presto,cosg`):
- **`presto`** — Wilcoxon rank-sum test with the **AUC** (a Python port of R presto's `wilcoxauc`).
  Markers are **selected and ranked by AUC**: `markers_min_auc` (0.7; 0.5 = no difference, 1 = a
  perfect marker). p-values are still reported but no longer select markers (cluster-vs-rest
  p-values are inflated), so **`markers_thr_adj_pvalue` is gone**.
- **`cosg`** — the COSG specificity score (cosine similarity to an ideal marker; `markers_cosg_mu`,
  default 1, penalises genes also expressed elsewhere). `markers_min_cosg_score` (0–1, unset)
  filters by it; it is off by default because top scores vary a lot between clusters.
- `markers_rank_by` — `auc` (default whenever presto runs: AUC → adj. p → log2FC → COSG) or `cosg`
  (default with COSG only: COSG → log2FC → pct in). `auc` needs presto, `cosg` and
  `markers_min_cosg_score` need cosg — the pipeline stops at launch otherwise.
- `markers_pct_nz` (0.1), `markers_min_logfc` (0) and `markers_n_top` (100) still filter.
- `--set markers_method=cosg` gives COSG only: no AUC, no p-values, `markers_min_auc` unused.
- Offer `--set markers_rank_by=cosg` when the user wants the most **specific** genes per cluster
  rather than the best-discriminating ones.

**Marker-gene JSONs** (`downstream` and `differential_genes`). Both write a compact gene-set JSON
to the root of `--outdir`: `<NAME>_downstream_markers.json.gz` (one set per cluster, id
`genes--cluster--<cluster>`, per gene `list_score` = the ranking metric, `list_logFC`, with presto
`list_auc` / `list_p_value(_adjusted)`, with COSG `list_cosg_score`) and `<NAME>_differential_genes.json.gz` (per group value × contrast,
`genes--<contrast id>--<group>--up` / `--down`, ranked by the Wald statistic; empty sets are
dropped). `differential_genes` filters its sets with `diffgenes_markers_thr_adj_pvalue` (0.05),
`diffgenes_markers_min_logfc` (0, absolute log2 FC) and `diffgenes_markers_n_top` (100 per set).
`markers_sep` (default `--`) is the separator in both files' set ids, and **the run stops when a
cluster value, group value or contrast id contains it** — leave it at `--` (the contrast ids built in
§6 never contain it); change it only via `--set markers_sep=<value>` in the params file.

### 5.1 `celltypist_model` value check
`celltypist_model` is a **comma-separated list**; each entry is either a **built-in model name
without `.pkl`** (downloaded at runtime) or a **local model file** — an entry **ending in `.pkl` or
containing `/`**, e.g. a `train_models` output. Both can be mixed:
`--set celltypist_model=Adult_Human_PrefrontalCortex,/data/$USER/PROJECT/train_models/out/models/celltypist/my_ref.pkl`.
Predictions are written as `celltypist:<model>` (the name, or the file name without `.pkl`); two
local files with the same file name cannot be used together. Use absolute paths for local files.

Each entry is checked (advisory, **warn — never error**) against `assets/celltypist_models.json`:

1. an entry with `/` or ending in `.pkl` is a **local file** and is accepted without a name check —
   but `Mouse_Whole_Brain.pkl` **warns**: the pipeline now reads it as a *file* named that (and stops
   when it is not there), not as the built-in; drop the `.pkl`;
2. any other entry is matched against the known CellTypist models (e.g. `Adult_Human_PrefrontalCortex`,
   `Mouse_Whole_Brain`);
3. an unknown name **warns** but the value **is still written** to `params_<entry>.yml`. The list
   is a refreshable snapshot, so a legitimate-but-unlisted name is not an error.

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
required (it becomes part of every result filename). An id must **not contain `markers_sep`**
(`--`): the marker-gene JSON export would stop the run after all the DE work. Generated ids never do
(runs of `-` collapse like runs of `_`); `build` replaces a hand-written id that does, and `check`
rejects one (pass `--markers_sep=<value>` to both if the run overrides it). `--in draft.tsv` (or a
differentialabundance `contrasts.csv`, whose `;` blocking is converted) also works. With
`--metadata`, the check refuses a reference/target level that does not occur in that column — the
pipeline would otherwise **skip the contrast silently** — and warns about a column the metadata
does not have.

**Excluding samples from one contrast** (e.g. outlier donors), via `exclude_samples_col` +
`exclude_samples_values` (comma-separated in the sheet, `+`-joined in `--contrast`). Matching
pseudobulk samples are dropped before the fit and before the `diffgenes_min_samples` check; other
contrasts still use them. Ask only if the user names samples to leave out.
```bash
python3 scripts/contrasts.py build \
    --contrast 'variable=condition,reference=control,target=treated' \
    --contrast 'id=condition__treated__vs__control__excl_outliers,variable=condition,reference=control,target=treated,exclude_samples_col=donor,exclude_samples_values=D07+D12' \
    --metadata sample_metadata.tsv --dest .
```
- The column must be **sample-level** (constant within a sample — donor, batch, sex; every
  `--metadata` column qualifies), or the run stops: pseudobulk keeps only such columns.
- The generated id does **not** encode the exclusion, so the same comparison with and without one
  needs an explicit `id=` on one of them, as above (`build` stops on the duplicate otherwise).
- `check`/`build` reject a row that sets only one of the two columns, or `;`-separated values, and —
  with `--metadata` — a value that does not occur in that column: the pipeline would only log a
  warning and exclude nothing (or less than intended). A column not in the metadata warns.
- If the exclusion leaves fewer than `diffgenes_min_samples` on a side, the contrast is skipped for
  that group value (the log says so).

**Grouping.** `diffgenes_group_col` decides what each DE analysis runs *within*: a clustering
(`leiden_1.0`, the seeded value, matching downstream's `selected_clustering`) or a cell-type column
(e.g. `celltypist:Adult_Human_PrefrontalCortex`, or `label`). `diffgenes_sample_col` is the biological sample —
keep `sample` (the pipeline always creates it) unless the user has a donor-level column that should
be the replicate.

**Tell the user** before submitting:
- A contrast is **skipped silently** for a group value when either side has fewer than
  `diffgenes_min_samples` (2) surviving pseudobulk samples — no error, no file. Check the DE report
  against the contrasts they expected (the pipeline's `de_manifest.tsv` feeds the report but is not
  published). The DE report opens with a
  **Contrasts** table (target vs reference, blocking, excluded samples) and a **Significant genes
  overview** per group value × contrast that marks the skipped ones.
- The design needs biological replicates on both sides; with one sample per condition nothing is
  tested.
- The values of `diffgenes_group_col` (and of downstream's `selected_clustering`) must not contain
  `markers_sep` (`--`) either, or the marker-gene JSON export stops the run. Leiden clusters are
  numbers; check cell-type labels if grouping by one. These live in the `.h5ad`, so no local check
  can see them.

## 7. Cell type models — `train_models` and `annotate`
Two stages outside the qc_clustering → downstream → differential_genes sequence. Neither needs a
species (no `--species`). Both use `-profile apptainer,gpu` (scVI / scANVI run on the GPU).

### 7.1 `train_models` — train CellTypist and scANVI models on a reference
Trains **CellTypist** (logistic regression on log-normalised counts) and **scANVI** (a scVI model,
then scANVI initialised from it, on `train_hvgs` (5000) HVGs; architecture and epochs from the
`scvi_*` params) — `train_methods: celltypist,scanvi` by default. Ask the user for:

- the **label column** → `--set train_label_col=<column>` (**required**). Labels are used **exactly
  as written** ("CD4+ T" and "CD4- T" stay two classes); only `train_unknown_label` (`unknown`) and
  empty values are unlabelled. Labels with fewer than `train_min_cells_per_label` (50) cells are
  dropped everywhere and listed in the report;
- a **model name** → `--set train_name=<model>` (letters, digits, `_`, `-`): it names the files and
  the prediction columns `celltypist:<model>` / `scanvi:<model>`;
- where the **raw counts** are → `--set train_counts_layer=counts` for an scdownstream output
  (default `X`; a warning is printed if they are not integers). Many published atlases keep
  *normalised* data in `X` and the raw counts in `raw.X` or a layer — ask, don't assume;
- the **batch** column (`train_batch_col`, default `batch`; one batch if missing) and, if gene
  symbols are not the var index, `train_symbol_col`;
- a **donor column** to hold out → `--set train_test_split_by=<column>`. **Recommend it:** by default
  single cells are held out, so test cells share donors with training cells and the metrics are
  optimistic for new donors.

```bash
python3 scripts/build_job.py --entry train_models \
    --input  /data/$USER/PROJECT/scdownstream/reference/reference.h5ad \
    --resdir /data/$USER/PROJECT/scdownstream/train_models \
    --dest   /data/$USER/PROJECT/scdownstream/train_models \
    --set train_label_col=cell_type --set train_name=my_ref \
    --set train_counts_layer=counts --set train_test_split_by=donor_id
```

**Evaluation** (`train_evaluate: true`, default): `train_test_fraction` (0.25) of each label is held
out, both models are trained on the rest and the test cells predicted (scANVI by query mapping, as
`qc_clustering` uses it), giving accuracy, balanced accuracy, F1, per-label precision/recall and a
confusion matrix. The final models are then **refit on all cells** (`train_final_on_all: true`);
`false` keeps the training-split models. `train_evaluate: false` skips the evaluation.

**Large references** (hundreds of thousands of cells; CellTypist's default holds a dense scaled
copy): offer `--set train_max_cells_per_label=2000` (downsample the training data per label; the
test set is not downsampled) and `--set train_celltypist_use_sgd=true
--set train_celltypist_mini_batch=true` (`train_celltypist_batch_size`, 1000). `mini_batch` without
`use_sgd` stops the run at launch.

**Outputs** under `<resdir>/out/`: `models/celltypist/<MODEL>.pkl`, `models/scanvi/<MODEL>/model.pt`,
`models/scvi/<MODEL>/model.pt`, `models/<MODEL>_reference.h5ad`, `models/evaluation/`
(`<MODEL>_label_counts.tsv`, `<method>/<method>_{metrics,per_label,confusion}.tsv`) and
`report/<MODEL>_training_report.html`. The models only work with the pipeline's tool versions
(CellTypist 1.6.3, scvi-tools 1.3.3). Use them in `qc_clustering` (§5, "Reference mapping") or
`annotate` (§7.2).

### 7.2 `annotate` — add predictions to an already processed object
Runs CellTypist and/or scANVI on an existing `.h5ad` (e.g. `<NAME>_qc_clustering.h5ad`) without
re-running QC, integration or clustering. A method runs only when its model is given; **at least one
is required** (the run stops at launch otherwise):

- `celltypist_model` — built-in names and/or local `.pkl` files (§5.1). The template seeds
  `Adult_Human_PrefrontalCortex`; replace it, or append the user's model so the report compares both;
- `scanvi_model` — the path of a **`model.pt`** (any other file name stops the run); the columns are
  named after its folder (`models/scanvi/my_ref/model.pt` → `scanvi:my_ref`).

```bash
python3 scripts/build_job.py --entry annotate \
    --input  /data/$USER/PROJECT/scdownstream/qc_clustering/out/study1_qc_clustering.h5ad \
    --resdir /data/$USER/PROJECT/scdownstream/annotate \
    --dest   /data/$USER/PROJECT/scdownstream/annotate \
    --set name=study1 \
    --set celltypist_model=Adult_Human_PrefrontalCortex,/data/$USER/PROJECT/scdownstream/train_models/out/models/celltypist/my_ref.pkl \
    --set scanvi_model=/data/$USER/PROJECT/scdownstream/train_models/out/models/scanvi/my_ref/model.pt
```

- **Raw counts are not checked.** They come from `layers["counts"]`, or `X` without that layer;
  normalised or log data give **wrong predictions without an error**. Non-integer (SoupX/decontX)
  counts are fine. Gene names must match the models' (usually symbols; `annotate_symbol_col` if
  they are in a var column) — scANVI stops below 50 % of the model's genes, warns below 80 %.
- **scANVI batches** come from `annotate_batch_col` (`batch`, one value per sample in scdownstream
  output); for another object set it to its sample column. A model trained with
  `scvi_*_covariates` needs the same `obs` columns.
- **Subset** — `--set annotate_subset_col=leiden --set annotate_subset_values=3,7` annotates only
  those cells (e.g. a microglia-state model on the microglia clusters). **The output then holds only
  those cells**; UMAPs and clusters are not recomputed. Both params are needed together; values
  containing a comma cannot be selected.
- **Outputs**: `<NAME>_annotate.h5ad` (the input plus `celltypist:<model>` / `scanvi:<model>`
  (+ `:conf`) columns and `obsm["X_scanvi_<model>"]`; re-annotating with a model of the same name
  replaces its columns), `annotate/<NAME>_annotate_predictions.tsv`, and
  `report/<NAME>_annotate_report.html` (label counts, confidences, method agreement, labels per
  Leiden cluster and per sample).
- **Continuing**: `<NAME>_annotate.h5ad` is a valid `downstream` input, e.g. with
  `--set selected_clustering=scanvi:my_ref` (and then `diffgenes_group_col` in stage 3). Cell-type
  labels used as groups must not contain `markers_sep` (`--`, §6).
- A cell type missing from the reference still gets the closest reference label, usually with a
  lower `:conf` — tell the user to check low-confidence cells.

## 8. Fill the SLURM template
`build_job.py` also writes the filled job script into `--dest`: the input-path line
(`samplesheet=` for `qc_clustering`, `h5adf=` for the other four) and the `resdir=` line are set
from `--input`/`--resdir`, and `exec=`/`main=` from `<repo-root>/assets/cluster.json` (the dev
`main.nf`, `/nfsdata/scripts/nf-core/dev/scdownstream/main.nf`). All five place `--stage <name>`
first and reference `params_<entry>.yml` — never `-entry`, which this fork no longer supports. The
input flag is `--input` (qc_clustering), `--train_adata` (train_models) or `--base_adata` (the
other three). `qc_clustering`, `downstream`, `train_models` and `annotate` use
`-profile apptainer,gpu`; `differential_genes` uses `-profile apptainer` (none of its processes use
a GPU). Confirm the `#SBATCH --time`/`--cpus-per-task` suit the run.

**No GPU on the cluster?** Change `-profile apptainer,gpu` to `-profile apptainer` in the
`qc_clustering`, `downstream`, `train_models` and `annotate` scripts. The `process_gpu` steps (e.g. scVI) then run on CPU, because
`base.config` sets `ext.use_gpu`/`accelerator` from `workflow.profile.contains('gpu')`. They are slower,
so allow more `#SBATCH --time`.

## 9. Custom-config recommendations
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
- **Large training references (`train_models`):** reach for `train_max_cells_per_label` and the
  CellTypist SGD options first (§7.1) — they cut memory at the source; a memory bump is the fallback.

## 10. Hand back
Tell the user the paths of the generated `run_nfcore_scdownstream_<entry>.sh` and
`params_<entry>.yml` files, and that the **`slurm` skill** submits each stage: it transfers a stage's
script with its `params_<entry>.yml` (and `sample_metadata.tsv` / `contrasts.tsv` / a training
reference `.h5ad` / local `.pkl` models where they are not yet on the cluster) and runs `sbatch`
from that directory. The three main stages are **sequential**. Because every `--base_adata` path is
derived in advance (§2), they can be submitted in one sitting with the `slurm` skill's
`submit --after-ok <previous job id>`: each stage starts only if the one before it succeeded. The
same holds for chains through the independent stages — `train_models` → `qc_clustering` /
`annotate` (the model paths `models/celltypist/<MODEL>.pkl` and `models/scanvi/<MODEL>/model.pt`
under its `$outdir` are known from `train_name`), and `qc_clustering` → `annotate` → `downstream`.
Say plainly that those paths do not exist yet and were not checked: the pipeline checks a local
`.pkl` and the `model.pt` when the dependent stage launches. Submitting one at a time after `job_status` reports completion, or running each
`sbatch` by hand, is equally fine. Never submit the jobs yourself from this skill.

## Species selection
`--species mouse|human` sets the `species` field for `qc_clustering` and `downstream` (the pipeline
default is `human`, so `--species human` leaves it at its default; `--species mouse` writes
`species: mouse`). For `downstream` it also fills **`ortholog_hcop_directory`** — the HCOP ortholog
tables LIANA+ needs for non-human data, which no longer has a pipeline default — from the shared
`<repo-root>/assets/genomes.json`. `differential_genes`, `train_models` and `annotate` need no
species (the `--species` flag is accepted there but fills nothing).

**A species is required for stages 1 and 2.** The templates deliberately do **not** seed `species`,
so if none can be resolved the build hard-errors instead of silently running mouse data as human.

If `--species` is omitted, it is inferred from a species/organism column in a tabular file: the
`qc_clustering` samplesheet or the `--metadata` TSV. A `downstream` `--input` is an `.h5ad`, which
cannot be scanned: pass `--species` (or `--metadata file.tsv`). Scientific names such as
*Mus musculus* / *Homo sapiens* are recognised; a file mixing species is not auto-selected.

## Deltas from upstream nf-core/scdownstream (DESIGN.md §8)
- Five stages instead of one pass, selected with the **required** `--stage
  qc_clustering|downstream|differential_genes|train_models|annotate` (since `325fa4e`; it replaces
  `-entry`, which Nextflow 26.04's strict syntax parser does not support; `train_models` and
  `annotate` since `20bb8f0`). Without a valid `--stage` the run stops before any task; `--help` /
  `--help_full` run no stage.
- Minimum Nextflow raised from 24.10.5 to **25.10.0** (nf-schema 2.4.2 → 2.7.3); the pipeline
  parses under Nextflow 26.04's strict parser without `NXF_SYNTAX_PARSER=v1`.
- Params added since the previous pin (`3009f37`): `metadata`, `metadata_sample_col`,
  `diffgenes_*`, `doublet_removal`, `filtering_keep_outliers`, `pca_n_comps`, `neighbors_n_pcs`,
  `umap_for_plots`, `umap_color_by`, `umap_color_by_embeddings`; since `e101d8c`: `markers_sep`,
  `diffgenes_markers_n_top`, `diffgenes_markers_thr_adj_pvalue`, `diffgenes_markers_min_logfc`;
  since `6ae8cd9`: `stage`; since `20bb8f0`: `markers_method`, `markers_rank_by`,
  `markers_min_auc`, `markers_cosg_mu`, `markers_min_cosg_score`, `report_max_celltype_labels`,
  `scvi_query_max_epochs`, `train_*` (§7.1) and `annotate_*` (§7.2).
- Removed (since `6ae8cd9`): SingleR / celldex cell type annotation and its `celldex_reference`
  param — cell type annotation is CellTypist only. `build_job.py` now rejects `celldex_reference`
  as an unknown key; the `test_offline` profile is gone too.
- Removed (since `325fa4e`), all of them unused or broken: `mito_genes` (mito genes are always the
  `MT-`/`mt-` prefix), `symbol_col` (set per sample in the samplesheet, §3), `qc_only`,
  `prep_cellxgene` (the published h5ad opens in cellxgene directly) and the config-only
  `skip_enrichment` (enrichment always runs in `downstream`). `build_job.py` rejects them as unknown
  keys.
- Removed (since `20bb8f0`): `markers_thr_adj_pvalue` (markers are selected by AUC, §5), SCimilarity
  (`scimilarity_model`, and `scimilarity` in `integration_methods`) and the inactive `pseudobulk`,
  `pseudobulk_groupby_labels`, `pseudobulk_min_num_cells`. `build_job.py` rejects them as unknown
  keys. The `SCANPY_RANKGENESGROUPS` module is gone (presto/COSG replace it).
- Since `20bb8f0`: **no `.rds` outputs** (ADATA_TORDS removed; read the h5ad with anndataR or
  zellkonverter). `celltypist_model` entries ending in `.pkl` or containing `/` are **local model
  files** (§5.1). scANVI reference mapping works in `qc_clustering` (`scanvi:<model>` columns,
  `obsm["X_scanvi"]`); with `--base_adata` it stops ("not supported yet"). The downstream marker
  JSON gained `list_auc` / `list_cosg_score`, and `list_score` is now the ranking metric. The
  reports' marker, enrichment and LIANA+ tables are sortable and the marker tables filterable.
  Containers: `nhecker/scanpy-ukdri-suite:1.11.4-1` and `nhecker/seurat-ukdri-suite:5.5.1-1`
  replace the per-tool images (first run on the cluster pulls them into the apptainer cache).
- Since `325fa4e`: the samplesheet's per-sample QC columns take effect (new `max_genes`,
  `max_counts`; before they were read and ignored), and so do the contrasts' `exclude_samples_col` /
  `exclude_samples_values` (§6). **Behaviour change:** with `automatic_cell_filtering`,
  `min_genes`/`min_counts` are floors under the N-MAD bounds (§5), and cells left empty after gene
  filtering are always removed. The DE report gained a Contrasts table and a significant-genes
  overview.
- The downstream marker JSON's set ids changed from `genes_cluster_<cluster>` to
  `genes--cluster--<cluster>`: tools reading that file need the new ids. The schema now enforces the
  minimums of `markers_min_logfc` (0) and `markers_n_top` (1).
- Changed defaults: `ambient_correction` = `none`; `ortholog_hcop_directory` has none; the schema's
  `species` default is now `human`, matching `nextflow.config`.
- Output names: `<NAME>_qc_clustering.h5ad` / `<NAME>_downstream.h5ad` replace the old
  `integrated_scvi_finalized.h5ad` (§2).
- Custom modules: ADATA_ADDSAMPLE / ADATA_ADDMETADATA (sample and metadata columns), decoupler
  pseudobulk, PyDESeq2 per contrast, PYDESEQ2_EXPORT_MARKERS (the differential-genes JSON), Quarto
  reports per stage, ADATA_PUBLISH (gzip, sparse-CSR stage outputs), MARKERS_PRESTO / MARKERS_COSG,
  and the train_models (ADATA_TRAINSPLIT, CELLTYPIST_TRAIN, MODEL_EVALUATE) and annotate
  (ADATA_PREPANNOTATE) modules.
