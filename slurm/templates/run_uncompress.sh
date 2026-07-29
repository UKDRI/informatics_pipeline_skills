#!/bin/bash
#
#SBATCH --job-name=uncompress          # Job name
#SBATCH --partition=htc    # Partition or queue name
#SBATCH --nodes=1                     # Number of nodes
#SBATCH --ntasks-per-node=1           # Number of tasks per node
#SBATCH --cpus-per-task=1             # Number of CPU cores per task
#SBATCH --time=12:00:00                # Maximum runtime (D-HH:MM:SS)
set -e
set -o pipefail

# CHANGE PATH_TO_ARCHIVE to the .zip / .tar.gz to unpack (full path)
archive=/data/${USER}/PATH_TO_ARCHIVE
# CHANGE DEST_DIR to the directory the contents should land in
destdir=/data/${USER}/DEST_DIR

if [ ! -e "$archive" ]
then
        echo "Archive not found: '$archive'." >&2
        exit 1
fi

if [ ! -d $destdir ]
then
        mkdir -p $destdir
        echo "Created '$destdir'."
fi

# list the archive contents first (read-only), so the job log records what was unpacked
echo "Listing '$archive'..."
case "$archive" in
    *.zip)
        unzip -l "$archive"
        ;;
    *.tar.gz|*.tgz)
        tar -tzf "$archive"
        ;;
    *)
        echo "Unsupported archive type: '$archive' (expected .zip, .tar.gz or .tgz)." >&2
        exit 1
        ;;
esac

echo "Unpacking into '$destdir'..."
# -n / -k keep existing files: an already-unpacked file is never overwritten.
# Only switch to an overwriting form (unzip -o / tar without -k) on explicit request.
case "$archive" in
    *.zip)
        unzip -n "$archive" -d "$destdir"
        ;;
    *.tar.gz|*.tgz)
        tar -xzkf "$archive" -C "$destdir"
        ;;
esac
echo "Done."

echo "Unpacked contents of '$destdir':"
ls -lh "$destdir"

# The archive itself is deliberately NOT deleted here. Once the unpacked data is
# verified, remove it explicitly with:
#   python3 scripts/slurm_ops.py cleanup --user <user> --host <host> --path "$archive"

echo "ALL DONE."
