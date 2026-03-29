# Understand Workflow

**Objective**: When you instruct the AI agent to "Run the Understand workflow on [Directory/Codebase]", the assistant should systematically ingest and construct a deep contextual understanding of the target system before executing any changes.

## Phase 1: Ingestion & Survey
1. **Entry Point Identification**: Use file listing commands to seek out the natural entry points of the repository (`main.py`, `package.json`, `index.js`, `README.md`, orchestrator CLI scripts).
2. **Dependency Analysis**: Review package managers (`pyproject.toml`, `requirements.txt`, `go.mod`) to understand the technology stack and architectural constraints.
3. **Directory Mapping**: Construct a high-level file tree. Group directories into logical layers (e.g., Domain/Business logic versus Infrastructure/Scripts versus UI/Frontend).

## Phase 2: Architecture Mapping
1. **Semantic Search**: Use keyword search (`grep_search` or Semantic tools) to locate the core logical routines within the service. 
2. **Trace the Happy Path**: Mentally dry-run the execution flow from user input to destination output. For instance, trace the path of an API request from the controller, through the service layer, to the database read, and back.
3. **Internal Documentation Review**: Read module-level docstrings, architecture diagrams, and any internal `.md` guidelines within the `docs/` or `Context/` folders.

## Phase 3: Component Deep-Dive
1. **Abstraction Detection**: Identify the common patterns spanning the codebase (e.g., Factory patterns, Dependency Injection, pub/sub queues, retry loops).
2. **Agentic File Reading**: Actively read (`view_file`) 3-5 core logic files. Skim to build a semantic map of where functions live without memorizing exact syntax.

## Phase 4: Output Synthesis
Synthesize the findings into an Artifact or direct response for the user. Produce:
- A clear summary of the system's purpose.
- A functional breakdown of its directory structure.
- Details regarding any idiosyncrasies, custom build pipelines, or hidden orchestrators that a new contributor would need to know prior to editing the codebase.
