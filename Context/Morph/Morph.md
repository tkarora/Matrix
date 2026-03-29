# Morph Hub Overview

Morph is a sophisticated benchmarking harness designed for evaluating autonomous Machine Learning (ML) AI agents on structured data science tasks. It acts as an orchestrator and referee, pitting AI agents against Kaggle-style competitions or custom ML problems to measure their end-to-end data science capabilities.

## What is an ML AI Agent?

Unlike traditional conversational AI models, an ML AI agent operates autonomously in a loop. When assigned a task by Morph, the agent:
1. Receives a prompt describing the problem, a target metric (e.g., RMSE), and a dataset location.
2. Explores the dataset autonomously, analyzing columns, handling missing values, and engineering features.
3. Writes, executes, and iteratively debugs its own Python machine learning code (e.g., training Random Forests or Neural Networks).
4. Generates predictions for a test dataset and outputs a `submission.csv` file without human intervention.

## The Morph Architecture

The Morph lifecycle revolves around several key components:

### 1. Agents (`agents/`)
Morph defines the benchmarking contestants in `agents/agents.yaml`. These repositories (e.g., `morph_mle_star` or `morph_autoresearch`) are cloned and installed locally. The system invokes them using unified commands (like `adk run`) and passes in the environment configuration as a JSON payload.

### 2. Tasks (`testing/tasks/`)
Each machine learning problem is defined as a separate directory under `testing/tasks/`. A typical task structure includes:
- **`description.md`**: The prompt containing the instructions, target variable, and the required format of the final submission.
- **`config.yaml`**: The grading and metric configuration for the task.
- **Training and Test Data**: The actual data splits or queries needed for model development. 
- **Hidden Answer Key**: Kept entirely separate from the task folder so the agent cannot cheat during evaluation.

### 3. Orchestration Scripts (`scripts/`)
- **`install_testing_env.sh`**: Prepares the workspace, downloads competition datasets, and installs the agent code.
- **`execute_runs.sh` / `execute_runs.py`**: A parallel runner that launches agents against defined tasks (from `scripts/run/runs.yaml`), tracks their logs, monitors execution time, and routes output.
- **`evaluate_submissions.sh`**: Grades the resulting `submission.csv` files using `mlebench grade` and compiles a summary leaderboard.

## Applying Morph to the Matrix Model

Morph contains a stub for testing agents on the Matrix model under `Morph/testing/tasks/forest-matrix`. Developing an agentic benchmark for this task requires configuring the test suite:

1. **Defining the Ground Truth**: Establishing a hidden evaluation split (an answer key) containing tree growth transitions or demography data that the agent cannot see during training.
2. **Formulating the Prompt**: Fleshing out the `description.md` so the agent understands how to pull the training data (e.g., from `cameltrain.Forest_MATRIX.grid_3km` in BigQuery) and what exactly it needs to predict.
3. **Choosing the Agent's Objective**: Determining whether the agent is expected to reimplement the existing baseline R code (`MATRIX_training_public.R`) in Python, tune its hyperparameters, or build an entirely novel machine learning model for forest demography from scratch.
