"""The module graph, over HTTP (N17, N18) — read only.

`D-19`. Everything here was finished and reachable only from MCP:
`ModuleService` computes the graph, the neighbourhood in both directions, and a
build order with a stable tie-break, and refuses cycles and double ownership at
write time. `kae_get_module_graph` exposed it to agents.

So a coding agent connected over MCP could read a project's architecture and the
person who owns the project could not, which is the wrong way round — and it is
why Studio's `/dependencies` is empty on every deployment.

**Reads only.** Defining a module and drawing an edge stay on MCP until somebody
rules who may draw an architecture. Three GETs create nothing, decide nothing,
and delete nothing, which is what makes adding them safe without that ruling.
"""

from fastapi import APIRouter

from kae_memory.application.module_service import ModuleNotFoundError
from kae_memory.domain.identifiers import ProjectId

from ..dependencies import Memory, Modules
from ..errors import not_found
from ..schemas import (
    ModuleEdgeResponse,
    ModuleGraphResponse,
    ModuleNeighbourhoodResponse,
    ModuleResponse,
)

router = APIRouter(prefix="/v1/projects/{project_id}", tags=["modules"])


def _project(project_id: str, memory: Memory) -> ProjectId:
    project = memory.get_project(ProjectId(project_id))
    if project is None:
        raise not_found("project", project_id)
    return project.id


@router.get("/modules", response_model=list[ModuleResponse])
def list_modules(project_id: str, memory: Memory, modules: Modules) -> list[ModuleResponse]:
    """Every module in this project, ordered by key.

    An empty list means the project has no modules — a real answer, and the one
    a caller needs to tell apart from *"modules cannot be read here"*, which is
    what the absence of this route used to produce.
    """

    resolved = _project(project_id, memory)
    return [ModuleResponse.of(module) for module in modules.list_modules(resolved)]


@router.get("/modules/graph", response_model=ModuleGraphResponse)
def module_graph(project_id: str, memory: Memory, modules: Modules) -> ModuleGraphResponse:
    """Every module, every edge, and the order they can be built in.

    Edges are returned in module **keys** rather than identifiers. The graph is
    for drawing and reading; a caller handed internal ids would have to resolve
    them first, and every caller would resolve them identically.
    """

    resolved = _project(project_id, memory)
    known = {module.id: module for module in modules.list_modules(resolved)}
    graph = modules.graph(resolved)

    edges: list[ModuleEdgeResponse] = []
    for edge in graph.edges:
        source = known.get(edge.source)
        if source is None:
            # An edge whose source is not in the project's module list. It
            # cannot be drawn and it must not be invented a name for, so it is
            # dropped rather than rendered under a placeholder key.
            continue
        target = known.get(edge.target_module) if edge.target_module else None
        edges.append(
            ModuleEdgeResponse(
                source=source.key,
                relation=edge.relation.value,
                target_module=target.key if target else None,
                target_knowledge=edge.target_knowledge,
            )
        )

    return ModuleGraphResponse(
        project_id=str(resolved),
        modules=[ModuleResponse.of(module) for module in known.values()],
        edges=edges,
        build_order=[module.key for module in modules.build_order(resolved)],
    )


@router.get("/modules/{key}", response_model=ModuleNeighbourhoodResponse)
def module_neighbourhood(
    project_id: str, key: str, memory: Memory, modules: Modules
) -> ModuleNeighbourhoodResponse:
    """One module and everything it touches, in both directions.

    The *"dig deeper for module-level information"* half. Dependencies and
    dependents arrive together because they answer opposite questions a reader
    needs at the same moment: what must exist before I build this, and what
    breaks if I change it.
    """

    resolved = _project(project_id, memory)
    try:
        neighbourhood = modules.neighbourhood(resolved, key)
    except ModuleNotFoundError as error:
        raise not_found("module", key) from error
    return ModuleNeighbourhoodResponse.of(neighbourhood)
