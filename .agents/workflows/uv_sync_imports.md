---
description: Automatically sync uv dependencies on Python file save
---

**Trigger:** Execute this workflow automatically whenever a Python file is saved or modified.

Whenever Python imports are changed (added or removed), follow these steps to keep the `pyproject.toml` and lockfile in sync. 

1. **Analyze Changes**: Check the saved Python file for any added or removed import statements.
2. **Resolve Packages**: 
   - For *added* imports, securely resolve the correct PyPI package name (e.g., `google.cloud.storage` -> `google-cloud-storage`). Do not assume exact matches.
   - For *removed* imports, identify the underlying PyPI package name that is being removed, and verify it isn't required elsewhere in the project.
3. **Sync Dependencies**: Add or remove the resolved package name to update `pyproject.toml` and automatically sync the `uv.lock`.

// turbo-all
```bash
uv add <resolved_added_package>
uv remove <resolved_removed_package>
```
