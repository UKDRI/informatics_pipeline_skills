#!/bin/bash
#
#SBATCH --job-name=nf-core:scdownstream        # Job name
#SBATCH --partition=htc    # Partition or queue name
#SBATCH --nodes=1                     # Number of nodes
#SBATCH --ntasks-per-node=1           # Number of tasks per node
#SBATCH --cpus-per-task=1             # Number of CPU cores per task
#SBATCH --time=72:00:00                # Maximum runtime (D-HH:MM:SS)
#SBATCH --mail-type=END               # Send email at job completion
set -e
set -o pipefail

# parameters
exec=/nfsdata/bin/nextflow-25.04.7-dist
main=/nfsdata/scripts/nf-core/dev/scdownstream/main.nf

# CHANGE INPUT FOLDER AND CREATE samplesheet
samplesheet=/data/${USER}/PROJECT_NAME/scdownstream/samplesheet_scdownstream.csv
# CHANGE RESULTS FOLDER
resdir=/data/${USER}/PROJECT_NAME/scdownstream/qc_clustering
outdir=$resdir/out

# OPTIONAL custom process-resource config (see DESIGN.md §4.6):
# point this at a config file and uncomment the '-c $conf' line in the run command below.
conf=CONFIG

# export environment variables
# singularity
export NXF_SINGULARITY_CACHEDIR=/nfsdata/apptainer
export NXF_APPTAINER_CACHEDIR=/nfsdata/apptainer


if [ ! -d $resdir ]
then
        mkdir -p $resdir
        echo "Created '$resdir'."
fi

if [ ! -d $outdir ]
then
        mkdir -p $outdir
        echo "Created '$outdir'."
fi

echo "Running nextflow..."
# All non-default pipeline parameters (name, species, celltypist_model,
# clustering_resolutions, automatic_cell_filtering, ...) are set in params_qc_clustering.yml
$exec run $main \
   -entry qc_clustering \
   -profile apptainer,gpu \
   --input $samplesheet \
   --outdir $outdir \
   -params-file params_qc_clustering.yml \
   -with-report $resdir/nextflow_report.html \
   -resume
#  -c $conf \        # OPTIONAL: process-resource overrides (see DESIGN.md §4.6)
echo "Done."

echo "Finalizing..."

# copy files
cp *.sh $resdir/
cp *.out $resdir/
if [ -e $conf ]
then
	cp $conf $resdir/
fi

# cleanup workdir
rm -rf work

echo "Done."

echo "ALL DONE."
