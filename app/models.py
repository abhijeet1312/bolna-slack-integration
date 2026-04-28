"""Pydantic models for Bolna webhook payloads."""


from pydantic import BaseModel, ConfigDict, Field


class TelephonyData(BaseModel):
    model_config = ConfigDict(extra="allow")
    duration: float | None = None


class BolnaExecution(BaseModel):
    """
    Subset of the Bolna execution payload that we actually care about.
    Extra fields are allowed (Bolna's payload is large and may evolve).

    Source: https://www.bolna.ai/docs/api-reference/executions/get_execution
    """

    model_config = ConfigDict(extra="allow")

    id: str
    agent_id: str
    status: str
    transcript: str | None = None
    conversation_time: float | None = None
    telephony_data: TelephonyData | None = Field(default=None)

    @property
    def effective_duration(self) -> float | None:
        """Phone-call duration is more accurate than conversation_time."""
        if self.telephony_data and self.telephony_data.duration is not None:
            return self.telephony_data.duration
        return self.conversation_time
