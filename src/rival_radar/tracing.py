from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from rival_radar.config import settings


def get_callback(run_name: str = "rival-radar"):
    """Return a Langfuse CallbackHandler if real keys are configured, else None."""
    pk = settings.langfuse_public_key or ""
    sk = settings.langfuse_secret_key or ""
    if not pk or not sk or pk.startswith("pk-placeholder") or sk.startswith("sk-placeholder"):
        return None

    try:
        from langfuse.langchain import CallbackHandler  # langfuse >= 2.x
    except ImportError:
        from langfuse.callback import CallbackHandler  # type: ignore[no-redef]

    return CallbackHandler(
        public_key=pk,
        secret_key=sk,
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
