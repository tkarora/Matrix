---
description: Read and understand new resources in Context directories
---
# Context Preparation Workflow

This workflow ensures that you read and understand all resources within any directory named `Context` before beginning to solve problems.

Follow these specific steps when you need to prepare the Context directory or when new files are added:

1. Locate the Context directory in the workspace (e.g., `/home/tkarora/Matrix/Context`).
2. Run `find_by_name` targeting the `Context` directory to recursively list all the resources, including files in its subdirectories.
3. Use the `view_file` tool to read the contents of all important code scripts (.R, .py, .js, etc.), documentation files (.md, .txt), and configuration files.
4. If there are PDF files, read them using `pdftotext -` via the `run_command` tool (e.g., `pdftotext Context/file.pdf -`). 
5. Review the extracted logic and documentation to fully understand the architectural patterns, workflows, and goals of the resources.
6. Summarize your findings internally and notify the user that you have finished reading the context, ready to apply the newly acquired knowledge.
