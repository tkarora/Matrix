# Matrix Workspace

This workspace contains code and scripts for interacting with the `cameltrain` Google Cloud project. 

## Prerequisites & Setup

To run Python scripts in this workspace and authenticate with Google Cloud, follow these steps:

### 1. Set Up Environment and Dependencies

This project relies on `uv` for fast dependency management. A `pyproject.toml` and lockfile are already provided.

To create the virtual environment and install all required libraries (including `pyopenssl` to resolve a known BigQuery dependency issue):

```bash
cd ~/Matrix
uv sync
source .venv/bin/activate
```

### 2. Install Local R Dependencies (For Local Evaluation Only)

If you plan to execute the Matrix modeling scripts or evaluation pipelines locally on your machine (e.g., using `make eval-local-test` inside `/Evaluate`), you must install the native R interpreter and its corresponding forecasting packages:

*(Note: If you only trigger the Google Cloud Run array workflow, you can gracefully skip this step as the foundational `r-base` Docker image handles this identically).*

```bash
sudo apt-get update
sudo apt-get install -y r-base
R -e "install.packages(c('randomForest', 'stringr'), repos='http://cran.rstudio.com/')"
```

### 3. Google Cloud Authentication

First, natively authorize your core Google SDK identity (crucial for local docker and gcloud command line operations):

```bash
gcloud auth login
```

Then, ensure your active `gcloud` configuration points to the correct project:

```bash
gcloud config set project cameltrain
```

Next, generate Application Default Credentials (ADC) so that the Python libraries can authenticate on your behalf:

```bash
gcloud auth application-default login
```

If you plan to build and push Docker containers to Google Artifact Registry (`gcr.io`), you must additionally configure your local Docker daemon to authenticate with Google Cloud identities:

```bash
gcloud auth configure-docker gcr.io --quiet
```

> [!IMPORTANT]
> **Do NOT use Service Account Impersonation for Local Docker Pushes**
> 
> When executing `make docker-push` locally, strictly rely on your physical identity authorized by `gcloud auth login` (which organically posesses Artifact Registry Writer permissions). 
> 
> Never attempt to forcibly route your deployments through a service account (e.g., using `gcloud config set auth/impersonate_service_account`). Doing so natively triggers absolute `PERMISSION_DENIED` errors at the Docker Credential Helper layer because developers inherently lack explicit token creator keys for deploying. Google Cloud natively assigns your container the correct Service Account context dynamically at *runtime* within the actual Cloud Run framework orchestration!

A `.env` file is already provided in the root directory specifying the target GCP project.

> [!WARNING]
> **Preventing MutualTLSChannelError (Exit Code -11)**
> 
> Due to Google Auth library mechanics occasionally interacting aggressively with corporate proxy networks or automated certificate providers, you must explicitly disable the client certificate pipeline to ensure BigQuery and other backend GCP clients do not segfault during initialization. 
> 
> You can permanently configure your shell to bypass this across all scripts in this workspace by running the following commands once:
> ```bash
> echo 'export GOOGLE_API_USE_CLIENT_CERTIFICATE=false' >> ~/.bashrc
> echo 'export GOOGLE_API_USE_MTLS_ENDPOINT=never' >> ~/.bashrc
> source ~/.bashrc
> ```

### 4. Verify Setup

You can verify that your authentication and setup is working by running the provided test script:

```bash
uv run test_gcp.py
```

If the authentication is successful, the script will list the first few storage buckets in your `cameltrain` GCP project.
