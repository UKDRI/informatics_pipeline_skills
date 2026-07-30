---
name: slurm
description: >-
  Run and manage jobs on the UKDRI SLURM HPC over SSH: transfer job scripts and input data to the
  cluster, submit them with sbatch, check job status and pipeline progress, cancel a job, download
  results back (max 2 GB, big files excluded), and remove intermediate files. Use after a pipeline
  skill (nf-core_rnaseq, nf-core_scrnaseq, nf-core_scdownstream, nf-core_differentialabundance,
  nf-core_spatialvi, bigbio_quantmsdiann) has generated a run_*.sh + params.yml — triggers:
  "submit", "sbatch", "run the pipeline on the cluster", "job status", "squeue", "sacct",
  "scontrol", "scancel", "cancel job", "transfer to HPC", "rsync to cluster", "copy to the
  cluster", "download results", "pull results", "fetch results", "get results back", "copy results
  from the cluster", "unzip on the cluster", "untar", "clean up work directory", "delete work dir",
  "HPC", "SLURM". Never uses passwords; always asks for the username and hostname; only ever reads
  and writes inside the user's own directories.
---

# slurm — cluster operations (submit, monitor, transfer, download, clean up)

## 1. Purpose
This is the **only** skill that touches the cluster. The pipeline skills generate a `run_*.sh` +
`params.yml` and stop; this skill puts them on the HPC and **starts the run**.

Everything runs through one script, `scripts/slurm_ops.py`, with six subcommands:

| Subcommand | Does |
|---|---|
| `transfer` | upload job scripts, params, samplesheets **and input data** to the HPC |
| `download` | pull a results directory back — scanned first, big files excluded, **max 2 GB** |
| `submit` | `sbatch` the job script from its own directory; reports the HPC folder and job id |
| `job_status` | `sacct`/`scontrol` state + the pipeline step read from the logs |
| `cancel` | `scancel` one job id, then suggest cleaning up its work directory |
| `cleanup` | remove one allow-listed path (`work`, `out`, archives, dataset objects, …) |

Plus one job template, `templates/run_uncompress.sh`, for unpacking a `.zip`/`.tar.gz` on the cluster.

Full specification: DESIGN.md §9. Read it before changing anything here.

## 2. Non-negotiable rules
Follow these exactly, every time. They are enforced in the script too, but they are your rules first.

0. **SCOPE — these rules bind every cluster interaction, however you issue it.** Not just
   `slurm_ops.py` calls: a raw `ssh`, `rsync`, or `scp` run from Bash is bound by all of them too.
   There is no "quick one-off" exemption, and no reason good enough to step outside the script.
   In particular: **pulling data from the HPC is done only with `slurm_ops.py download`** (§4b).
   Never hand-roll an `rsync`/`scp` pull and run it yourself — that route has no scan, no size cap,
   and no path guard. Anything the skill cannot do inside these rules, you hand to the user as a
   command **they** run.
1. **Always ask the user for the HPC `username` and `hostname`.** Never infer them from `$USER`,
   `~/.ssh/config`, an earlier session, git config, the user's email, or a path in the repo. There are
   no defaults. Ask once per conversation and reuse the answer within it.
2. **Never use a password.** Not typed, not stored, not `sshpass`. Everything runs with
   `BatchMode=yes`, so a host without key auth fails immediately.
3. **Passwordless SSH is the user's responsibility.** If a connection fails, say so plainly and tell
   the user to configure key-based SSH themselves — then stop. Never create, edit, or inspect SSH
   keys, `~/.ssh/config`, `known_hosts`, or `authorized_keys`, and never offer to set them up.
4. **Never operate at the top of a hierarchy, and never in another user's space.** A path must be
   absolute, contain the given username, and sit at least one level below the user's directory.
   `/data/<user>/project_1` yes; `/data/<user>`, `/data`, `/scratch`, `/shared/home` no. Same for
   `/nfsdata/<user>`, `/home/<user>`, `/shared/home/<user>`, `/scratch/<user>`. This holds for
   **reads as much as writes** — never download from `/data/<someone-else>/…` or a shared area, and
   never treat "it's only reading" as a reason to relax it. It also holds for **paths the cluster hands
   back**: a `WorkDir` or `StdOut` from `scontrol` can point at a shared area, so it is checked before
   being read or offered as a cleanup target, and reported rather than followed when it fails.
5. **Never delete, overwrite, create, or download anything without the user's permission.** Every
   state-changing subcommand prints its plan and stops; you show that plan to the user, and only
   after they agree do you re-run with `--confirm`. Never pass `--confirm` on the first call.
   **`download` and `cleanup` are never a one-step operation** — always plan, show, wait for the
   user's word, then confirm. A download moves data onto their machine and a cleanup destroys data on
   the cluster; both need the user to say yes first.
6. **Never a glob in a path.** No `rm -rf *`, no `rm -r *`, no wildcards anywhere. One literal full
   path per call: `rm -rf /data/<user>/project_1/nfcore/scrnaseq/work`.
7. **Report faithfully.** Show the user the real command output, the real job id, the real state.

## 3. Ask first, then act
Before the first cluster command, collect:
- **username** and **hostname** (rule 1);
- the **absolute remote directory** for this run (e.g. `/data/<username>/project_1/nfcore/scrnaseq`);
- for `submit`, the **job script path**; for `job_status`/`cancel`, the **job id**; for `download`, the
  **results directory to fetch** and where it should land locally.

If the user gives a relative path, a `~` path, or one still containing `${USER}`/`RESULTS_DIR`
placeholders, ask for the resolved absolute path instead of guessing.

## 4a. transfer — upload files and data
```bash
python3 scripts/slurm_ops.py transfer --user <username> --host <hostname> \
    --path run_nfcore_scrnaseq.sh --path params.yml --path samplesheet.csv \
    --dest /data/<username>/project_1/nfcore/scrnaseq
# → prints the plan; re-run with --confirm once the user agrees
```
- **What to push:** `run_*.sh`, `params.yml` / `params_<entry>.yml`, `custom.config`,
  `samplesheet.csv`, `contrasts.csv` (plural — the differentialabundance parameter is `contrasts`),
  the abundance `matrix` TSV, `*.sdrf.tsv` (quantmsdiann), optionally `metadata.tsv`; **and input
  data**: `fastq`/`sra` directories, Cell Ranger / Space Ranger `outs` directories, `*.raw` files and
  `*.d/` directories, `*.tar.gz`/`*.zip` archives, `*.rds`/`*.pkl`/`*.h5ad` objects, any `*.csv`/`*.tsv`.
- **Keep the job script and its params file in the same directory** — the script references
  `params.yml` and `custom.config` by *relative* path, and `submit` runs `sbatch` from there.
- Add `--progress` for large data (adds `-P`, so an interrupted push resumes).
- An existing remote file is never replaced silently: the plan lists collisions and refuses. Only add
  `--overwrite` if the user explicitly wants them replaced.
- **Genome references are not pushed** — `fasta`/`gtf`/`spaceranger_reference` live on the cluster
  already (`/nfsdata/genome/…`).
- For **public data, suggest the cheaper route**: download it directly on the cluster with the `ena`,
  `geo`, `arrayexpress`, `pride`, `sra`, or `fastq-download-script` skills instead of uploading. It is
  a suggestion — if the user wants their local copy pushed, push it.
- **`--print-only`** prints the `rsync` command for the user to run themselves and transfers nothing.
  Offer this whenever the upload is large or the user would rather drive it (screen/tmux, overnight).

## 4b. download — pull results back (max 2 GB)
**This is the only way you may pull data off the cluster** (rule 0). A hand-rolled `rsync`/`scp` pull
run from Bash is never acceptable.

**Rule 0 for downloads — only the user's own results, checked two ways.** Another user's data is never
downloaded, and there is no override:
1. **The path** must contain the username, under `/data`, `/nfsdata`, `/home`, `/shared/home`, or
   `/scratch`. Another user's directory (`/data/<someone-else>/…`), a shared project area, or any other
   root is refused before a single file is listed.
2. **The ownership** must match — a directory under your own path can still hold someone else's files.
   The script checks the source directory's owner and every file's owner, and **refuses the whole
   download if anything belongs to another user**, naming the files and their owners. Narrow `--remote`
   to a directory holding only the user's own results; never try to filter the foreign files out.

Do not look for a way around either check.

```bash
python3 scripts/slurm_ops.py download --user <username> --host <hostname> \
    --remote /data/<username>/project_1/nfcore/scrnaseq --dest scrnaseq
# → scans, reports what it would fetch, and stops. Show that to the user;
#   only after they agree, re-run with --confirm.
```

**When the user asks to download or pull results, do both of these:**
1. **Give them the `rsync` command** for the complete tree, large files included, to run themselves.
2. **Offer to do it through this skill** instead, within the 2 GB cap — and wait for their answer.
   Never start a download because they mentioned wanting the data.

How it behaves:
- **Scans first** (`find`, read-only), skipping the Nextflow scratch dirs `work` and `.nextflow`
  (add `--include-work` only if the user explicitly wants them).
- **Excludes big files** — anything over 500 MB by default (`--max-file-size 100M` to tighten). The
  plan lists what was excluded and how much it came to.
- **Hard 2 GB cap.** If what remains is still over, it **refuses and transfers nothing**, and shows the
  three ways forward: narrow `--remote` to a subdirectory, lower `--max-file-size`, or run the full
  `rsync` themselves. Do not try to defeat the cap by looping over subdirectories.
- **Local destination** defaults to the basename of `--remote`; a non-empty existing directory is
  refused unless the user asks for `--overwrite`.
- `--print-only` prints the pull command instead of running it; `--progress` adds `-P` for resumability.

**After a download, always hand back two things** (the script prints both — pass them on):
1. The **full-results `rsync`, large files included**, for the user to run themselves:
   ```bash
   rsync -avhP <username>@<hostname>:/data/<username>/project_1/nfcore/scrnaseq scrnaseq
   ```
   Say how many files and how much data it would add, so they can judge whether it is worth it.
2. A **suggestion to run `cleanup`** once they have verified the data locally — with the concrete
   command. **You never run it yourself**: the user reviews `cleanup`'s own plan and confirms it
   (§8). Never chain a cleanup onto a download. Note that `work/` and `.nextflow/` sit in the
   directory the job was *launched* from, which need not be the directory you just downloaded — take
   that path from `job_status` (`scontrol`'s `WorkDir`) rather than assuming.

## 5. submit — start the run
```bash
python3 scripts/slurm_ops.py submit --user <username> --host <hostname> \
    --script /data/<username>/project_1/nfcore/scrnaseq/run_nfcore_scrnaseq.sh --confirm
```
- Checks the **100-job limit** first with `squeue -u <username>` and **refuses** at or above 100
  (running + pending both count). If refused, tell the user to wait or cancel jobs — do not retry.
- Verifies the files the script names by relative path (`-params-file`, `-c`) are present beside it.
- `cd`s into the script's directory before `sbatch`, because those paths are relative.
- **Always report back the HPC folder and the job id**, verbatim, and tell the user the `job_status`
  command for that id. There is no active monitoring — the user asks when they want to know.

## 6. job_status — state and pipeline step
```bash
python3 scripts/slurm_ops.py job_status --user <username> --host <hostname> --jobid 1234567
```
- Reports the state as **pending, running, complete, fail, or node_fail** (the raw SLURM state is
  shown too; `node_fail` means the node died, not the pipeline).
- Reads the SLURM `.out` (via `scontrol`'s `StdOut`) and the `.nextflow.log` in the job's work
  directory, and reports **which pipeline process is currently running**.
- Read-only: never edit, truncate, or delete a log; it tails rather than dumping whole files.
- **No polling.** Run it once when asked. Do not loop, sleep, re-check on a timer, or promise to
  watch the job.
- When the state is `complete`, **offer both retrieval routes** and let the user pick (§4b) — default to
  the whole results directory, which holds `out/`, `nextflow_report.html`, and the job's `*.sh`/`*.out`
  copies:
  ```bash
  # through this skill — capped at 2 GB, big files excluded, shows a plan first
  python3 scripts/slurm_ops.py download --user <username> --host <hostname> \
      --remote /data/<username>/project_1/nfcore/scrnaseq
  # or the complete tree, large files included — the user runs this themselves
  rsync -avhP <username>@<hostname>:/data/<username>/project_1/nfcore/scrnaseq scrnaseq
  ```
  Remote source without a trailing slash; the local destination is a new folder, so run it where that
  name is free or rsync nests it. Mention that `cleanup` can free the run's scratch once the data is
  safely local — as a suggestion, not an action.

## 7. cancel — stop one job
```bash
python3 scripts/slurm_ops.py cancel --user <username> --host <hostname> --jobid 1234567 --confirm
```
- One job id only. Never a mass cancel (`scancel -u`), a range, or a wildcard.
- Verifies the job belongs to the given username, shows the job name, state, and work dir, and
  requires confirmation — cancelling ends real compute.
- Afterwards it **suggests** `cleanup` of that run's `work` directory (a cancelled run leaves a large
  half-finished tree). Pass that suggestion on; never chain the deletion automatically. If the user
  intends to `-resume`, tell them to keep `work`.

## 8. cleanup — remove intermediate data
```bash
python3 scripts/slurm_ops.py cleanup --user <username> --host <hostname> \
    --path /data/<username>/project_1/nfcore/scrnaseq/work --confirm
```
Only these are removable, matched on the final path component:

| Kind | Removable |
|---|---|
| Directories | `work`, `out`, `outs`, `sra`, `fastq`, `.nextflow`, `*.zarr`, `*.d` |
| Files | `*.zip`, `*.tar.gz`, `*.gz`, `*.rds`, `*.h5ad`, `*.h5`, `*.pkl`, `*.h5seurat`, `*.raw` |

- Everything else is refused — a results directory other than `out`/`outs`, the run directory itself,
  `params.yml`, job scripts, samplesheets, logs, reports.
- **Never a one-step operation** (rule 5). Run it without `--confirm` first, show the user the plan it
  prints — target, kind, size, contents — and only re-run with `--confirm` once they say yes. Suggesting
  a cleanup (after a download, or after a cancel) is not the same as being told to do it.
- It prints the target's size and contents, and requires confirmation.
- **Name the cost when it matters:** `out`/`outs` are results, not scratch;
  `integrated_scvi_finalized.h5ad` is the `--base_adata` input of scdownstream's `downstream` entry
  (re-making it means re-running `qc_clustering`); `.raw`/`.d`/`fastq`/`sra` data must be
  re-downloaded before a run can be repeated.
- To clear several files of one kind, list them first, show the user, then remove them **one explicit
  path at a time**. Never a glob.

## 9. Unpacking archives on the cluster
Compressed input data (PRIDE `.zip`, `.tar.gz` elsewhere) is unpacked by a **job**, never on a login
node. Copy `templates/run_uncompress.sh` into the user's run directory, set the two paths, transfer it,
and submit it like any other job script:

```bash
# in the copy: set the archive and the destination
archive=/data/<username>/project_1/PXD000000.zip
destdir=/data/<username>/project_1/raw
```
- It lists the archive first (`unzip -l` / `tar -tzf`) so the job log records what was unpacked, then
  extracts with `unzip -n` / `tar -xzkf` — **existing files are kept, never overwritten**. Only switch
  to an overwriting form if the user explicitly asks.
- Refuse an archive whose listing shows absolute or `../` member paths.
- It does **not** delete the archive. Afterwards, the `.zip`/`.tar.gz` is a normal `cleanup` target.
- Confirm the `#SBATCH --time` suits the archive size (the template ships `12:00:00`).

## 10. Hand back
After any operation, tell the user plainly: the exact HPC folder, the job id, the state, and the next
command they can run — `job_status` for that id, `download` or the full `rsync` to fetch results (§4b),
`cleanup` to free space once the data is local. If something was refused — the job cap, the 2 GB
download cap, a path outside their own directories, a non-allow-listed cleanup target, an SSH auth
failure — say which rule refused it and what they can do instead. Never present a suggestion you made
(a cleanup, a bigger download) as something already done.
