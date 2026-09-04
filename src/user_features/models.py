"""Data models for extracted explicit and inferred user features."""

from pydantic import BaseModel, Field


class ExtractedUserFeatures(BaseModel):
    """Container for separated inferred and explicit user feature lists."""

    explicit: list[str] = Field(default_factory=list, description="List of explicit user features")
    inferred: list[str] = Field(default_factory=list, description="List of inferred user features")
