---
name: nf-core_sopa
description: >-
  Build a SLURM job script + params.yml for an nf-core/sopa run on the UKDRI cluster. Use when the
  user wants cell segmentation and per-cell aggregation of imaging-based spatial omics data with
  nf-core:sopa — triggers: "sopa", "nf-core sopa", "CosMx", "NanoString CosMx", "Bruker CosMx",
  "Xenium", "MERSCOPE", "Vizgen", "Visium HD", "PhenoCycler", "CODEX", "Hyperion", "MACSima",
  "imaging spatial transcriptomics", "spatial proteomics", "cell segmentation", "Cellpose",
  "Proseg", "Baysor", "SpatialData", "zarr", "Xenium Explorer", plus "samplesheet", "params.yml",
  "slurm job". Produces files only; never runs the pipeline.
---

# nf-core:sopa — job builder

## 1. Purpose
Generate a ready-to-submit SLURM job script and a validated `params.yml` for the nf-core/sopa
pipeline (<https://github.com/nf-core/sopa>, release **`1.0.1`**). Sopa reads the raw output of a
spatial omics instrument, segments cells (Cellpose / Stardist on the stains, Proseg / Baysor /
Comseg on the transcripts), aggregates transcripts and channel intensities per cell, and writes a
SpatialData object plus a Xenium Explorer view. This skill only produces files. The generated job
script is what the **`slurm` skill** uses to transfer the run to the HPC and submit it.

Usage docs: <https://nf-co.re/sopa/1.0.1/docs/usage> — but the parameter set this skill validates
against is the pinned `assets/nextflow_schema.json`.

**Cluster prerequisites:**
- **Nextflow ≥ 25.10.4** — sopa refuses to start with anything older (`manifest.nextflowVersion =
  '!>=25.10.4'`). The job runs the command in `<repo-root>/assets/cluster.json` (`nextflow`):
  make sure that resolves to a recent enough version on the cluster.
- The sopa 1.0.1 checkout at the `main` path in `<repo-root>/assets/cluster.json` (marked
  "confirm path on cluster"). Use `--main /path/main.nf` for another checkout.

## 2. Required inputs
A **`samplesheet.csv`** passed with `--input`. No spaces anywhere in a value, and every path must
exist **on the cluster** (the pipeline checks them). Two layouts:

**All technologies except Visium HD** — one row per sample/region:
```csv
sample,data_path
slide1_region1,/data/<user>/PROJECT/cosmx/slide1_region1
slide2_region1,/data/<user>/PROJECT/cosmx/slide2_region1
```
`sample` is optional (default: the basename of `data_path`) and names the outputs
`{sample}.zarr` / `{sample}.explorer`; keep it unique. What `data_path` must contain:

| `--technology` | `data_path` |
|---|---|
| `cosmx` | a directory with `*_fov_positions_file.csv[.gz]`, the `Morphology2D/` directory of per-FOV images, and `*_tx_file.csv[.gz]` (the flat-file export of one slide) |
| `xenium` | the Xenium output directory: `transcripts.parquet`, `experiment.xenium`, `morphology_focus.ome.tif` (or a morphology directory) |
| `merscope` | `detected_transcripts.csv`, `images/` and `images/micron_to_mosaic_pixel_transform.csv` |
| `molecular_cartography` | `.tiff` images and `_results.txt` files |
| `macsima`, `hyperion` | a directory of `.tif` images |
| `phenocycler` | **a file**: the `.qptiff` / `.tif` with all channels |
| `ome_tif` | **a file**: the `.ome.tif` with all channels |

**Visium HD** — Space Ranger runs first, so the sheet is
`sample,fastq_dir,image,cytaimage,slide,area` (+ optional `id`, `manual_alignment`, `slidefile`,
`colorizedimage`, `darkimage`). `image` is the full-resolution microscopy image (sopa segments it),
not the CytAssist image.

If the samplesheet does not exist yet, write it with the user — never invent sample names or paths.

## 3. Gather parameters
Ask the user for:
- the **technology** — required, `--technology <value>`; there is no default (upstream's `xenium`
  default is never assumed);
- the samplesheet path and a results directory on `/data`;
- the **segmentation** — offer the technology's default (§4) and the alternatives;
- optional extras: `use_scanpy_preprocessing: true` (adds a UMAP and Leiden clustering, set
  `resolution`), `use_tissue_segmentation: true` (only segment inside the tissue),
  `min_transcripts` (cells with fewer are dropped).

## 4. Segmentation — the technology overlays
Upstream chooses technology and segmentation with a predefined `-profile` (e.g. `cosmx_proseg`).
Those presets only set ordinary parameters, so this skill writes them into `params.yml` instead
(DESIGN.md §5): `--technology` writes `technology` and layers `templates/params_<technology>.yml` —
a translation of one preset — over `templates/params.yml`. All 22 upstream presets are pinned in
`assets/predefined/*.config` for reference.

| `--technology` | Default overlay | Source |
|---|---|---|
| `cosmx` | **Cellpose → Proseg**: Cellpose on the `DNA` stain (diameter 60 px), then Proseg refines the cells from the transcripts with the Cellpose boundaries as its prior | **UKDRI composition**: `cosmx_cellpose` + `use_proseg: true`, `patch_width_microns: -1` |
| `xenium` | Proseg, 10x segmentation as prior | `xenium_proseg` |
| `merscope` | Proseg, Vizgen segmentation as prior | `merscope_proseg` |
| `visium_hd` | Proseg, Space Ranger segmentation as prior | `visium_hd_proseg` |
| `phenocycler` | Cellpose on DAPI, **20X** | `phenocycler_base_20X` |
| `hyperion` | Cellpose on DNA1 | `hyperion_base` |
| `macsima` | Cellpose on DAPI | `macsima_base` |
| `molecular_cartography`, `ome_tif` | **none** — no upstream preset | ask the user for a segmentation method and its params |

**Another preset or method.** Read the matching `assets/predefined/<preset>.config`, and pass its
values as `--set key=value` overrides — plus `--set use_<method>=false` for any method the overlay
turned on that the new choice does not use. E.g. CosMx with upstream's Proseg-only preset (CosMx's
own segmentation as the prior):
```bash
--set use_cellpose=false --set prior_shapes_key=auto
```
(the overlay's Cellpose keys are then simply unused). For PhenoCycler at 10X / 40X, take the values
from `phenocycler_base_10X` / `_40X`.

**Method rules** — sopa checks them at launch, so get them right here:
- at most **one staining-based** method (`use_cellpose` | `use_stardist`) and at most **one
  transcript-based** method (`use_proseg` | `use_baysor` | `use_comseg`);
- Stardist combines only with Proseg;
- Proseg runs on **one** transcript patch (`patch_width_microns: -1`) and needs a prior: with
  Cellpose on, the prior is `cellpose_boundaries` automatically; otherwise set `prior_shapes_key`
  (`auto` = the instrument's own segmentation).

**CosMx tuning.** `cellpose_diameter` and `min_area_pixels2` are in **pixels** of the morphology
images. If cells look over- or under-split in the report, adjust the two together.
`cellpose_channels` must name a morphology channel present in the data — upstream's CosMx presets
use `DNA`; check the channel names of the user's run if Cellpose finds no cells.

## 5. Generate `params.yml` (+ optional custom config)
```bash
python3 scripts/build_job.py --technology cosmx \
    --input  /data/$USER/PROJECT/sopa/samplesheet.csv \
    --resdir /data/$USER/PROJECT/sopa/cosmx_run1 \
    --dest   /data/$USER/PROJECT/sopa/cosmx_run1
```
- Add or override any parameter with `--set key=value` (repeatable).
- Unknown keys or out-of-enum values are rejected with a hard error naming the offender.
- `params.yml` keeps only non-default values, so `technology: xenium` (the pipeline default) is
  omitted from a Xenium run even though `--technology xenium` was given.

## 6. Fill the SLURM template
`build_job.py` writes the filled `run_nfcore_sopa.sh` into `--dest`: `exec=` and `main=` from
`<repo-root>/assets/cluster.json`, the `samplesheet=` and `resdir=` lines from `--input`/`--resdir`.
The script runs `-profile apptainer` (no GPU: the presets run Cellpose on CPU) and passes
`-params-file params.yml`. Confirm `#SBATCH --time` suits the run; large CosMx slides with many
FOVs take hours.

## 7. Hand back
Tell the user the paths of the generated `run_nfcore_sopa.sh` and `params.yml`, and that the
**`slurm` skill** transfers them (with the samplesheet) and submits the job. Outputs land in
`$resdir/out`:
- `{sample}.zarr/` — the SpatialData object (images, cell shapes, transcripts, the AnnData table).
  This is the **result**, not scratch.
- `{sample}.explorer/` — `report.html` (sopa QC), `adata.h5ad`, and `experiment.xenium` to open in
  the 10x Xenium Explorer.
- Visium HD only: `{sample}_spaceranger/outs`.

These are usually far above the `slurm` skill's 2 GB download cap: offer its `download` for the
`report.html`/`adata.h5ad`, and hand over the `rsync` command for the full `.zarr` / `.explorer`.

## Custom-config recommendations
No UKDRI-specific recommendation yet. Proseg runs as one `process_high` task per sample (on the
single transcript patch) and Cellpose as one `process_single` task per image patch. If a large slide
runs out of memory, raise the matching label, e.g. `--resource process_high:memory=...` (see
`assets/base.config` for the defaults and selectors).

## Species / reference
No species parameter: segmentation and aggregation use no genome reference. Visium HD is the
exception — Space Ranger's `spaceranger_reference` defaults to an auto-downloaded human GRCh38
reference (set it explicitly for mouse, or when compute nodes have no internet), and it needs
`spaceranger_probeset` (the official 10x probe set CSV for the panel).

## Deltas from upstream usage
- The technology/segmentation `-profile` is replaced by `params.yml` overlays (§4); the job script
  uses only `-profile apptainer`.
- CosMx defaults to a UKDRI Cellpose → Proseg composition rather than one of upstream's presets.
- `expand_radius_ratio` is written as a quoted string in the imaging overlays: the pinned schema
  types it as a string, while upstream's presets give a bare number.
