"""Loopback is not a reason to skip authentication.

The original guard refused to start on a non-loopback interface without tokens,
which is correct and does not cover the deployment ADR-0024 recommends: nginx
terminating TLS with the API bound to `127.0.0.1`. In that shape the process is
genuinely on loopback however public the proxy is, so the guard never fired —
and a missing `KAE_API_TOKENS` produced an API that started cleanly, reported
healthy, and answered every request from the internet.

It failed **open**, and silently. Nothing distinguished it from a working
deployment except making an unauthenticated call and having it succeed, which
is how it was found here — twice.

So the default is now refusal, and a deployment that genuinely wants no
authentication says so in a variable a reviewer reading the environment can see.
"""

from __future__ import annotations

import pytest

from kae_memory.api.security import InsecureDeploymentError, resolve_policy


class TestTheProxiedShapeIsNotTrusted:
    def test_loopback_without_tokens_refuses(self) -> None:
        """The defect, directly. A reverse proxy in front of a loopback listener
        is a public API, and this process cannot see the difference."""

        with pytest.raises(InsecureDeploymentError, match="without authentication"):
            resolve_policy(environ={}, host="127.0.0.1")

    def test_the_message_names_the_proxy_case(self) -> None:
        """An operator who reads 'bind to loopback for local development' will
        do exactly that and believe they are safe."""

        with pytest.raises(InsecureDeploymentError, match="reverse proxy"):
            resolve_policy(environ={}, host="127.0.0.1")

    @pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "0.0.0.0", "10.0.0.4"])
    def test_no_host_starts_unauthenticated_by_default(self, host: str) -> None:
        with pytest.raises(InsecureDeploymentError):
            resolve_policy(environ={}, host=host)


class TestTheOptOutIsDeliberate:
    def test_it_works_on_loopback(self) -> None:
        """Local development without tokens stays possible — it just has to be
        asked for."""

        policy = resolve_policy(environ={"KAE_ALLOW_UNAUTHENTICATED": "1"}, host="127.0.0.1")

        assert policy.required is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_the_obvious_affirmatives_work(self, value: str) -> None:
        assert resolve_policy(environ={"KAE_ALLOW_UNAUTHENTICATED": value}).required is False

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "maybe", "please"])
    def test_anything_else_is_not_consent(self, value: str) -> None:
        """A stray export must not disable authentication. The variable takes a
        value someone typed on purpose."""

        with pytest.raises(InsecureDeploymentError):
            resolve_policy(environ={"KAE_ALLOW_UNAUTHENTICATED": value})

    def test_it_is_refused_off_loopback(self) -> None:
        """The opt-out is for a developer's own machine. Off-loopback it would be
        an unauthenticated public API with a note attached."""

        with pytest.raises(InsecureDeploymentError, match="not for an exposed interface"):
            resolve_policy(environ={"KAE_ALLOW_UNAUTHENTICATED": "1"}, host="0.0.0.0")


class TestTokensStillWork:
    def test_configured_tokens_require_authentication(self) -> None:
        policy = resolve_policy(environ={"KAE_API_TOKENS": "studio:secret"}, host="127.0.0.1")

        assert policy.required is True

    def test_tokens_win_over_the_opt_out(self) -> None:
        """Configuring both is contradictory; the safe reading is the one that
        authenticates."""

        policy = resolve_policy(
            environ={"KAE_API_TOKENS": "studio:secret", "KAE_ALLOW_UNAUTHENTICATED": "1"},
            host="127.0.0.1",
        )

        assert policy.required is True

    def test_a_malformed_entry_still_raises(self) -> None:
        with pytest.raises(InsecureDeploymentError, match="name:token"):
            resolve_policy(environ={"KAE_API_TOKENS": "justatoken"}, host="127.0.0.1")
