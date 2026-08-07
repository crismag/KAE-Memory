# Documentation gaps and contradictions

Found while mapping current implementation to the proposed documentation.
Separated by what they cost: a **blocker** stops a page being written honestly; a
**gap** is ordinary writing work.

---

## Blockers to Phase 2B

Four. Each stops one page, not the phase.

### B1 — No token configuration procedure

ADR-0024 requires the process to refuse to start off-loopback without tokens.
Nothing in this repository documents the format, where the value goes, or how
to generate one. `docs/operations/deployment.md` cannot be completed: it would
either omit the step that makes a deployment start, or invent one.

**Format, observed on the deployed instance:** `name:token` pairs, optionally
`name:token:project,project`. **Not verified against the parser in Phase 2A**,
and worth verifying carefully — a malformed value parses to zero tokens and
`required = bool(tokens)` then makes authentication optional. The failure is
silent and fails *open*.

**Resolution:** read `api/security.py`, document the format, and test the
negative case. Phase 2C at the latest.

### B2 — CockroachDB status cannot be stated as-is

ADR-0022 makes providers selectable; parity was demonstrated at revision `0009`
on 2026-08-04; the head is `0021`. "Supports CockroachDB" would be a claim
twelve revisions past its evidence.

**Resolution:** `docs/architecture/persistence-and-providers.md` says *selectable
provider, parity demonstrated at `0009`, not re-verified since* — and links
VG-4. That is publishable. Anything stronger needs the 7.5-hour suite, which
VG-4 makes a release decision.

### B3 — Modules are MCP-only and the reason is unresolved

`kae_define_module`, `kae_relate_modules`, `kae_get_module_graph` exist on MCP
and not on HTTP, declared `agent_only`. The recorded reason (N12) is that
Studio's curation flow is a different contract, still unreconciled.

Writing `docs/concepts/modules-and-dependencies.md` for the integrator audience
means explaining a boundary whose justification is an open question.

**Resolution:** state the current shape and that Studio curation is unreconciled.
Do not imply HTTP support is coming, and do not imply it was an oversight.

### B4 — Cross-session continuity is the headline claim and is untested as such

The demonstration the product turns on — a second session knowing what the first
established — has no end-to-end test. The parts are tested; the claim is not.

**Resolution:** Phase 2C exercises it and records the transcript.
`docs/examples/cross-session-continuity.md` waits for that. **E4 until then.**

---

## Contradictions

### C1 — `README.md` still reads as a development document

A milestone table (M0–M11), a code inventory, a file-layout table. It survived
Phase 1 because it was not under `docs/`. It contradicts the boundary the
migration established.

**Not a blocker** — Phase 2B rewrites it as an entry point.

### C2 — ADR-0017 names `deploy/aws/ec2/`

The last surviving reference to assets removed in `05fb320`. **Left deliberately:**
ADR-0017 records a topology decision as it was taken, and editing it would make
the record disagree with what was decided. Historical description, no action.

### C3 — Two ADRs describe a frontend that no longer exists

ADR-0009 (superseded by ADR-0026) and ADR-0013 mention frontend concerns.
ADR-0009 carries its superseded status. **No action** — that is what supersession
is for.

### C4 — `CHANGELOG.md` names archived paths

`docs/00_project/CURRENT_PROJECT_STATE.md`, `project-model.yaml`. Historical
entries, accurate when written. **No action** — a changelog that edits its own
past is not a changelog.

---

## Non-blocking gaps

Ordinary writing work; no decision needed.

| # | Gap | Destination |
|---|---|---|
| G1 | No installation guide | `docs/development/local-setup.md` |
| G2 | No MCP client connection instructions | `docs/getting-started/connect-mcp-client.md` |
| G3 | No tools reference — 30 tools, none documented | `docs/reference/mcp-tools.md` |
| G4 | Response tiers undocumented outside code | `docs/reference/response-policy.md` |
| G5 | Configuration keys never enumerated | `docs/reference/configuration.md` |
| G6 | No glossary; 30+ terms used without definition | `docs/glossary.md` |
| G7 | No error reference | `docs/reference/errors.md` |
| G8 | No architecture overview for a reader | `docs/architecture/` |
| G9 | No troubleshooting | `docs/operations/troubleshooting.md` |
| G10 | No diagrams | `docs/assets/diagrams/` |
| G11 | Retrieval threshold caveat not user-visible | `docs/workflows/retrieve-and-search.md` (VG-2) |
| G12 | Reviewer identity is unattested and unstated | `docs/reference/access-and-mutation-policy.md` (VG-3) |

---

## Inferred behaviour needing confirmation

E4 claims. **None may be published as supported until Phase 2C confirms them.**

| # | Claim | Why only inferred | How to confirm |
|---|---|---|---|
| I1 | Direct DB writes bypass domain invariants | Reasoned from transitions living in Python, not the schema. No test attempts it | Write one that does, and assert the resulting state is invalid |
| I2 | Projects are isolated on every read and write | Repositories are project-scoped; no cross-project leakage test found | Two projects, similar records, assert no bleed |
| I3 | Dependency cycles are prevented | `module_service.py` appears to check | Attempt a cycle |
| I4 | `reembedding_service` is internal | Not in the registry, not on either adapter | Confirm intent — if internal, keep it out of the documentation |
| I5 | Extraction always falls back to a fixture without a model | Observed once, on the deployed instance | Run with no Bedrock access and check the run summary |

---

## Human decisions required

Three. Everything else is writing.

### D1 — What may the public deployment guide contain?

The boundary is agreed in principle. In practice: may `docs/operations/deployment.md`
describe an EC2 shape at all, given that the working example is private? Options:
generic Linux only (safest, less useful); named cloud shapes without account
specifics (useful, needs care); or defer deployment documentation entirely.

**Blocks:** the depth of `docs/operations/deployment.md`, not its existence.

### D2 — Is a version claimed?

No release, no tag, no compatibility guarantee. Documentation implies stability
by existing, and a reader will ask what they may depend on. Something has to be
said — even "no interface stability is promised yet" is a statement.

### D3 — Is `reembedding_service` internal or unfinished?

Determines whether it is documented, hidden, or removed. **I4.**

---

## What was checked and found clean

Recorded so Phase 2B does not re-audit: no broken relative links repo-wide; no
public file names KAE-Ecosystem or any path inside it; no secrets, account
identifiers, or private hostnames in tracked files; the phrases "production
ready" and "fully supported" appear nowhere; `npm --prefix frontend` and the
`:5173` workspace claim are gone.
