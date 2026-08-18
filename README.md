# informatics_pipeline_skills

A collection of Claude Code **skills** for running Nextflow nf-core-style pipelines on the UKDRI SLURM
cluster. There are two kinds:

- **Pipeline skills** — one per pipeline. Each produces a ready-to-submit **SLURM job script** and a
  validated **`params.yml`** (plus, optionally, a custom process-resource config). They generate files
  and nothing else.
- **The `slurm` skill** — runs those job scripts on the cluster: transfer, submit, job status, cancel,
  and cleanup of intermediate files.

## Pipelines

| Skill | Pipeline |
|---|---|
| `nf-core_rnaseq` | bulk RNA-seq |
| `nf-core_scrnaseq` | single-cell RNA-seq |
| `nf-core_scdownstream` | single-cell downstream analysis *(UKDRI-modified)* |
| `nf-core_differentialabundance` | differential abundance *(UKDRI-modified)* |
| `nf-core_spatialvi` | spatial transcriptomics |
| `bigbio_quantmsdiann` | DIA proteomics (DIA-NN) |

Each pipeline folder contains its skill definition, job-script template, and pinned reference files.

## Install

Claude Code picks up skills from `~/.claude/skills`. Symlink them from your clone rather than copying,
so a `git pull` updates them in place:

```bash
git clone https://github.com/UKDRI/informatics_pipeline_skills.git
cd informatics_pipeline_skills

mkdir -p ~/.claude/skills
# one symlink per skill you want
ln -s "$PWD"/nf-core_rnaseq                ~/.claude/skills/
ln -s "$PWD"/nf-core_scrnaseq              ~/.claude/skills/
ln -s "$PWD"/nf-core_scdownstream          ~/.claude/skills/
ln -s "$PWD"/nf-core_differentialabundance ~/.claude/skills/
ln -s "$PWD"/nf-core_spatialvi             ~/.claude/skills/
ln -s "$PWD"/bigbio_quantmsdiann           ~/.claude/skills/
ln -s "$PWD"/slurm                         ~/.claude/skills/
```

Or all of them at once:

```bash
mkdir -p ~/.claude/skills
for d in nf-core_* bigbio_* slurm; do ln -s "$PWD/$d" ~/.claude/skills/; done
```

Restart Claude Code (or start a new session) and the skills appear. Verify with `/help` or by asking
for one by name.

**Keep the clone intact.** The symlinks point back into it, and every skill reads the shared
`assets/genomes.json` at the repo root (see below) — so moving or deleting the clone breaks them. The
scripts resolve their own real path through the symlink, so with the symlink install above nothing
else needs linking: `assets/genomes.json` is found inside the clone.

**If you copy the skill folders instead of symlinking them**, copy the shared assets folder too — it
has to sit beside the skill folders, i.e. one level above each skill:

```bash
# only needed for a copy-based install; symlinks find it in the clone
mkdir -p ~/.claude/skills/assets
cp assets/genomes.json ~/.claude/skills/assets/
```

Without it, every species-dependent build stops with
`ERROR: missing shared reference map: …/assets/genomes.json`.

**Requirements** are just Python 3 and `pyyaml` — everything else runs on the cluster:

```bash
python3 -m pip install pyyaml
```

## Reference files

Genome, gene-annotation, gene-set, and protein-database paths are **not** hard-coded in the skills.
They all live in one file at the repo root:

```
assets/genomes.json
```

It maps `mouse` / `human` to the cluster paths for each kind of reference:

| Key | Used for |
|---|---|
| `fasta`, `gtf` | genome sequence and gene annotation (rnaseq, scrnaseq, differentialabundance) |
| `gene_sets_ensg`, `gene_sets_name` | gProfiler gene-set GMTs for enrichment (differentialabundance) |
| `background_gene_names` | gprofiler2 background gene list (differentialabundance, proteomics) |
| `protein_fasta` | UniProt protein database for DIA search (quantmsdiann) |

To point the skills at a different release, add a species, or add a new kind of reference, **edit this
one file** — no Python change is needed anywhere, and the change applies to every skill at once.

**These files must already exist on the HPC before you use the skills.** The skills only write the
paths into `params.yml`; they never upload a reference, and nothing checks that a path exists until the
pipeline runs on the cluster. So if you change an entry here — or add a species — make sure the file is
staged under `/nfsdata/genome/…` on the cluster first, otherwise the job fails at launch. Shared
reference trees are read-only to the skills by design: the `slurm` skill refuses to write into them.

## Cluster operations — the `slurm` skill

| Command | Does |
|---|---|
| `transfer` | upload job scripts, params, samplesheets and input data to the HPC |
| `download` | pull a results directory back — scanned first, big files excluded, max 2 GB |
| `submit` | `sbatch` from the script's own directory; reports the HPC folder and job id; chains one stage behind another with `--after-ok` |
| `job_status` | SLURM state (pending/running/complete/fail/node_fail) plus the current pipeline step |
| `cancel` | `scancel` one job, then suggest cleaning up its work directory |
| `cleanup` | remove intermediate data (`work`, `out`, archives, dataset objects, …) |

It also ships a job template for unpacking `.zip`/`.tar.gz` input archives on the cluster.

**Safety, by design:** it always asks for your username and hostname and never guesses them; it never
uses passwords (passwordless SSH is yours to configure); it refuses to read from or write to anything
outside your own directories or at the top of a hierarchy; it never uses wildcards in a path; and it
changes nothing until it has shown you the exact command and you have confirmed it. Submissions are
capped at 100 jobs.

Downloads are deliberately narrow: only from your own directories **and only files you own** (both the
path and the file ownership are checked), scanned before anything moves, files over 500 MB excluded,
**2 GB total maximum**, and never started without your go-ahead. For the complete results tree — large
files included — you get an `rsync` command to run yourself.

## Key features

- **Validated parameters** — a `params.yml` holds only the values that differ from the pipeline
  defaults. Every parameter name and value is checked against the pipeline's own definition;
  unknown parameters or invalid choices are rejected.
- **Recommended defaults** — each skill ships the UKDRI-recommended settings (e.g. rnaseq
  `aligner: star_rsem`, scrnaseq `aligner: cellranger`), applied automatically and easy to override.
- **Species-aware reference selection** — pick mouse or human and the matching genome, annotation,
  gene-set, and protein-database files are filled in for you from a single shared
  [`assets/genomes.json`](assets/genomes.json); the species can also be inferred from a samplesheet or
  metadata file (scientific names like *Mus musculus* are recognised). Custom paths are always allowed,
  and a run that cannot resolve a species fails loudly rather than quietly using the wrong organism.
- **Validated input sheets** — differentialabundance contrast ids are generated to one convention
  (`condition__treated__vs__control__block__sex__batch`) and checked for characters that would break
  output paths, because each id becomes a results filename and directory prefix. An unsafe or
  duplicated id stops the build instead of surfacing as unusable results hours later.
- **Assay-aware defaults** — where the right settings depend on the assay rather than the pipeline
  (e.g. differentialabundance `--study-type mass_spec` for DIA proteomics), the skill layers the
  matching set of recommended values and switches to the appropriate reference files.
- **Custom resource tuning (optional)** — request more CPUs, memory, or wall-time for specific
  processes when a dataset needs it, without changing the pipeline.
- **Multiple entry points** — pipelines with more than one workflow (e.g. scdownstream's
  `qc_clustering` → `downstream`) get one job script per entry point.
- **Reproducible references** — each skill pins the exact pipeline version (and commit, for
  in-development pipelines) so generated jobs match what actually runs.

## Usage

Invoke the relevant pipeline skill in Claude Code and provide your inputs (typically a
`samplesheet.csv` prepared beforehand, e.g. via the `ena`, `geo`, `arrayexpress`, or `pride`
data-retrieval skills). It gathers your choices and generates the job script and `params.yml`.

Then use the `slurm` skill to transfer those files to the cluster and submit the job — it reports the
HPC folder and job id, and you check progress with `job_status` whenever you like. Submitting with
`sbatch` yourself works just as well.

## For contributors

House style, conventions, and the full specification live in **[`DESIGN.md`](DESIGN.md)**. Read it
before authoring or modifying any skill.
