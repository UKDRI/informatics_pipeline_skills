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
genes and multi-sample integration). The repo does not execute the pipeline; the user submits the
script with `sbatch` on the cluster.

**Dev pipeline.** spatialvi is tracked on the `dev` branch (version `1.0dev`, commit `d0fd35d`).
The template pins `main=/nfsdata/scripts/nf-core/dev/spatialvi/main.nf` — a dev build, not a
release tag; confirm the exact path on the cluster before submitting.

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
`integration_method` (`harmony`|`scanorama`), and `skip_integration` for single-sample runs.
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
into `--dest`. Confirm the `#SBATCH --time`/`--cpus-per-task` suit the run and that the pinned dev
`main.nf` path (`/nfsdata/scripts/nf-core/dev/spatialvi/main.nf`, commit `d0fd35d`) exists on the
cluster — this is a dev build, not a tagged release.

## 6. Hand back
Tell the user the paths of the generated `run_nfcore_spatialvi.sh` and `params.yml`, and that they
submit with `sbatch run_nfcore_spatialvi.sh` from the results directory.

## Custom-config recommendations
(None specific to spatialvi yet. Space Ranger and integration are the heaviest steps — scale the
relevant `withName`/`withLabel` memory/cpus for large Visium HD runs or many samples as needed —
see DESIGN.md §4.6 and `assets/base.config` for the default selectors.)

## Species / reference
spatialvi is species-dependent via its Space Ranger reference (`spaceranger_reference`), for which
there is no house default path — set it explicitly with `--set spaceranger_reference=/path/to/ref`.
(The pipeline auto-downloads a human GRCh38 reference by default.) There is no `--species` flag for
this skill because no default reference paths are stored.
