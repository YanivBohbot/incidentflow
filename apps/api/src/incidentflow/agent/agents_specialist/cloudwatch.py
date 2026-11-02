from langchain_openai import ChatOpenAI

from incidentflow.agent.agents_specialist.contracts import CloudWatchFinding
from incidentflow.core.config import get_settings


def build_cloudwatch_analysis_model():
    """Build the one-shot structured analyser used after bounded CloudWatch reads."""
    settings = get_settings()
    model = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
        timeout=settings.openai_timeout_seconds,
    )
    return model.with_structured_output(CloudWatchFinding)
