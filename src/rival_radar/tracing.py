from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from rival_radar.config import settings


def get_callback(run_name: str = "rival-radar"):
    """Return a Langfuse CallbackHandler if keys are configured, else None."""
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return None

    from langfuse.callback import CallbackHandler  # lazy: only needed when keys are present

    return CallbackHandler(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
        trace_name=run_name,
        tags=["rival-radar"],
    )


def build_run_config(run_name: str = "rival-radar") -> RunnableConfig:
    """Return a LangGraph-compatible run config with Langfuse callback if available."""
    callback = get_callback(run_name=run_name)
    config: RunnableConfig = {"run_name": run_name}
    if callback:
        config["callbacks"] = [callback]
    return config
