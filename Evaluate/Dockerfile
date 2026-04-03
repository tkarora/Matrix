# Base OS with R pre-installed
FROM r-base:4.4.1

# Unbuffer Python stdout/stderr to ensure logs flush instantly in Cloud Run
ENV PYTHONUNBUFFERED=1

# Install required system packages
RUN apt-get update && apt-get install -y \
    curl \
    python3 \
    python3-venv \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install UV for fast python package management
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="/usr/local/bin" sh

# Install required R packages (randomForest)
RUN R -e "install.packages(c('randomForest', 'stringr'), repos='http://cran.rstudio.com/')"

WORKDIR /app

# We expect the full Matrix repository tree to be mounted here so that paths
# like ../Context/forestmatrixmodel/MATRIX_simulation_0925.R resolve properly
COPY . /app

# Install Python dependencies canonically via the locked uv environment to prevent system conflicts
RUN uv sync --package evaluate

# Make script executable
RUN chmod +x /app/Evaluate/evaluate_model.py

# Entrypoint configuration
WORKDIR /app/Evaluate
ENTRYPOINT ["/app/.venv/bin/python3", "evaluate_model.py"]
