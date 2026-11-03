"""Evidence item shared by every finding."""

from typing import Literal

from pydantic import BaseModel, Field


class InvestigationEvidence(BaseModel):
    source: str = Field(description="System or document that produced this evidence.")
    detail: str = Field(description="Exact, concise evidence returned by the source.")
    source_status: Literal["simulated", "live", "unavailable"] = Field(
        description="Whether the source is simulated, live, or unavailable during the investigation."
    )
