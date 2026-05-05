from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

MAX_FALLBACK_TITLE_LENGTH = 60


class ChatTitleGenerator(Protocol):
    def generate_title(self, *, first_message: str, model: str) -> str: ...


@dataclass(frozen=True)
class TitleGenerationDependencies:
    first_message: str


class ChatTitleOutput(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class PydanticAIChatTitleGenerator:
    def __init__(self, *, model: Model | str) -> None:
        self._agent = Agent(
            model,
            output_type=ChatTitleOutput,
            deps_type=TitleGenerationDependencies,
            instructions=_title_generation_instructions,
        )

    def generate_title(self, *, first_message: str, model: str) -> str:
        result = self._agent.run_sync(
            "Create a short title for this chat session.",
            deps=TitleGenerationDependencies(first_message=first_message),
        )
        return " ".join(result.output.title.split())


def fallback_title(first_message: str) -> str:
    normalized = " ".join(first_message.split())
    if not normalized:
        return "New chat"

    if len(normalized) <= MAX_FALLBACK_TITLE_LENGTH:
        return normalized

    return normalized[: MAX_FALLBACK_TITLE_LENGTH - 1].rstrip() + "..."


def _title_generation_instructions(ctx: RunContext[TitleGenerationDependencies]) -> str:
    return "\n\n".join(
        [
            "Generate a concise title for a saved chat session from the first user message.",
            "Use 2 to 6 words. Do not add quotes, trailing punctuation, or generic prefixes.",
            "Return only the structured title.",
            f"First user message:\n{ctx.deps.first_message}",
        ]
    )
