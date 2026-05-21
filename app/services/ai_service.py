from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.services.kb_content import KB

logger = logging.getLogger(__name__)


def parse_json_response(output: str) -> dict[str, Any]:
    output = output.strip()

    # remove markdown fences
    output = re.sub(r"^```json\s*", "", output)
    output = re.sub(r"^```\s*", "", output)
    output = re.sub(r"\s*```$", "", output)

    # extract first JSON object
    match = re.search(r"\{.*\}", output, re.DOTALL)

    if not match:
        raise ValueError(f"No JSON object found in AI response: {output}")

    return json.loads(match.group())


CATEGORIES = [
    "Royalty & Payments",
    "ISBN & Metadata Issues",
    "Printing & Quality",
    "Distribution & Availability",
    "Book Status & Production Updates",
    "General Inquiry",
]
PRIORITIES = ["Critical", "High", "Medium", "Low"]


class AIService:
    def __init__(self) -> None:
        self.enabled = bool(settings.groq_api_key)
        if not self.enabled:
            self.classifier_model = None
            self.generator_model = None
            return

        self.classifier_model = ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.groq_model_classifier,
            temperature=0,
            timeout=settings.ai_timeout_seconds,
        )
        self.generator_model = ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.groq_model_generator,
            temperature=0.2,
            timeout=settings.ai_timeout_seconds,
        )

    async def _invoke_with_retry(self, model: ChatGroq, messages: list[Any]) -> str:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(settings.ai_retry_attempts),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=6),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        ):
            with attempt:
                response = await model.ainvoke(messages)
                return str(response.content)
        raise RuntimeError("AI invocation failed after retries")

    async def _safe_ai_call(self, call_name: str, executor, fallback_payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {**fallback_payload, "source": "fallback", "reason": "ai_disabled"}

        try:
            return await executor()
        except Exception as exc:  # noqa: BLE001
            logger.exception("AI call failed for %s: %s", call_name, exc)
            return {**fallback_payload, "source": "fallback", "reason": "ai_error"}

    async def classify_ticket(self, subject: str, description: str) -> dict[str, Any]:
        async def _executor() -> dict[str, Any]:
            prompt = f"""
You are a JSON API.

Classify the support ticket into exactly one category from:
{", ".join(CATEGORIES)}

Rules:
- Return ONLY valid JSON
- Do NOT use markdown
- Do NOT add explanations
- Do NOT add extra text
- Response must start with {{
- Response must end with }}

Expected schema:
{{
  "category": "string",
  "confidence": number
}}
"""

            text = f"""
Subject: {subject}

Description:
{description}
"""

            output = await self._invoke_with_retry(
                self.classifier_model,
                [
                    SystemMessage(content=prompt),
                    HumanMessage(content=text),
                ],
            )

            logger.info("Raw classify_ticket output: %s", output)

            parsed = parse_json_response(output)

            category = parsed.get("category", "General Inquiry")

            if category not in CATEGORIES:
                category = "General Inquiry"

            try:
                confidence = float(parsed.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5

            confidence = max(0.0, min(confidence, 1.0))

            return {
                "category": category,
                "confidence": confidence,
                "source": "ai",
            }

        fallback = {
            "category": "General Inquiry",
            "confidence": 0.0,
            "source": "fallback",
        }

        return await self._safe_ai_call(
            "classify_ticket",
            _executor,
            fallback,
        )

    async def prioritize_ticket(self, subject: str, description: str) -> dict[str, Any]:
        async def _executor() -> dict[str, Any]:
            prompt = f"""
        You are a JSON API for support ticket prioritization.

        Your task is to assign exactly one priority level to the support ticket.

        Allowed priorities:
        - Critical
        - High
        - Medium
        - Low

        Priority guidelines:

        Critical:
        - Payout delays across quarters
        - Legal/compliance risk
        - Data corruption or integrity issues
        - Security incidents
        - System-wide outages

        High:
        - Payment delays
        - Production bugs affecting multiple users
        - Important account access issues
        - Major workflow blockers

        Medium:
        - Standard operational issues
        - Bugs with workarounds
        - Delayed responses
        - Minor feature problems

        Low:
        - General questions
        - Feature requests
        - Cosmetic/UI issues
        - Non-urgent requests

        Rules:
        - Return ONLY valid JSON
        - Do NOT use markdown
        - Do NOT add explanations
        - Do NOT add notes
        - Do NOT add extra text
        - Response must start with {{
        - Response must end with }}

        Expected JSON schema:
        {{
        "priority": "Critical | High | Medium | Low",
        "confidence": number
        }}
        """

            text = f"""
        Subject: {subject}

        Description:
        {description}
        """

            output = await self._invoke_with_retry(
                self.classifier_model,
                [
                    SystemMessage(content=prompt),
                    HumanMessage(content=text),
                ],
            )

            logger.info("Raw prioritize_ticket output: %s", output)

            parsed = parse_json_response(output)

            priority = parsed.get("priority", "Medium")

            if priority not in PRIORITIES:
                priority = "Medium"

            try:
                confidence = float(parsed.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5

            confidence = max(0.0, min(confidence, 1.0))

            return {
                "priority": priority,
                "confidence": confidence,
                "source": "ai",
            }

        fallback = {
            "priority": "Medium",
            "confidence": 0.0,
            "source": "fallback",
        }

        return await self._safe_ai_call(
            "prioritize_ticket",
            _executor,
            fallback,
        )
 
    async def draft_response(self, ticket: dict[str, Any], author: dict[str, Any], book: dict[str, Any] | None = None) -> dict[str, Any]:
        async def _executor() -> dict[str, Any]:
            system_prompt = (
                "You are BookLeaf Support. Use empathetic professional tone. "
                "Acknowledge concern first, provide specific timeline and clear next step. "
                "Do not invent internal policies."
            )
            ticket_text = (
                f"Author: {author.get('name')} ({author.get('email')})\n"
                f"Subject: {ticket.get('subject')}\n"
                f"Description: {ticket.get('description')}\n"
                f"Category: {ticket.get('category')}\n"
                f"Priority: {ticket.get('priority')}\n"
            )
            book_text = ""
            if book:
                book_text = (
                    f"Book context: title={book.get('title')}, isbn={book.get('isbn')}, "
                    f"status={book.get('status')}, royaltyPending={book.get('royaltyPending')}"
                )

            user_prompt = f"Knowledge Base:\n{KB}\n\nTicket:\n{ticket_text}\n{book_text}\n\nDraft response in 120-180 words."
            output = await self._invoke_with_retry(
                self.generator_model,
                [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
            )
            return {"draft": output.strip(), "source": "ai"}

        fallback = {
            "draft": (
                "Thank you for reaching out and sharing this. I understand your concern and we are reviewing the details now. "
                "Our team has logged your ticket and an operations specialist will provide a concrete update within 48 hours. "
                "If applicable, please share any supporting screenshots or references so we can speed up resolution."
            )
        }
        return await self._safe_ai_call("draft_response", _executor, fallback)


ai_service = AIService()
