"""Test suite package.

Present so ``tests.support`` resolves under a bare ``pytest`` invocation and
under mypy, which otherwise sees the same file as both ``support.database`` and
``tests.support.database``.
"""
