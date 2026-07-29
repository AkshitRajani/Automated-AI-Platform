"""
Component inference — layered, no hardcoding.

Layer 1: (future) manifest-provided component mappings
Layer 2: Auto-derive from 2nd-level directory in entity file paths
Layer 3: Single default component if nothing else works
"""
import logging
from collections import defaultdict
from dataclasses import dataclass

from ingestion.parsers.quad_parser import Entity

logger = logging.getLogger(__name__)


@dataclass
class Component:
    component_id: str
    app_id: str
    name: str
    path_prefix: str
    languages: list[str]
    entity_count: int


def infer_components(app_id: str, entities: list[Entity]) -> list[Component]:
    """
    Infer components from entity file paths.
    Groups entities by the second path segment (the deployment unit).
    No regex. No app-specific logic. Just split on '/'.
    """
    path_groups: dict[str, list[Entity]] = defaultdict(list)
    unassigned: list[Entity] = []

    for entity in entities:
        fp = entity.source.file_path if entity.source else ""
        parts = fp.split("/")

        if len(parts) >= 2:
            group_key = parts[1]
            path_groups[group_key].append(entity)
        else:
            unassigned.append(entity)

    # Build component list from groups
    components = []
    for group_key, members in sorted(path_groups.items()):
        languages = sorted(set(e.language for e in members if e.language))
        prefix = f"{members[0].source.file_path.split('/')[0]}/{group_key}" if members[0].source else group_key

        components.append(Component(
            component_id=f"{app_id}:{group_key}",
            app_id=app_id,
            name=group_key,
            path_prefix=prefix,
            languages=languages,
            entity_count=len(members),
        ))

    # Handle bare files (no '/' in path)
    if unassigned:
        languages = sorted(set(e.language for e in unassigned if e.language))
        components.append(Component(
            component_id=f"{app_id}:_unassigned",
            app_id=app_id,
            name="_unassigned",
            path_prefix="",
            languages=languages,
            entity_count=len(unassigned),
        ))

    # Fallback: if no components were created, use a single default
    if not components:
        components.append(Component(
            component_id=f"{app_id}:default",
            app_id=app_id,
            name=app_id,
            path_prefix="",
            languages=[],
            entity_count=len(entities),
        ))

    return components


def assign_component(entity: Entity, components: list[Component]) -> str:
    """
    Assign an entity to a component based on its file path.
    Returns the component_id. First match wins.
    """
    if not entity.source or not entity.source.file_path:
        # Assign to _unassigned or default
        for c in components:
            if c.name in ("_unassigned", c.app_id):
                return c.component_id
        return components[-1].component_id

    fp = entity.source.file_path
    for comp in components:
        if comp.path_prefix and fp.startswith(comp.path_prefix):
            return comp.component_id

    # If no prefix matches, use the path-based grouping
    parts = fp.split("/")
    if len(parts) >= 2:
        group_key = parts[1]
        for comp in components:
            if comp.name == group_key:
                return comp.component_id

    return components[-1].component_id
