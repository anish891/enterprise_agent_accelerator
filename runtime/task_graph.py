from typing import Any, Dict, List, Set
from utils.logger import get_logger

logger = get_logger("runtime.task_graph")

def resolve_execution_batches(tasks_config: Dict[str, Dict[str, Any]]) -> List[List[str]]:
    """
    Resolves dependency ordering of tasks configured in tasks.yaml.
    Organizes tasks into sequential layers (batches) of execution. Tasks within
    the same layer have their dependencies satisfied and can be run concurrently.
    
    Raises:
        ValueError: If a task depends on an undefined task or a dependency loop/cycle exists.
    """
    dependency_map: Dict[str, Set[str]] = {}
    
    # Build adjacency mapping
    for name, info in tasks_config.items():
        deps = info.get("depends_on") or []
        if isinstance(deps, str):
            deps = [deps]
        dependency_map[name] = set(deps)

    # Validate that all references exist
    for name, deps in dependency_map.items():
        for dep in deps:
            if dep not in dependency_map:
                msg = f"Task '{name}' has dependency on undefined task '{dep}'"
                logger.error(msg)
                raise ValueError(msg)

    batches: List[List[str]] = []
    visited: Set[str] = set()

    while len(visited) < len(dependency_map):
        current_layer = []
        for name, deps in dependency_map.items():
            if name in visited:
                continue
            # Check if all prerequisite tasks have been completed
            if deps.issubset(visited):
                current_layer.append(name)

        # Loop check
        if not current_layer:
            unresolved = set(dependency_map.keys()) - visited
            msg = f"Circular dependency cycle detected within tasks: {unresolved}"
            logger.error(msg)
            raise ValueError(msg)

        batches.append(current_layer)
        visited.update(current_layer)

    logger.info(f"Topological sorting succeeded. Compiled execution into {len(batches)} layer batches.")
    return batches
