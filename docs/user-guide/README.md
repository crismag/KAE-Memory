# KAE User Guide

Documentation for **people using KAE**, as opposed to people building it.
Everything else under `docs/` is written for contributors: architecture,
decisions, milestones, and measurements. This folder is the other audience.

## Contents

| Guide | For |
| --- | --- |
| [MCP tools](mcp-tools.md) | Working with KAE from Claude, Cursor, or any MCP client |
| [Getting started](getting-started.md) | Connecting a client and creating your first project |

## What KAE is, in one paragraph

KAE-Memory records what a software project durably knows: its requirements,
rules, decisions, constraints, and the questions it has not answered yet. Every
statement carries the evidence it came from. Nothing becomes project knowledge
until a person confirms it. Agents can read that knowledge, propose additions,
and be told plainly what is missing — which is the part that makes it different
from asking an assistant to remember things.

## Two rules that explain most of KAE's behaviour

**Confirmation is a human act.** No agent, and no tool on this surface, can turn
a proposal into confirmed project knowledge. When a tool seems unhelpfully
insistent that something is only "proposed", this is why.

**A response never claims more than it can support.** If retrieval is running
without a semantic model, the response says so. If a capability does not exist,
you get a structured gap rather than an invented answer. Reading those fields is
usually faster than discovering the limitation later.
