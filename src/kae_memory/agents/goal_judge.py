"""Judging whether a candidate belongs in a project's goal model.

`D-101`: three deterministic exclusions were tried against the golden corpus and
each failed, so membership is a judgement. This is where that judgement is made,
and the prompt lives here rather than in a test — a prompt measured in a test and
re-typed in the product is two prompts, and only one of them was measured.

## What was measured

Against `qwen2.5:14b` on the corpus. The **first** shape of this prompt asked
whether a candidate matched what the project had established, and the model
refused **every** candidate — a project with no goals at all. A project's goals
are diverse by nature, so *does this match the dominant theme* excludes most of
them.

Asking what the sentence **is**, with the project's own wording as background
rather than as a filter, and naming the two ways to fail, recovers them: eight
of nine probe statements judged as a person would, the ninth being *"Cloud
providers are adapters, not the canonical runtime"* — refused as a goal, which
is arguable, since doc 02 asks goal synthesis to reclassify architecture
statements rather than keep them.

## Which way it is allowed to be wrong

Not symmetric. Admitting a marginal goal costs a person one deletion. Dropping a
real one loses it silently — nobody removes what they never saw. The prompt says
so, and the tolerance is the reason the live gate asserts a floor on how many
goals survive rather than a ceiling.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence

import httpx

from kae_memory.domain.synthesizers.goals import GoalJudgement

from .extraction import ProviderUnavailableError

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL_ENV_HINT = "KAE_GOAL_JUDGE_MODEL"
DEFAULT_MODEL = "qwen2.5:14b"


def prompt_for(statement: str, identity: Sequence[str]) -> str:
    """The judged question, in the words that were measured."""

    background = "\n".join(f"- {line}" for line in identity) or "- (nothing established yet)"
    return (
        "A project is being planned. Here is what it says about itself, for background:\n"
        f"{background}\n\n"
        f"Sentence: {statement!r}\n\n"
        "Question: is this sentence about what the software should achieve, do, or be like?\n"
        "Answer false only if it is an instruction about the conversation itself, or if it "
        "describes nothing to do with software at all.\n"
        "Being about a different part of the software than the background mentions is fine — "
        "a project has many goals.\n"
        "When unsure, answer true: a person can remove a goal they can see, and cannot "
        "restore one they never saw.\n"
        'Answer with JSON only: {"include": true|false, "reason": "one short sentence"}'
    )


class OllamaGoalJudge:
    """Ask the model this deployment already runs (`ADR-0006`).

    One candidate per call, deliberately. A judge handed the whole corpus and
    asked to *synthesize goals* is the generic summarizer doc 12 forbids, and
    nothing it returned could be attributed to any particular evidence.
    """

    def __init__(
        self,
        *,
        base_url: str = OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._transport = transport

    def judge(self, statement: str, identity: Sequence[str]) -> GoalJudgement:
        payload = {
            "model": self._model,
            "prompt": prompt_for(statement, identity),
            "stream": False,
            "format": "json",
        }
        try:
            with httpx.Client(
                base_url=self._base_url, timeout=self._timeout, transport=self._transport
            ) as client:
                response = client.post("/api/generate", json=payload)
                response.raise_for_status()
                body = json.loads(response.json()["response"])
        except httpx.HTTPError as error:
            raise ProviderUnavailableError(
                f"Ollama is not reachable at {self._base_url}: {type(error).__name__}. "
                "Start it, or unset KAE_GOAL_JUDGE to synthesize without a judge."
            ) from error
        except (KeyError, ValueError) as error:
            # A judge that cannot be parsed must not read as a refusal. Refusing
            # on malformed output would quietly delete goals whenever the model
            # returned prose, which is the failure this estate calls a silent
            # empty.
            raise ProviderUnavailableError(
                f"{self._model} did not answer with the requested JSON: {error}"
            ) from error

        return GoalJudgement(
            include=bool(body.get("include")),
            reason=str(body.get("reason", "")).strip() or "No reason given.",
        )


def default_goal_judge() -> OllamaGoalJudge | None:
    """The judge this deployment is configured for, or none.

    `None` is a supported deployment, not a broken one: synthesis then promotes
    only corroborated clusters and says so. Opt-in rather than automatic,
    because a judge is a model call per candidate and that is a cost decision —
    the same reasoning that keeps `REV-AUTO` a button.
    """

    if os.environ.get("KAE_GOAL_JUDGE", "").strip().lower() != "ollama":
        return None
    return OllamaGoalJudge(
        base_url=os.environ.get("KAE_OLLAMA_URL", OLLAMA_URL).strip() or OLLAMA_URL,
        model=os.environ.get("KAE_GOAL_JUDGE_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
    )
