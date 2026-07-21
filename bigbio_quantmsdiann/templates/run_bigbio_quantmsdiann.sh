#!/bin/bash
#
#SBATCH --job-name=bigbio:quantmsdiann   # Job name
#SBATCH --partition=htc    # Partition or queue name
#SBATCH --nodes=1                     # Number of nodes
#SBATCH --ntasks-per-node=1           # Number of tasks per node
#SBATCH --cpus-per-task=1             # Number of CPU cores per task
#SBATCH --time=72:00:00                # Maximum runtime (D-HH:MM:SS)
set -e
set -o pipefail

# parameters
exec=/nfsdata/bin/nextflow-25.04.7-dist
main=/nfsdata/scripts/bigbio/quantmsdiann_2.2.0/main.nf   # confirm path on cluster

# CREATE AND CHANGE PATH TO SDRF SAMPLE SHEET (must end with .sdrf.tsv)
sdrf=/nfsdata/${USER}/PATH_TO_SAMPLE_SHEET
# CHANGE RESULTS_DIR on your folder on /data
resdir=/data/${USER}/RESULTS_DIR
outdir=$resdir/out

# OPTIONAL custom process-resource config (see DESIGN.md §4.6):
# point this at a config file and uncomment the '-c $conf' line in the run command below.
conf=CONFIG

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

# export environment variables
# singularity
export NXF_SINGULARITY_CACHEDIR=/nfsdata/apptainer
export NXF_APPTAINER_CACHEDIR=/nfsdata/apptainer

echo "Running nextflow..."
# All non-default pipeline parameters (database, ...) are set in params.yml
$exec run $main \
   -profile apptainer \
   --input $sdrf \
   --outdir $outdir \
   -params-file params.yml \
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
