---
name: nf-core_spatialvi
description: >-
  Build a SLURM job script + params.yml for an nf-core/spatialvi run on the UKDRI cluster.
  Use when the user wants to run 10x Visium / Visium HD spatial transcriptomics analysis with
  nf-core:spatialvi — triggers: "spatialvi", "nf-core spatialvi", "spatial transcriptomics",
  "Visium", "Visium HD", "Space Ranger", "spaceranger", "spatial gene expression", plus
  "samplesheet", "params.yml", "slurm job". Produces files only; never runs the pipeline.
---

# nf-core:spatialvi — job builder

## 1. Purpose
Generate a ready-to-submit SLURM job script (`run_nfcore_spatialvi.sh`) and a validated
`params.yml` for one nf-core/spatialvi run (10x Visium / Visium HD spatial transcriptomics:
optional Space Ranger processing followed by QC, normalization, clustering, spatially variable
genes and multi-sample integration). This skill only produces files. The generated job script is what
the **`slurm` skill** uses to transfer the run to the HPC and submit it with `sbatch`.

**UKDRI fork, dev pipeline.** spatialvi runs from the UK DRI fork
[`UKDRI/spatialvi`](https://github.com/UKDRI/spatialvi), tracked on its default **`dev_ukdri`**
branch (version `1.0dev`, commit `c49fcc5`) — not `nf-core/spatialvi`. The job script's `main=` is
filled from `<repo-root>/assets/cluster.json`: `/nfsdata/scripts/nf-core/dev/spatialvi/main.nf` — a
dev build, not a release tag; confirm the exact path on the cluster before submitting.

**Deltas from upstream `nf-core/spatialvi@dev`** (the fork is upstream dev plus the UK DRI
marker-gene export; everything else matches the public docs):
- **Marker-gene JSON export** (`SCANPY_EXPORT_MARKERS`, ported from UK DRI scdownstream): marker
  genes per cluster are written as gzipped JSON, per sample (`<SAMPLE>/data/<SAMPLE>_markers.json.gz`)
  and, unless `skip_integration`, for the integrated clusters
  (`integration/data/<METHOD>_markers.json.gz`), in the same format as scdownstream. Each gene set
  id is `genes<sep>cluster<sep><cluster>`. Skipped entirely with `rank_genes_method: logreg` (no
  p-values / fold changes / expression fractions to filter on).
- **Marker genes for the integrated clusters**, shown in the integration report; per-sample and
  integrated reports gain a "Differential genes per cluster" section with a top-3 dotplot and
  searchable, sortable per-cluster tables of the top markers.
- **New parameters** (all optional, in `params.yml`):

  | param | default | meaning |
  |---|---|---|
  | `report_n_top_markers` | `250` | top marker genes per cluster listed in the reports (≥ 1) |
  | `markers_thr_adj_pvalue` | `0.05` | adjusted p-value cut-off for the JSON export (0–1) |
  | `markers_pct_nz` | `0.1` | min fraction of the cluster's spots expressing the gene (0–1) |
  | `markers_min_logfc` | `0` | min log2 fold change (≥ 0) |
  | `markers_n_top` | `100` | max marker genes per cluster in the JSON (≥ 1) |
  | `markers_sep` | `--` | separator in the gene-set ids; no quotes, backslashes, `$` or whitespace; the run stops if a cluster name contains it |

  `build_job.py` checks these keys exist but not their ranges or the `markers_sep` pattern — the
  pipeline's nf-schema validation rejects out-of-range values at launch. Because `params.yml` is a
  `-params-file`, a `markers_sep` starting with `-` is safe there (it would not be as a CLI flag).
- `SCANPY_RANK_GENES_GROUPS` now records `pts`/`pts_rest` (fraction of spots expressing each gene
  in/outside the cluster) in `uns["rank_genes_groups"]`; the integrated ranking gets 36 GB × attempt.

## 2. Required inputs
- **`samplesheet.csv`** — prepared beforehand. Its columns are derived from the pipeline's
  `assets/schema_input.json` / usage docs (dev branch). It has **2 columns** (processed data) **or
  5 columns** (raw data), plus a header row — the same samplesheet feeds both paths:
  - **2-column (processed / downstream-only)** — data already processed by Space Ranger, only
    downstream analysis is needed:
    ```
    sample,spaceranger_dir
    SAMPLE_1,results/SAMPLE_1/outs
    SAMPLE_2,results/SAMPLE_2/outs
    ```
    `spaceranger_dir` may be a directory path or a compressed tarball.
  - **5-column (raw / run Space Ranger first)** — raw spatial data that must be processed by Space
    Ranger before downstream analysis:
    ```
    sample,fastq_dir,image,slide,area
    SAMPLE_1,fastqs_1/,hires_1.png,V11J26,B1
    SAMPLE_2,fastqs_2/,hires_2.png,V11J26,B1
    ```
    `image` may be replaced by `cytaimage` for CytAssist samples; optional extra columns
    (`colorizedimage`, `darkimage`, `manual_alignment`, `slidefile`) may be added per experiment.
  - `sample` is the only column the input schema marks strictly required (non-whitespace id); the
    2-vs-5 column shape selects the processing path. If unsure which format applies, ask the user
    whether their data is already Space Ranger-processed.
- **Space Ranger reference** — for the 5-column raw path. `spaceranger_reference` defaults to the
  GRCh38 human reference (auto-downloaded); set it in `params.yml` for mouse or a custom genome.
  Optionally `spaceranger_probeset` for FFPE/probe-based assays. Not needed for the 2-column path.

If the samplesheet is missing, direct the user to prepare it first (do not fabricate one).

## 3. Gather parameters
Ask the user for: the samplesheet path, a results directory on `/data`, which input format they
have (2- vs 5-column), and any non-default parameters. Common non-defaults: `spaceranger_reference`
(mouse/custom genome for the raw path), `hd_bin_size` (Visium HD; enum `2|8|16`, default `8`), QC
thresholds (`qc_min_counts` 500, `qc_min_genes` 250, `qc_mito_threshold` 20, …),
`integration_method` (`harmony`|`scanorama`), `skip_integration` for single-sample runs, and the
fork's marker-gene filters (`markers_*`, `report_n_top_markers` — see §1).
**There is no UKDRI house recommendation for spatialvi**, so `templates/params.yml` ships
effectively empty (comments only) — nothing is pre-applied.

## 4. Generate `params.yml` (+ optional custom config)
Run the skill's Python API, which validates every key/value against
`assets/nextflow_schema.json` and writes only non-default values:

```bash
python3 scripts/build_job.py \
    --input /data/$USER/PROJECT/samplesheet.csv \
    --resdir /data/$USER/PROJECT/spatialvi \
    --set spaceranger_reference=/data/$USER/references/refdata-gex-GRCm39-2024-A \
    --dest /data/$USER/PROJECT/spatialvi
```
- With no `--set`, `params.yml` is written empty (all pipeline defaults) — valid, since `input`
  and `outdir` are supplied as CLI flags in the run script.
- Values are validated: unknown keys or out-of-enum values (e.g. `hd_bin_size`, `hvg_flavor`,
  `integration_method`, `rank_genes_method`, `svg_autocorr_method`, `spatial_coord_type`) are
  rejected with a hard error naming the offender.
- To tune process resources, pass `--resource 'process_high:memory=128.GB'` (repeatable); this
  writes a `custom.config` and you then add `-c custom.config` to the run command (DESIGN.md §4.6).

## 5. Fill the SLURM template
`build_job.py` also writes the filled `run_nfcore_spatialvi.sh` (samplesheet + resdir lines set)
into `--dest`. Confirm the `#SBATCH --time`/`--cpus-per-task` suit the run and that the pinned
`main.nf` path (`/nfsdata/scripts/nf-core/dev/spatialvi/main.nf`, `UKDRI/spatialvi@dev_ukdri`
commit `c49fcc5`) exists on the cluster — this is a dev build, not a tagged release.

## 6. Hand back
Tell the user the paths of the generated `run_nfcore_spatialvi.sh` and `params.yml`, and that the
**`slurm` skill** takes it from here: it transfers both files to the HPC, submits
`run_nfcore_spatialvi.sh` with `sbatch` (from the directory holding `params.yml`, which the script
references by relative path), and reports the job id. Running `sbatch run_nfcore_spatialvi.sh` on the
cluster by hand is equally fine. Never submit the job yourself from this skill.

## Custom-config recommendations
(None specific to spatialvi yet. Space Ranger and integration are the heaviest steps — scale the
relevant `withName`/`withLabel` memory/cpus for large Visium HD runs or many samples as needed —
see DESIGN.md §4.6 and `assets/base.config` for the default selectors.)

## Species / reference
spatialvi is species-dependent via its Space Ranger reference (`spaceranger_reference`), for which
there is no house default path — set it explicitly with `--set spaceranger_reference=/path/to/ref`.
(The pipeline auto-downloads a human GRCh38 reference by default.) There is no `--species` flag for
this skill: `<repo-root>/assets/genomes.json` carries no Space Ranger reference, so the skill declares
no `species_map`.
