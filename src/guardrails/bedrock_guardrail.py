"""Direct Amazon Bedrock chat path with local EHR safety checks."""

from __future__ import annotations

import re
from typing import Any

import boto3

DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"
DEFAULT_PROFILE = "foresight"
DEFAULT_REGION = "us-east-1"
REFUSAL_MESSAGE = (
    "I am an enterprise EHR retrieval system. For legal and compliance reasons, "
    "I cannot provide new medical diagnoses or recommend medication changes. "
    "Please consult the attending physician."
)

_MEDICAL_ADVICE_PATTERN = re.compile(
    r"\b(?:prescribe|prescription|diagnos(?:e|is)|recommend|increase|decrease|"
    r"change|adjust|higher|lower)\b.*\b(?:dose|dosage|medication|medicine|drug|treatment|"
    r"symptom|furosemide)\b|\b(?:dose|dosage|medication|medicine|drug|treatment)\b.*\b"
    r"(?:increase|decrease|change|adjust|recommend|prescribe|higher|lower)\b",
    re.IGNORECASE,
)


def is_medical_advice_request(prompt: str) -> bool:
    """Return whether the prompt asks for diagnosis or treatment changes."""
    return bool(_MEDICAL_ADVICE_PATTERN.search(prompt))


class BedrockGuardedChat:
    """Call Claude through Bedrock only after the local safety check passes."""

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        profile_name: str = DEFAULT_PROFILE,
        region_name: str = DEFAULT_REGION,
    ) -> None:
        session = boto3.Session(profile_name=profile_name, region_name=region_name)
        self.client = session.client("bedrock-runtime")
        self.model_id = model_id

    def answer(self, prompt: str) -> str:
        if is_medical_advice_request(prompt):
            return REFUSAL_MESSAGE

        response: dict[str, Any] = self.client.converse(
            modelId=self.model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            system=[
                {
                    "text": (
                        "You are an EHR retrieval assistant. Answer only from information "
                        "provided in the user's request. Do not diagnose, prescribe, or "
                        "recommend medication changes. If asked for those, refuse briefly."
                    )
                }
            ],
            inferenceConfig={"temperature": 0.2, "maxTokens": 3000},
        )
        return response["output"]["message"]["content"][0]["text"]
