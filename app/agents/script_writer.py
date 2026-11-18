"""Script writing agent contract. The extractive fallback already exists."""

from typing import Protocol

from app.schemas.workflow import ScriptRequest, ScriptResult


class ScriptWritingAgent(Protocol):
    """Turn one selected story into a grounded slide script."""

    name: str

    def run(self, request: ScriptRequest) -> ScriptResult:
        """Return a validated script. Do not add facts that are not in the request."""
