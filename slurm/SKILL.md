---
name: slurm
description: >-
  Run and manage jobs on the UKDRI SLURM HPC over SSH: transfer job scripts and input data to the
  cluster, submit them with sbatch, check job status and pipeline progress, cancel a job, and remove
  intermediate files. Use after a pipeline skill (nf-core_rnaseq, nf-core_scrnaseq,
  nf-core_scdownstream, nf-core_differentialabundance, nf-core_spatialvi, bigbio_quantmsdiann) has
  generated a run_*.sh + params.yml — triggers: "submit", "sbatch", "run the pipeline on the
  cluster", "job status", "squeue", "sacct", "scontrol", "scancel", "cancel job", "transfer to
  HPC", "rsync to cluster", "copy to the cluster", "unzip on the cluster", "untar", "clean up work
  directory", "delete work dir", "HPC", "SLURM". Never uses passwords; always asks for the username
  and hostname.
---

# slurm — cluster operations (submit, monitor, transfer, clean up)

## 1. Purpose
This is the **only** skill that touches the cluster. The pipeline skills generate a `run_*.sh` +
`params.yml` and stop; this skill puts them on the HPC and **starts the run**. It also fetches nothing:
results retrieval is always a command handed to the user.

Everything runs through one script, `scripts/slurm_ops.py`, with five subcommands:

| Subcommand | Does |
|---|---|
| `transfer` | push job scripts, params, samplesheets **and input data** to the HPC (push only) |
| `submit` | `sbatch` the job script from its own directory; reports the HPC folder and job id |
| `job_status` | `sacct`/`scontrol` state + the pipeline step read from the logs |
| `cancel` | `scancel` one job id, then suggest cleaning up its work directory |
| `cleanup` | remove one allow-listed path (`work`, `out`, archives, dataset objects, …) |

Plus one job template, `templates/run_uncompress.sh`, for unpacking a `.zip`/`.tar.gz` on the cluster.

Full specification: DESIGN.md §9. Read it before changing anything here.

## 2. Non-negotiable rules
Follow these exactly, every time. They are enforced in the script too, but they are your rules first.

1. **Always ask the user for the HPC `username` and `hostname`.** Never infer them from `$USER`,
   `~/.ssh/config`, an earlier session, git config, the user's email, or a path in the repo. There are
   no defaults. Ask once per conversation and reuse the answer within it.
2. **Never use a password.** Not typed, not stored, not `sshpass`. Everything runs with
   `BatchMode=yes`, so a host without key auth fails immediately.
3. **Passwordless SSH is the user's responsibility.** If a connection fails, say so plainly and tell
   the user to configure key-based SSH themselves — then stop. Never create, edit, or inspect SSH
   keys, `~/.ssh/config`, `known_hosts`, or `authorized_keys`, and never offer to set them up.
4. **Never operate at the top of a hierarchy.** A path must be absolute, contain the given username,
   and sit at least one level below the user's directory. `/data/<user>/project_1` yes;
   `/data/<user>`, `/data`, `/scratch`, `/shared/home` no. Same for `/nfsdata/<user>`,
   `/home/<user>`, `/shared/home/<user>`, `/scratch/<user>`.
5. **Never delete, overwrite, or create anything without the user's permission.** Every
   state-changing subcommand prints its plan and stops; you show that plan to the user, and only
   after they agree do you re-run with `--confirm`. Never pass `--confirm` on the first call.
6. **Never a glob in a path.** No `rm -rf *`, no `rm -r *`, no wildcards anywhere. One literal full
   path per call: `rm -rf /data/<user>/project_1/nfcore/scrnaseq/work`.
7. **Report faithfully.** Show the user the real command output, the real job id, the real state.

## 3. Ask first, then act
Before the first cluster command, collect:
- **username** and **hostname** (rule 1);
- the **absolute remote directory** for this run (e.g. `/data/<username>/project_1/nfcore/scrnaseq`);
- for `submit`, the **job script path**; for `job_status`/`cancel`, the **job id**.

If the user gives a relative path, a `~` path, or one still containing `${USER}`/`RESULTS_DIR`
placeholders, ask for the resolved absolute path instead of guessing.

## 4. transfer — push files and data (push only)
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
- When the state is `complete`, give the user the `rsync` command to fetch results — default to the
  whole results directory (it holds `out/`, `nextflow_report.html`, and the job's `*.sh`/`*.out`
  copies), or just `out/` if they only want pipeline outputs:
  ```bash
  rsync -avh <username>@<hostname>:/data/<username>/project_1/nfcore/scrnaseq scrnaseq
  ```
  Remote source without a trailing slash; the local destination is a new folder, so run it where that
  name is free or rsync nests it.

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
command they can run (`job_status` for that id, or the `rsync` to fetch results). If something was
refused — the job cap, a path outside their directories, a non-allow-listed cleanup target, an SSH
auth failure — say which rule refused it and what they can do instead.
