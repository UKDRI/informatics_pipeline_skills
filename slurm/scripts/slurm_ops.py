#!/usr/bin/env python3
"""Cluster operations for the UKDRI SLURM HPC: transfer, download, submit, job_status, cancel, cleanup.

The operations skill of this repository (see repo DESIGN.md §9). Pipeline skills
generate a job script + params.yml and stop; this script is what puts them on the
cluster and starts the run.

Hard rules implemented here (DESIGN.md §9.2, §9.3):
  * --user and --host are REQUIRED on every subcommand and are never inferred from
    the environment, ~/.ssh/config, or anywhere else.
  * No passwords, ever: ssh/rsync run with BatchMode=yes, so an unconfigured host
    fails fast instead of prompting. Passwordless SSH is the user's own setup.
  * Every remote path must sit inside one of the user's own standard directories,
    at least one level below it, absolute and glob-free. This applies to a download
    SOURCE as much as to a write target: data is never pulled from another user's
    directory, and there is no flag to override that.
  * Nothing is created, overwritten, or deleted without --confirm: without it every
    state-changing subcommand prints its plan and stops. A download writes to the
    local disk, so it is gated the same way.
  * A download is capped at MAX_DOWNLOAD_BYTES in total with big files excluded; it
    is refused, never silently truncated, when the scan comes out over the cap.
  * Every remote command is echoed before it runs.

Stdlib only.
"""
from __future__ import annotations

import argparse
import os
import posixpath
import re
import shlex
import subprocess
import sys

# --------------------------------------------------------------------------- #
# Constants (DESIGN.md §9.3, §9.4.1, §9.4.3)
# --------------------------------------------------------------------------- #
# Never prompt for a password; key-based auth only.
SSH_OPTS = ["-o", "BatchMode=yes"]

# The user's own standard directories. A remote path must start with one of these
# followed by the username, and must go at least one component deeper.
USER_DIR_PREFIXES = (
    "/data",
    "/nfsdata",
    "/home",
    "/shared/home",
    "/scratch",
)

# A user may have at most this many jobs in the queue (running + pending).
MAX_JOBS = 100

# `download` limits. The total is a hard ceiling: no flag raises it. Files above the
# per-file threshold are excluded from what the skill pulls; the user fetches those
# themselves with the full rsync command the skill prints.
MAX_DOWNLOAD_BYTES = 2 * 1024 ** 3              # 2 GiB total per download
DEFAULT_MAX_FILE_SIZE_BYTES = 500 * 1024 ** 2   # "big file" = larger than 500 MiB
# Nextflow scratch: never part of a results download unless explicitly asked for.
DOWNLOAD_SKIP_DIRS = ("work", ".nextflow")

# What `cleanup` may remove — matched on the final path component.
CLEANUP_DIR_NAMES = {"work", "out", "outs", "sra", "fastq", ".nextflow"}
CLEANUP_DIR_SUFFIXES = (".zarr", ".d")
CLEANUP_FILE_SUFFIXES = (
    ".zip", ".tar.gz", ".tgz", ".gz",          # compressed inputs
    ".rds", ".h5ad", ".h5", ".pkl", ".h5seurat",  # dataset objects
    ".raw",                                    # proteomics raw files
)
# Results directories: removable, but the user is told they are results, not scratch.
CLEANUP_RESULT_DIRS = {"out", "outs"}

GLOB_CHARS = "*?[]{}"

# SLURM state -> the five states reported to the user.
STATE_MAP = {
    "PENDING": "pending",
    "CONFIGURING": "pending",
    "REQUEUED": "pending",
    "RUNNING": "running",
    "COMPLETING": "running",
    "RESIZING": "running",
    "SUSPENDED": "running",
    "STAGE_OUT": "running",
    "COMPLETED": "complete",
    "NODE_FAIL": "node_fail",
    "FAILED": "fail",
    "TIMEOUT": "fail",
    "OUT_OF_MEMORY": "fail",
    "BOOT_FAIL": "fail",
    "DEADLINE": "fail",
    "PREEMPTED": "fail",
    "CANCELLED": "fail",
    "REVOKED": "fail",
}


# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #
def die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    sys.stdout.flush()          # keep the plan above the error, not after it
    sys.stderr.write(f"ERROR: {msg}\n")
    raise SystemExit(code)


def warn(msg: str) -> None:
    sys.stdout.flush()
    sys.stderr.write(f"WARNING: {msg}\n")


def info(msg: str) -> None:
    print(msg)


def die_needs_confirm(what: str) -> "NoReturn":  # type: ignore[name-defined]
    """Stop after printing the plan. The user's go-ahead becomes --confirm."""
    info("")
    info(f"Nothing has been changed. {what}")
    info("Re-run the same command with --confirm to proceed.")
    raise SystemExit(0)


def human_size(num: int) -> str:
    """Bytes as a short 1024-based string, matching rsync's K/M/G suffixes."""
    value = float(num)
    for unit in ("B", "K", "M", "G", "T"):
        if value < 1024 or unit == "T":
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}T"


def parse_size(text: str) -> int:
    """'500M' / '2G' / '1048576' -> bytes (1024-based, as rsync reads them)."""
    s = text.strip().upper().rstrip("B")
    if not s:
        die(f"could not read a size from {text!r}")
    mult = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}.get(s[-1])
    number = s[:-1] if mult else s
    try:
        return int(float(number) * (mult or 1))
    except ValueError:
        die(f"could not read a size from {text!r} — use forms like 500M, 2G, or a byte count.")


# --------------------------------------------------------------------------- #
# Path guard (DESIGN.md §9.3)
# --------------------------------------------------------------------------- #
def guard_path(path: str, username: str) -> str:
    """Validate a remote path and return it normalised.

    All of these must hold: absolute; no glob, '~' or unexpanded '$VAR'; inside one
    of USER_DIR_PREFIXES as <prefix>/<username>/...; at least one level below that
    user directory. Anything else is refused, naming the check that failed.
    """
    if not path:
        die("empty remote path.")
    if not path.startswith("/"):
        die(f"remote path is not absolute: {path!r} (§9.3 rule 1). Give the full path.")
    if "~" in path:
        die(f"remote path contains '~': {path!r} (§9.3 rule 1). Give the full path.")
    if "$" in path:
        die(
            f"remote path contains an unexpanded variable: {path!r} (§9.3 rule 1). "
            "Templates use ${USER}/PLACEHOLDER forms; pass the resolved path instead."
        )
    if any(c in path for c in GLOB_CHARS):
        die(f"remote path contains a wildcard: {path!r} (§9.3 rule 4). Name one literal path.")

    clean = posixpath.normpath(path)
    if clean != path.rstrip("/") and clean != path:
        die(f"remote path is not normalised: {path!r} — pass {clean!r} instead.")
    if ".." in clean.split("/"):
        die(f"remote path contains '..': {path!r} (§9.3 rule 1).")

    for prefix in USER_DIR_PREFIXES:
        userdir = f"{prefix}/{username}"
        if clean == prefix or clean == userdir:
            die(
                f"refusing to operate on {clean!r}: that is a top-level or user directory "
                f"(§9.3 rule 3). Give a path at least one level below {userdir}."
            )
        if clean.startswith(userdir + "/"):
            return clean

    allowed = ", ".join(f"{p}/{username}/..." for p in USER_DIR_PREFIXES)
    die(
        f"remote path {clean!r} is outside the user's own directories (§9.3 rule 2). "
        f"It must contain the username {username!r} under one of: {allowed}"
    )


def in_user_path(path: str, username: str) -> bool:
    """True if `path` passes the §9.3 guard — without exiting on failure.

    For paths the CLUSTER hands back (scontrol WorkDir/StdOut, sacct fields): they
    are checked before being read or offered, so a job that ran outside the user's
    own directories is reported rather than followed.
    """
    if not path or not path.startswith("/") or "~" in path or "$" in path:
        return False
    if any(c in path for c in GLOB_CHARS):
        return False
    clean = posixpath.normpath(path)
    if ".." in clean.split("/"):
        return False
    return any(
        clean.startswith(f"{prefix}/{username}/") for prefix in USER_DIR_PREFIXES
    )


def require_user_path(path: str, username: str, what: str) -> str:
    """Guard a cluster-reported path before reading it; empty string if it fails."""
    if not path:
        return ""
    if not in_user_path(path, username):
        warn(
            f"{what} is outside {username}'s own directories: {path} — not reading it "
            "(§9.3 applies to paths the cluster reports back, not just paths you type)."
        )
        return ""
    return path


def cleanup_kind_allowed(path: str, kind: str) -> tuple[bool, str]:
    """Check a cleanup target against the allow-list (DESIGN.md §9.4.1).

    Returns (allowed, reason). Directory names match directories only; file
    extensions match files only; '.zarr'/'.d' are directories.
    """
    name = posixpath.basename(path)
    if kind == "dir":
        if name in CLEANUP_DIR_NAMES:
            return True, f"directory named {name!r}"
        for suffix in CLEANUP_DIR_SUFFIXES:
            if name.endswith(suffix) and name != suffix:
                return True, f"{suffix} directory"
        return False, (
            f"directory {name!r} is not a removable kind. Removable directories are: "
            + ", ".join(sorted(CLEANUP_DIR_NAMES))
            + ", or a *"
            + "/*".join(CLEANUP_DIR_SUFFIXES)
            + " directory"
        )
    if kind == "file":
        for suffix in CLEANUP_FILE_SUFFIXES:
            if name.endswith(suffix) and name != suffix:
                return True, f"{suffix} file"
        return False, (
            f"file {name!r} is not a removable kind. Removable extensions are: "
            + ", ".join(CLEANUP_FILE_SUFFIXES)
        )
    return False, f"{path} does not exist on the cluster"


# --------------------------------------------------------------------------- #
# SSH plumbing — argument lists only, never shell=True locally
# --------------------------------------------------------------------------- #
def target(user: str, host: str) -> str:
    return f"{user}@{host}"


def echo_cmd(argv: list) -> None:
    """Show the user exactly what is about to run (DESIGN.md §9.6)."""
    info("$ " + " ".join(shlex.quote(a) for a in argv))


def check_auth_failure(argv: list, res: subprocess.CompletedProcess) -> None:
    """Turn an SSH auth/connection failure into a clear stop (DESIGN.md §9.2)."""
    err = (res.stderr or "")
    markers = (
        "Permission denied",
        "publickey",
        "Host key verification failed",
        "Could not resolve hostname",
        "Connection refused",
        "Connection timed out",
        "No route to host",
    )
    if res.returncode != 0 and any(m in err for m in markers):
        sys.stderr.write(err if err.endswith("\n") else err + "\n")
        die(
            "SSH could not connect or authenticate. This skill never uses passwords: "
            "configure passwordless (key-based) SSH to the host yourself, then try again. "
            "Setting up SSH keys is outside this skill's scope."
        )


def run_local(argv: list, echo: bool = True, check: bool = True) -> subprocess.CompletedProcess:
    if echo:
        echo_cmd(argv)
    res = subprocess.run(argv, capture_output=True, text=True)
    check_auth_failure(argv, res)
    if check and res.returncode != 0:
        if res.stderr:
            sys.stderr.write(res.stderr if res.stderr.endswith("\n") else res.stderr + "\n")
        die(f"command failed with exit status {res.returncode}: {' '.join(argv[:3])} ...")
    return res


def run_remote(
    user: str, host: str, remote_argv: list, echo: bool = True, check: bool = True
) -> subprocess.CompletedProcess:
    """Run one command on the cluster.

    remote_argv is quoted with shlex so no path can be re-split or re-expanded by
    the remote shell (DESIGN.md §9.3).
    """
    remote_cmd = " ".join(shlex.quote(a) for a in remote_argv)
    argv = ["ssh"] + SSH_OPTS + [target(user, host), remote_cmd]
    return run_local(argv, echo=echo, check=check)


def remote_kind(user: str, host: str, path: str) -> str:
    """'dir', 'file' or 'missing' — a read-only probe."""
    res = run_remote(
        user, host,
        ["sh", "-c", f'if [ -d {shlex.quote(path)} ]; then echo dir; '
                     f'elif [ -e {shlex.quote(path)} ]; then echo file; else echo missing; fi'],
        echo=False, check=True,
    )
    return res.stdout.strip() or "missing"


def remote_text(user: str, host: str, argv: list) -> str:
    """Read-only remote command whose stdout we want; empty string on failure."""
    res = run_remote(user, host, argv, echo=False, check=False)
    return res.stdout if res.returncode == 0 else ""


# --------------------------------------------------------------------------- #
# transfer (DESIGN.md §9.4.0)
# --------------------------------------------------------------------------- #
def rsync_argv(sources: list, user: str, host: str, dest: str, progress: bool) -> list:
    argv = ["rsync", "-avh"]
    if progress:
        argv.append("-P")           # --partial --progress: an interrupted push resumes
    argv += ["-e", "ssh " + " ".join(SSH_OPTS)]
    argv += sources
    argv.append(f"{target(user, host)}:{dest}/")   # trailing '/': dest is the directory
    return argv


def cmd_transfer(args: argparse.Namespace) -> None:
    dest = guard_path(args.dest, args.user)

    sources = []
    for p in args.path:
        if not os.path.exists(p):
            die(f"local path does not exist: {p}")
        sources.append(p.rstrip("/") if os.path.isdir(p) else p)

    argv = rsync_argv(sources, args.user, args.host, dest, args.progress)

    # --print-only: hand the command to the user and touch nothing (DESIGN.md §9.4.0).
    if args.print_only:
        info("Run this yourself to push the files (nothing has been transferred):")
        info("")
        info("  " + " ".join(shlex.quote(a) for a in argv))
        info("")
        info(f"The destination directory {dest} must already exist on the cluster.")
        return

    kind = remote_kind(args.user, args.host, dest)
    if kind == "file":
        die(f"remote destination exists but is a file, not a directory: {dest}")
    need_mkdir = kind == "missing"

    # Never silently overwrite an existing remote file or directory.
    existing = []
    for src in sources:
        remote_item = posixpath.join(dest, os.path.basename(src))
        if remote_kind(args.user, args.host, remote_item) != "missing":
            existing.append(remote_item)

    info("Transfer plan:")
    info(f"  host        : {target(args.user, args.host)}")
    info(f"  destination : {dest}" + ("   (does not exist yet)" if need_mkdir else ""))
    for src in sources:
        info(f"  push        : {src}")
    if need_mkdir:
        info("  will create the destination directory with: mkdir -p")
    if existing:
        info("  already present on the cluster (would be overwritten):")
        for item in existing:
            info(f"      {item}")

    if existing and not args.overwrite:
        die(
            "refusing to overwrite the remote files listed above. Move them aside, choose "
            "another destination, or re-run with --overwrite if replacing them is intended."
        )

    if not args.confirm:
        die_needs_confirm("The files above would be pushed to the cluster.")

    if need_mkdir:
        run_remote(args.user, args.host, ["mkdir", "-p", dest])
    run_local(argv)
    info("")
    info(f"Pushed to {target(args.user, args.host)}:{dest}")


# --------------------------------------------------------------------------- #
# download (DESIGN.md §9.4.6)
# --------------------------------------------------------------------------- #
def remote_uid(user: str, host: str) -> str:
    """Numeric uid of `user` on the cluster; '' if the account is unknown there."""
    return remote_text(user, host, ["id", "-u", user]).strip()


def remote_file_sizes(user: str, host: str, path: str, skip_dirs: tuple) -> list:
    """[(is_foreign, size, path), ...] for every regular file under `path`.

    Ownership is decided by `find -user` ON THE CLUSTER, never by comparing owner
    strings here: `find`'s `%U` is a numeric uid while `%u` is a name — and GNU
    `stat` uses those two letters the other way round. Comparing either against
    --user is how every file in the user's own tree once got flagged as foreign.
    So the remote system resolves the identity and just tags each file:
    'F' = owned by someone else, 'O' = owned by --user.

    Read-only, and WITHOUT -L, so a symlink pointing at another user's data is never
    followed — matching `rsync -a`, which copies it as a symlink.
    """
    argv = ["find", path]
    for name in skip_dirs:
        argv += ["-name", name, "-prune", "-o"]
    argv += [
        "-type", "f", "(",
        "!", "-user", user, "-printf", "F\\t%s\\t%p\\n",
        "-o", "-printf", "O\\t%s\\t%p\\n", ")",
    ]

    out = remote_text(user, host, argv)
    entries = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3 or parts[0] not in ("F", "O"):
            continue                      # ignore anything not tag<TAB>size<TAB>path
        try:
            entries.append((parts[0] == "F", int(parts[1]), parts[2]))
        except ValueError:
            continue
    return entries


def foreign_owned(user: str, host: str, path: str) -> bool:
    """True if `path` itself belongs to someone other than `user`.

    Same `-user` predicate as the scan above — the cluster resolves the identity.
    """
    out = remote_text(user, host, ["find", path, "-maxdepth", "0", "!", "-user", user, "-print"])
    return bool(out.strip())


def full_rsync_hint(user: str, host: str, remote: str, dest: str) -> list:
    """The user's own command for the COMPLETE tree, large files included."""
    return ["rsync", "-avhP", f"{target(user, host)}:{remote}", dest]


def cmd_download(args: argparse.Namespace) -> None:
    # Rule 0: the source must be inside the user's OWN directory. guard_path runs
    # first, so another user's path is refused before anything is even listed.
    remote = guard_path(args.remote, args.user)

    if remote_kind(args.user, args.host, remote) != "dir":
        die(f"remote path is not a directory on the cluster: {remote}")

    # Pre-flight the account: this both validates --user against the cluster and
    # guarantees the `-user` predicate below cannot fail on an unknown name.
    uid = remote_uid(args.user, args.host)
    if not uid:
        die(
            f"the HPC does not recognise the account {args.user!r} (`id -u` returned nothing). "
            "Check the username with the user — nothing was read or transferred."
        )

    # Rule 0, second half: the results must BELONG to the user, not merely sit under a
    # path containing their name. A directory owned by someone else is refused here.
    if foreign_owned(args.user, args.host, remote):
        die(
            f"refusing to download {remote}: it is owned by another user, not {args.user!r} "
            f"(uid {uid}). This skill only downloads the user's own results. Ask the owner for "
            "the data, or give a path under your own directory."
        )

    max_file = parse_size(args.max_file_size) if args.max_file_size \
        else DEFAULT_MAX_FILE_SIZE_BYTES
    skip_dirs = () if args.include_work else DOWNLOAD_SKIP_DIRS

    dest = args.dest or posixpath.basename(remote)
    local_hint = full_rsync_hint(args.user, args.host, remote, dest)

    # 1. scan
    info(f"Scanning {remote} ...")
    entries = remote_file_sizes(args.user, args.host, remote, skip_dirs)
    if not entries:
        die(f"no files found under {remote} (nothing to download).")

    # 2a. any file the cluster tagged as owned by someone else is a hard stop, not
    #     something to filter around: rsync would copy it, and this skill never pulls
    #     another user's data.
    foreign = sorted(((s, p) for is_foreign, s, p in entries if is_foreign), reverse=True)
    if foreign:
        info("")
        info(f"  files owned by another user : {len(foreign)}")
        for size, path in foreign[:10]:
            info(f"      {human_size(size):>8}  {path}")
        if len(foreign) > 10:
            info(f"      ... and {len(foreign) - 10} more")
        die(
            f"refusing to download {remote}: it contains {len(foreign)} file(s) owned by another "
            f"user (see above), and this skill only pulls {args.user}'s own data. Narrow --remote "
            "to a subdirectory that holds only your results."
        )

    # 2b. exclude the big ones
    selected = [(s, p) for _, s, p in entries if s <= max_file]
    excluded = sorted(((s, p) for _, s, p in entries if s > max_file), reverse=True)
    total = sum(s for s, _ in selected)
    excluded_total = sum(s for s, _ in excluded)

    info("")
    info(f"Scan of {remote}")
    info(f"  files found      : {len(entries)}")
    if skip_dirs:
        info(f"  skipped dirs     : {', '.join(skip_dirs)} (Nextflow scratch)")
    if excluded:
        info(f"  excluded >{human_size(max_file)}   : {len(excluded)} files, "
             f"{human_size(excluded_total)}")
        for size, path in excluded[:10]:
            info(f"      {human_size(size):>8}  {path}")
        if len(excluded) > 10:
            info(f"      ... and {len(excluded) - 10} more")
    info(f"  would download   : {len(selected)} files, {human_size(total)} "
         f"(cap {human_size(MAX_DOWNLOAD_BYTES)})")

    # 3a. nothing left after exclusion: say so instead of running an empty rsync
    if not selected:
        smallest = min(s for _, s, _ in entries)
        info("")
        info("To get this data, either:")
        info(f"  * raise the per-file limit : --max-file-size {human_size(smallest)}"
             " (the total cap still applies)")
        info("  * fetch it yourself        : " + " ".join(shlex.quote(a) for a in local_hint))
        die(
            f"every file under {remote} is larger than {human_size(max_file)}, so there is "
            "nothing for this skill to download. Nothing was transferred."
        )

    # 3b. the cap is absolute — refuse rather than truncate the file set
    if total > MAX_DOWNLOAD_BYTES:
        info("")
        info("  largest files still selected:")
        for size, path in sorted(selected, reverse=True)[:10]:
            info(f"      {human_size(size):>8}  {path}")
        info("")
        info("To get this data, either:")
        info(f"  * narrow the download   : --remote {remote}/<subdirectory>")
        info(f"  * exclude more          : --max-file-size 100M")
        info("  * fetch it yourself     : " + " ".join(shlex.quote(a) for a in local_hint))
        die(
            f"refusing to download {human_size(total)} — over the "
            f"{human_size(MAX_DOWNLOAD_BYTES)} limit. Nothing was transferred."
        )

    argv = ["rsync", "-avh"]
    if args.progress:
        argv.append("-P")
    argv.append(f"--max-size={max_file}")
    for name in skip_dirs:
        argv.append(f"--exclude={name}")
    argv += ["-e", "ssh " + " ".join(SSH_OPTS)]
    argv += [f"{target(args.user, args.host)}:{remote}", dest]

    if args.print_only:
        info("")
        info("Run this yourself to download the scanned files (nothing has been transferred):")
        info("  " + " ".join(shlex.quote(a) for a in argv))
        info("")
        info("Or the complete tree, large files included:")
        info("  " + " ".join(shlex.quote(a) for a in local_hint))
        return

    # 4. plan + local destination checks (a download writes to the user's disk)
    info("")
    info("Download plan:")
    info(f"  from    : {target(args.user, args.host)}:{remote}")
    info(f"  into    : {dest}")
    info(f"  size    : {human_size(total)} in {len(selected)} files")
    info("  command : " + " ".join(shlex.quote(a) for a in argv))

    if os.path.exists(dest):
        if not os.path.isdir(dest):
            die(f"local destination exists but is not a directory: {dest}")
        existing = os.listdir(dest)
        if existing and not args.overwrite:
            info(f"  NOTE: {dest} already exists and holds {len(existing)} entries.")
            die(
                f"refusing to write into the non-empty directory {dest}. Choose another "
                "--dest, or re-run with --overwrite if replacing its contents is intended."
            )

    if not args.confirm:
        die_needs_confirm("The files above would be downloaded to this machine.")

    os.makedirs(dest, exist_ok=True)
    run_local(argv)

    # 5. hand back: the full-tree command, then the cleanup suggestion (never run here)
    info("")
    info(f"Downloaded {human_size(total)} into {dest}")
    if excluded:
        info("")
        info(f"{len(excluded)} large files ({human_size(excluded_total)}) were NOT downloaded. "
             "To fetch the complete tree, large files included, run this yourself:")
        info("  " + " ".join(shlex.quote(a) for a in local_hint))
    info("")
    info("Once you have verified the data locally, the run's intermediate files can be removed from "
         "the cluster with `cleanup` — it shows a plan and asks before deleting anything:")
    info(f"  slurm_ops.py cleanup --user {args.user} --host {args.host} --path <run dir>/work")
    info("The work/ and .nextflow/ directories sit in the directory the job was LAUNCHED from, "
         "which is not necessarily this one — take the path from `scontrol show job <jobid>` "
         "(WorkDir), or from job_status. Removing out/ or outs/ is irreversible on the cluster, so "
         "only clean up what you no longer need there.")


# --------------------------------------------------------------------------- #
# submit (DESIGN.md §9.4, §9.4.3)
# --------------------------------------------------------------------------- #
def queued_job_count(user: str, host: str) -> int:
    out = remote_text(user, host, ["squeue", "-u", user, "-h", "-o", "%i"])
    return len([line for line in out.splitlines() if line.strip()])


def script_relative_inputs(text: str) -> list:
    """Relative files the job script needs beside it: -params-file / -c (§4.5)."""
    wanted = []
    for pattern in (r"-params-file\s+(\S+)", r"^\s*-c\s+(\S+)"):
        for m in re.finditer(pattern, text, flags=re.MULTILINE):
            name = m.group(1).strip()
            if name.startswith("$") or name.startswith("/") or name.startswith("#"):
                continue          # a bash variable or an absolute path: not our business
            wanted.append(name)
    return sorted(set(wanted))


def cmd_submit(args: argparse.Namespace) -> None:
    script = guard_path(args.script, args.user)
    rundir = posixpath.dirname(script)
    name = posixpath.basename(script)

    if remote_kind(args.user, args.host, script) != "file":
        die(f"job script not found on the cluster: {script}")

    # The 100-job cap, checked before sbatch (DESIGN.md §9.4.3).
    count = queued_job_count(args.user, args.host)
    info(f"Jobs currently queued for {args.user}: {count} (limit {MAX_JOBS})")
    if count >= MAX_JOBS:
        die(
            f"{args.user} already has {count} jobs on the cluster (limit {MAX_JOBS}). "
            "Nothing was submitted. Wait for jobs to finish, or cancel what is no longer "
            "needed (slurm_ops.py cancel), then submit again."
        )
    if count >= MAX_JOBS * 0.8:
        warn(
            f"the queue is already {count}/{MAX_JOBS} full, and a Nextflow driver job "
            "submits many child jobs of its own as it runs."
        )

    # The script's -params-file / -c are relative paths, so they must sit beside it (§4.5).
    text = remote_text(args.user, args.host, ["cat", script])
    missing = [
        n for n in script_relative_inputs(text)
        if remote_kind(args.user, args.host, posixpath.join(rundir, n)) == "missing"
    ]
    if missing:
        die(
            "the job script references these files by relative path, but they are not in "
            f"{rundir}: " + ", ".join(missing) + ". Transfer them first — the run would "
            "otherwise fail minutes later inside Nextflow."
        )

    info("")
    info("Submit plan:")
    info(f"  host      : {target(args.user, args.host)}")
    info(f"  directory : {rundir}")
    info(f"  script    : {name}")
    info(f"  command   : cd {rundir} && sbatch {name}")
    if not args.confirm:
        die_needs_confirm("The job above would be submitted.")

    # sbatch runs FROM the run directory: the script's -params-file is relative (§4.5).
    res = run_remote(
        args.user, args.host,
        ["sh", "-c", f"cd {shlex.quote(rundir)} && sbatch {shlex.quote(name)}"],
    )
    out = (res.stdout or "").strip()
    info(out)

    m = re.search(r"Submitted batch job (\d+)", out)
    if not m:
        die("could not read a job id from the sbatch output above.")
    jobid = m.group(1)
    info("")
    info(f"Submitted on the HPC in : {rundir}")
    info(f"Job id                  : {jobid}")
    info("")
    info(f"Check it with:  slurm_ops.py job_status --user {args.user} --host {args.host} "
         f"--jobid {jobid}")


# --------------------------------------------------------------------------- #
# job_status (DESIGN.md §9.5)
# --------------------------------------------------------------------------- #
def sacct_field(user: str, host: str, jobid: str, field: str) -> str:
    out = remote_text(
        user, host,
        ["sacct", "-j", jobid, "-X", "-n", "-P", f"--format={field}"],
    )
    for line in out.splitlines():
        if line.strip():
            return line.strip()
    return ""


def scontrol_fields(user: str, host: str, jobid: str) -> dict:
    """Parse `scontrol show job` key=value pairs (live / recently-finished jobs only)."""
    out = remote_text(user, host, ["scontrol", "show", "job", jobid])
    fields = {}
    for token in out.split():
        if "=" in token:
            k, _, v = token.partition("=")
            fields.setdefault(k, v)
    return fields


def normalise_state(raw: str) -> str:
    base = raw.split()[0].split("+")[0].upper() if raw else ""
    return STATE_MAP.get(base, base.lower() or "unknown")


def current_step(log_text: str) -> str:
    """The process Nextflow most recently submitted."""
    steps = re.findall(r"Submitted process > (.+)", log_text)
    if steps:
        return steps[-1].strip()
    steps = re.findall(r"\[[0-9a-f]{2}/[0-9a-f]+\]\s+process > (.+)", log_text)
    return steps[-1].strip() if steps else ""


def cmd_job_status(args: argparse.Namespace) -> None:
    jobid = args.jobid
    fields = scontrol_fields(args.user, args.host, jobid)

    raw_state = fields.get("JobState") or sacct_field(args.user, args.host, jobid, "State")
    if not raw_state:
        die(f"no job {jobid} found for {args.user} (neither scontrol nor sacct knows it).")
    state = normalise_state(raw_state)

    jobname = fields.get("JobName") or sacct_field(args.user, args.host, jobid, "JobName")
    elapsed = fields.get("RunTime") or sacct_field(args.user, args.host, jobid, "Elapsed")

    # Paths reported BY the cluster get the same guard as paths the user types: a job
    # that ran outside the user's own directories is reported, not read (§9.3).
    raw_workdir = fields.get("WorkDir") or sacct_field(args.user, args.host, jobid, "WorkDir")
    workdir = require_user_path(raw_workdir, args.user, "the job's work directory")
    stdout_path = require_user_path(
        fields.get("StdOut", ""), args.user, "the job's SLURM output file"
    )

    info("")
    info(f"Job {jobid} ({jobname or 'unknown name'})")
    info(f"  state    : {state}    [SLURM: {raw_state}]")
    if elapsed:
        info(f"  elapsed  : {elapsed}")
    if workdir:
        info(f"  work dir : {workdir}")
    if stdout_path:
        info(f"  slurm out: {stdout_path}")

    # Read-only: tail the logs, never modify them.
    if stdout_path:
        tail = remote_text(args.user, args.host, ["tail", "-n", str(args.lines), stdout_path])
        if tail.strip():
            info("")
            info(f"--- last {args.lines} lines of {stdout_path} ---")
            info(tail.rstrip())

    nf_log = ""
    if workdir:
        for candidate in (".nextflow.log", "nextflow.log"):
            path = posixpath.join(workdir, candidate)
            if remote_kind(args.user, args.host, path) == "file":
                nf_log = path
                break

    if nf_log:
        text = remote_text(args.user, args.host, ["tail", "-n", "400", nf_log])
        step = current_step(text)
        info("")
        info(f"Nextflow log : {nf_log}")
        info(f"Current step : {step or 'could not determine from the log tail'}")
    elif workdir:
        info("")
        info("Nextflow log : none found in the work directory "
             "(the run may not have started, or was launched elsewhere).")

    if state == "complete":
        info("")
        info("Job is complete. Two ways to get the results — both need your go-ahead:")
        base = posixpath.basename(workdir) if workdir else "results"
        if workdir:
            info(f"  * through this skill (max {human_size(MAX_DOWNLOAD_BYTES)}, large files "
                 "excluded; shows a plan first):")
            info(f"      slurm_ops.py download --user {args.user} --host {args.host} "
                 f"--remote {workdir}")
        info("  * the complete tree, large files included — run this yourself:")
        info(f"      rsync -avhP {target(args.user, args.host)}:{workdir or '<results dir>'} {base}")
        info("  (that directory holds out/, the nextflow report, and the job's own logs)")
        info("Once the data is safely local, `cleanup` can remove the run's work/ from the "
             "cluster — it asks before deleting anything.")
    elif state in ("fail", "node_fail"):
        info("")
        info(f"Job did not succeed ({state}). The SLURM .out and .nextflow.log above are in the "
             "work directory — a failed run never reaches its finalize step, so nothing was "
             "copied to the results directory.")


# --------------------------------------------------------------------------- #
# cancel (DESIGN.md §9.4.4)
# --------------------------------------------------------------------------- #
def cmd_cancel(args: argparse.Namespace) -> None:
    jobid = args.jobid
    if not jobid.isdigit():
        die(f"job id must be a plain number, got {jobid!r}. This command cancels one job only — "
            "never a range, a mass cancel, or a wildcard.")

    fields = scontrol_fields(args.user, args.host, jobid)
    owner = fields.get("UserId", "").split("(")[0] or sacct_field(
        args.user, args.host, jobid, "User"
    )
    if not owner:
        die(f"no job {jobid} found on the cluster — nothing to cancel.")
    # scontrol prints UserId=<name>(<uid>), but falls back to the bare uid when the name
    # cannot be resolved — so accept either form rather than comparing only names.
    if owner != args.user and owner != remote_uid(args.user, args.host):
        die(f"job {jobid} belongs to {owner!r}, not {args.user!r}. Refusing to cancel it.")

    jobname = fields.get("JobName", "") or sacct_field(args.user, args.host, jobid, "JobName")
    workdir = fields.get("WorkDir", "") or sacct_field(args.user, args.host, jobid, "WorkDir")
    state = normalise_state(fields.get("JobState", "") or
                            sacct_field(args.user, args.host, jobid, "State"))

    info("")
    info("Cancel plan:")
    info(f"  job id   : {jobid}")
    info(f"  name     : {jobname or 'unknown'}")
    info(f"  state    : {state}")
    info(f"  work dir : {workdir or 'unknown'}")
    info(f"  command  : scancel {jobid}")
    info("  This ends the job's compute immediately.")
    if not args.confirm:
        die_needs_confirm("The job above would be cancelled.")

    run_remote(args.user, args.host, ["scancel", jobid])
    info("")
    info(f"Cancelled job {jobid}" + (f" ({jobname})" if jobname else "") + ".")

    # Suggest — never perform — cleanup of the half-finished run (DESIGN.md §9.4.4).
    # Only suggest a path that itself passes the guard: the work dir comes from the
    # cluster, so it is checked before being offered as a deletion target.
    if in_user_path(workdir, args.user):
        workpath = posixpath.join(workdir, "work")
        info("")
        info("A cancelled Nextflow run leaves its work directory and .nextflow cache on disk.")
        info("To remove the work directory (asks again before deleting anything):")
        info(f"  slurm_ops.py cleanup --user {args.user} --host {args.host} "
             f"--path {workpath}")
        info("Keep it instead if you intend to resume this run — -resume needs it.")


# --------------------------------------------------------------------------- #
# cleanup (DESIGN.md §9.4.1)
# --------------------------------------------------------------------------- #
def cmd_cleanup(args: argparse.Namespace) -> None:
    path = guard_path(args.path, args.user)

    kind = remote_kind(args.user, args.host, path)
    if kind == "missing":
        die(f"nothing to remove: {path} does not exist on the cluster.")

    allowed, reason = cleanup_kind_allowed(path, kind)
    if not allowed:
        die(
            f"refusing to remove {path}: {reason} (§9.4.1). Only intermediate and bulk-input "
            "artifacts are removable — results directories out/outs, work/.nextflow, "
            "sra/fastq downloads, archives and dataset objects."
        )

    info("")
    info("Cleanup plan:")
    info(f"  host   : {target(args.user, args.host)}")
    info(f"  target : {path}   ({reason})")

    size = remote_text(args.user, args.host, ["du", "-sh", path]).strip()
    if size:
        info(f"  size   : {size.split()[0]}")
    listing = remote_text(args.user, args.host, ["ls", "-lh", path])
    if listing.strip():
        info("  contents:")
        for line in listing.rstrip().splitlines()[:15]:
            info(f"      {line}")
        extra = len(listing.rstrip().splitlines()) - 15
        if extra > 0:
            info(f"      ... and {extra} more entries")

    info(f"  command: rm -rf {path}")
    if posixpath.basename(path) in CLEANUP_RESULT_DIRS:
        info("  NOTE: this is a pipeline RESULTS directory, not scratch. Fetch anything you "
             "still need before removing it.")

    if not args.confirm:
        die_needs_confirm("The target above would be permanently deleted.")

    run_remote(args.user, args.host, ["rm", "-rf", path])
    info("")
    info(f"Removed {path}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def add_common(sub: argparse.ArgumentParser, confirmable: bool = True) -> None:
    # Required, never defaulted: the username and hostname always come from the user.
    sub.add_argument("--user", required=True,
                     help="HPC username (ask the user; never inferred)")
    sub.add_argument("--host", required=True,
                     help="HPC hostname (ask the user; never inferred)")
    if confirmable:
        sub.add_argument("--confirm", action="store_true",
                         help="actually perform the change (without it the plan is printed only)")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="UKDRI SLURM cluster operations: transfer, download, submit, job_status, "
                    "cancel, cleanup.",
        epilog="Passwordless SSH must already be configured by the user; no passwords are used.",
    )
    subs = ap.add_subparsers(dest="cmd", required=True)

    p = subs.add_parser("transfer",
                        help="push job scripts and input data to the HPC (upload; see download "
                             "for the other direction)")
    add_common(p)
    p.add_argument("--path", action="append", required=True,
                   help="local file or directory to push (repeatable)")
    p.add_argument("--dest", required=True, help="remote destination directory (absolute)")
    p.add_argument("--print-only", action="store_true",
                   help="print the rsync command for the user to run; transfer nothing")
    p.add_argument("--progress", action="store_true",
                   help="add -P (--partial --progress) for large or resumed transfers")
    p.add_argument("--overwrite", action="store_true",
                   help="allow replacing files that already exist at the destination")
    p.set_defaults(func=cmd_transfer)

    p = subs.add_parser(
        "download",
        help=f"pull results from the HPC — max {human_size(MAX_DOWNLOAD_BYTES)} total, "
             "big files excluded",
    )
    add_common(p)
    p.add_argument("--remote", required=True,
                   help="remote results directory to download (must be under the user's own "
                        "directory; another user's path is refused)")
    p.add_argument("--dest", help="local destination directory (default: basename of --remote)")
    p.add_argument("--max-file-size", default=None,
                   help=f"exclude files larger than this (default "
                        f"{human_size(DEFAULT_MAX_FILE_SIZE_BYTES)}; e.g. 100M)")
    p.add_argument("--include-work", action="store_true",
                   help="also include the Nextflow work/ and .nextflow/ scratch dirs")
    p.add_argument("--print-only", action="store_true",
                   help="print the rsync command for the user to run; download nothing")
    p.add_argument("--progress", action="store_true",
                   help="add -P (--partial --progress) for large or resumed transfers")
    p.add_argument("--overwrite", action="store_true",
                   help="allow writing into a non-empty local destination")
    p.set_defaults(func=cmd_download)

    p = subs.add_parser("submit", help="submit a job script with sbatch from its own directory")
    add_common(p)
    p.add_argument("--script", required=True,
                   help="absolute path of the job script on the HPC")
    p.set_defaults(func=cmd_submit)

    p = subs.add_parser("job_status", help="report SLURM state and the current pipeline step")
    add_common(p, confirmable=False)
    p.add_argument("--jobid", required=True, help="job id reported by submit")
    p.add_argument("--lines", type=int, default=20,
                   help="lines of the SLURM .out to show (default 20)")
    p.set_defaults(func=cmd_job_status)

    p = subs.add_parser("cancel", help="cancel one job by id with scancel")
    add_common(p)
    p.add_argument("--jobid", required=True, help="the single job id to cancel")
    p.set_defaults(func=cmd_cancel)

    p = subs.add_parser("cleanup", help="remove one allow-listed path on the HPC")
    add_common(p)
    p.add_argument("--path", required=True,
                   help="absolute path to remove (one literal path, no wildcards)")
    p.set_defaults(func=cmd_cleanup)

    args = ap.parse_args()
    if not args.user.strip() or not args.host.strip():
        die("--user and --host must be non-empty; ask the user for both.")
    args.func(args)


if __name__ == "__main__":
    main()
