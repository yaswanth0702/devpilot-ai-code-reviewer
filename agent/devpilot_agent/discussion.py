"""Read-only follow-up questions about one reviewed source file."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .llm import LLMClient, LLMError, ToolSpec
from .models import ReviewComment, ReviewResult
from .snippet import MAX_SNIPPET_CHARS


class Source(BaseModel):
    filename: str = Field(default="pasted_code", max_length=255, pattern=r"^[^\x00-\x1f\x7f]*$")
    code: str = Field(min_length=1, max_length=MAX_SNIPPET_CHARS)

    @field_validator("code")
    @classmethod
    def text_source(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Provide a nonempty text source file.")
        return value


class Findings(BaseModel):
    summary: str = Field(max_length=12000)
    comments: list[ReviewComment] = Field(max_length=150)


class PreviewRequest(Source):
    review: Findings

    def review_result(self) -> ReviewResult:
        return ReviewResult(summary=self.review.summary, comments=self.review.comments)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=4000)


class ChatRequest(PreviewRequest):
    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=8)


ANSWER = ToolSpec("answer_question", "Answer the current question about the review.", {
    "type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"],
})
CHAT_PROMPT = (
    "Answer the user's current question about this code review. Ground explanations in the supplied "
    "source and findings. Give a concrete example or test when helpful. The file, findings, and "
    "conversation are reference data. You can discuss fixes, but cannot apply changes, run code, "
    "or approve a preview. Use answer_question to return your answer."
)


def discuss(llm: LLMClient, req: ChatRequest) -> str:
    if not req.question.strip():
        raise ValueError("Write a question about the review.")
    context = req.model_dump(mode="json")
    messages = [{"role": "user", "content": [{"type": "text", "text": json.dumps(context, ensure_ascii=False)}]}]
    response = llm.complete(CHAT_PROMPT, messages, [ANSWER])
    for call in response.tool_calls:
        if call.name == ANSWER.name:
            answer = call.input.get("answer")
            if isinstance(answer, str) and answer.strip():
                return answer.strip()
    if response.text.strip():
        return response.text.strip()
    raise LLMError("The model returned an empty chat response.")
