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

# parameters (exec= and main= are filled by build_job.py from <repo-root>/assets/cluster.json)
exec=NEXTFLOW_EXEC
main=PIPELINE_MAIN_NF

# CHANGE INPUT_H5AD ANNDATA FILE: the annotated reference to train on (passed as --train_adata).
# Its raw counts are read from train_counts_layer (X by default; set `counts` in
# params_train_models.yml for an scdownstream output), its labels from train_label_col.
h5adf=/data/${USER}/PROJECT_NAME/scdownstream/reference/REFERENCE.h5ad
# CHANGE RESULTS_FOLDER
resdir=/data/${USER}/PROJECT_NAME/scdownstream/train_models
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
# All non-default pipeline parameters (train_label_col, train_name, train_*, ...) are set in
# params_train_models.yml. scVI / scANVI training uses the GPU.
$exec run $main \
   --stage train_models \
   -profile apptainer,gpu \
   --train_adata $h5adf \
   --outdir $outdir \
   -params-file params_train_models.yml \
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
