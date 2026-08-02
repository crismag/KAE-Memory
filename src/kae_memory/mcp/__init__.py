"""KAE MCP — the sanctioned agent data path (ADR-0018).

An adapter over the application layer, never over the database. Every tool
calls an application service, so every write passes the domain invariants that
ADR-0004 says the schema cannot reconstruct.

The dependency direction is one way:

    MCP adapter -> application services -> domain -> persistence

Nothing here imports ``kae_memory.persistence`` or constructs SQL.
"""
