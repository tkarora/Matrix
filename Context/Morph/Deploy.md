# Morph Deployment & Execution Guide

This document details the commands and workflows required to configure, deploy, and execute a Morph benchmarking run both on your local filesystem and on Google Cloud (using the `cameltrain` project).

## Prerequisites & Configuration Layer

Regardless of whether you run Morph locally or in the cloud, you must first define your tasks and agents:

1. **Configure Contestants**: Ensure your agents are defined in `agents/agents.yaml`. Note their git endpoints and build commands.
2. **Select Tasks**: Open `scripts/run/runs.yaml` and list the `competition_id`s (like `forest-matrix`) that the agents should be evaluated against.
3. **Environment Setup**: Pull down competition data and clone the agents locally.
   ```bash
   cd Morph
   ./scripts/install/install_testing_env.sh
   ```

---

## 💻 1. Local Execution

If you are developing an agent or testing a small batch of covariates, generating runs locally is the fastest approach.

### Start the Run
You can launch execution via the Bash wrapper or the native Python orchestrator:
```bash
# Option A: Run using the shell wrapper (daemonizes to the background by default)
./scripts/run/execute_runs.sh

# Option B: Run in the foreground using the CLI, limiting each agent to 2 parallel tasks
poetry run python morph.py run --jobs 2
```

### Tail the Logs
Morph dumps progress to the `results/` folder dynamically.
```bash
tail -f results/<agent_name>-<task_name>_<timestamp>/progress.log
```

### Grade Submissions
Once the tasks complete (they deposit `submission.csv` files), evaluate them against the hidden answer keys locally:
```bash
poetry run python morph.py evaluate
# OR
./scripts/evaluate/evaluate_submissions.sh
```

---

## ☁️ 2. Google Cloud Execution (`cameltrain` Project)

When deploying at scale, Morph leverages Google Cloud Storage (GCS) to hold the datasets, Cloud Run to host the persistent benchmarking hub/web UI, and Vertex AI to parallelize the agent sandboxes.

### Step 1: Push Data to GCS
Because Cloud Run and Vertex AI execute remotely, they need access to your local `testing/tasks/` configurations and `testing/eval_data/` answer keys. You must push your latest local state to a GCS bucket. 
Ensure your `scripts/run/config.yaml` sets your `gcs_bucket` to `morph-test-state-cameltrain`, then run:
```bash
poetry run python scripts/data/sync_gcs.py --mode push
```

### Step 2: Distributed Vertex Engine Execution
Instead of tying up your local machine constraints, you can instruct your local CLI to outsource the benchmarking jobs to Google Vertex AI. The Vertex cluster will pull the test payload directly from the `cameltrain` bucket.
```bash
# Deploys agent sandboxes across serverless Vertex resources
poetry run python morph.py run --vertex
```
And to evaluate thousands of `submission.csv` files natively on Vertex AI:
```bash
poetry run python morph.py evaluate --vertex
```

### Step 3: Deploy the Persistent Morph Hub (Cloud Run)
If you wish to mount the benchmarking web console and orchestrator persistently on the web, Morph includes a turnkey deployment script bound to Artifact Registry and Cloud Run.

```bash
cd Morph
gcloud config set project cameltrain
./deploy/deploy_cloud_run.sh
```
*Note: The script will prompt you for variables. Use `cameltrain` as the project, `us-central1` as the region, and `morph-test-state-cameltrain` as the persistent GCS bucket.* 

This deployment command accomplishes three things automatically:
1. Activates required APIs (`run`, `cloudbuild`, `storage-component`) on `cameltrain`.
2. Packages Morph into a Docker container and registers it.
3. Mounts the `morph-test-state-cameltrain` bucket directly inside a Cloud Run Gen 2 container as a filesystem volume so the web hub can stream logs natively.
