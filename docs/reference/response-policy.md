# Response policy

How much detail an MCP response carries, and why that is configurable at all.

An agent's context window is finite and shared. A tool that always returns
everything spends budget the agent needed for reasoning; one that always returns
a summary forces a second call. The policy makes that a deployment choice rather
than a fixed guess.

Source: `src/kae_memory/mcp/response_policy.py`.

---

## The three dimensions

**Detail** — how much structure comes back.

| `KAE_MCP_DETAIL` | |
|---|---|
| `summary` | Enough to decide what to ask next. The default |
| `standard` | The usual working level |
| `diagnostic` | Everything, including what is normally elided. For debugging, not routine use |

**Prose** — how much explanatory text accompanies it.

| `KAE_MCP_PROSE` | |
|---|---|
| `none` | Structure only |
| `minimal` | |
| `concise` | The default |
| `standard` | Full explanation |

`none` is worth knowing about: an agent that is going to reformat the answer
anyway does not need it written out first, and the tokens are better spent
elsewhere.

**Profile** — a named combination.

| `KAE_MCP_PROFILE` | |
|---|---|
| `economy` | Least budget |
| `regular` | The default |
| `detailed` | |
| `custom` | Dimensions set individually |

---

## Bounds

| Setting | Default | Meaning |
|---|---|---|
| `max_output_tokens` | 2,500 | Ceiling on a response |
| `max_entities` | 25 | Ceiling on returned items |
| `max_text_length` | unset | Per-field truncation |

A bound is not an error. A truncated response says it was truncated; it does not
pretend the remainder does not exist.

## Responses say what produced them

A response carries its resolved policy — profile, detail, prose, and the bounds
in force.

That is deliberate, and the reason is narrow: **a `custom` profile is
irreproducible unless the response says what it was.** Two calls returning
different amounts, with nothing to distinguish them, is a debugging problem
nobody can solve from the outside. Stating the policy costs a few tokens and
removes a class of confusion entirely.

## Configuring it

```bash
KAE_MCP_PROFILE=economy          # or set the dimensions individually
KAE_MCP_DETAIL=summary
KAE_MCP_PROSE=none
KAE_MCP_MAX_TOKENS=2500
KAE_MCP_MAX_ENTITIES=25
```

Setting a dimension directly implies `custom`. An invalid combination raises
`InvalidPolicyError` at startup rather than silently falling back — a policy
quietly replaced by a default is one nobody notices is not in force.

## HTTP does not have this

Response shaping is an MCP concern. HTTP responses are their recorded contract
([`specifications/openapi.json`](../../specifications/openapi.json)), and a
route that returned different shapes by configuration would not have a contract.

The asymmetry is deliberate: an agent pays for tokens, a product client pays for
round trips, and the two want opposite things.

## Related

- [MCP tools](mcp-tools.md) · [Configuration](configuration.md)
- [Capability matrix](capability-matrix.md)
