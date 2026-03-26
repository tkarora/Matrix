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
```


### 3. Google Cloud Authentication

First, ensure your active `gcloud` configuration points to the correct project:

```bash
gcloud config set project cameltrain
```

Next, generate Application Default Credentials (ADC) so that the Python libraries can authenticate on your behalf:

```bash
gcloud auth application-default login
```

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
