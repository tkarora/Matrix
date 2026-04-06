---
description: Access and analyze Google Cloud Run logs for debugging Matrix scripts
---

**Trigger:** Use this workflow when you need to debug performance or logical issues with scripts running on Google Cloud Run.

This skill ensures you run the correct `gcloud` commands and ask the right questions to locate the exact logs.

### Step 1: Clarifying Questions
Before running commands, verify you have the necessary context. If missing, ask the user:
1. **Target**: Is this a Cloud Run **Job** (batch script) or a **Service** (web endpoint)?
2. **Name**: What is the name of the Job or Service?
3. **Execution/Revision**: Are we looking for a specific Execution ID (for Jobs) or Revision (for Services)?
4. **Project/Region**: Are we using a non-default GCP Project or Region?

### Step 2: Locate the Resource
Use these commands to find the exact job or execution.

#### For Cloud Run Jobs (Batch Scripts)
List all jobs to find the correct name:
```bash
gcloud run jobs list
```

List executions for a specific job:
```bash
gcloud run jobs executions list --job=JOB_NAME
```

Describe a specific execution to see task status:
```bash
gcloud run jobs executions describe EXECUTION_NAME
```

#### For Cloud Run Services (Web Endpoints)
List all services:
```bash
gcloud run services list
```

### Step 3: Fetch and Analyze Logs
Use `gcloud logging read` for powerful filtering.

#### For Cloud Run Jobs
Read logs for a specific execution (Replace variables):
```bash
gcloud logging read "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"JOB_NAME\" AND labels.\"run.googleapis.com/execution_name\"=\"EXECUTION_NAME\"" --limit 100
```

To filter for failures/errors:
```bash
gcloud logging read "resource.type=\"cloud_run_job\" AND severity>=ERROR AND resource.labels.job_name=\"JOB_NAME\"" --limit 50
```

#### For Cloud Run Services
Read logs for a service:
```bash
gcloud logging read "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"SERVICE_NAME\"" --limit 100
```

### Step 4: Summarize for the User
When presenting log analysis, always provide:
1. **Status Summary**: Number of tasks spawned, succeeded, failed, running.
2. **Failure Analysis**: List of unique errors or crash logs.
3. **Trace/Log Snippets**: Relevant log lines showing the error context.
