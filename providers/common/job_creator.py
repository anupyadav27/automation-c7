"""
Kubernetes Job launcher shared by the engine APIs.

`create_engine_job` creates a batch/v1 Job that runs one engine scan on a
spot node and returns the job name. It is only meaningful inside a cluster
(or with a kubeconfig); callers surface the raised RuntimeError as an HTTP
error, so local file-mode pipelines never come through here.
"""
import logging
import os
import re

logger = logging.getLogger(__name__)


def _load_kube_config():
    from kubernetes import config

    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()


def create_engine_job(
    engine_name: str,
    scan_id: str,
    scan_run_id: str,
    image: str,
    cpu_request: str = "250m",
    mem_request: str = "1Gi",
    cpu_limit: str = "1",
    mem_limit: str = "2Gi",
    active_deadline_seconds: int = 3600,
    env: dict = None,
    namespace: str = None,
) -> str:
    """Create a K8s Job for one engine scan; returns the job name."""
    try:
        from kubernetes import client
    except ImportError as exc:
        raise RuntimeError(
            "kubernetes client not installed — Job-based scans need the "
            "cluster runtime (pip install kubernetes), or use the local "
            "pipeline: python -m orchestration.pipeline"
        ) from exc

    _load_kube_config()
    namespace = namespace or os.getenv("ENGINE_NAMESPACE", "default")

    # RFC 1123: lowercase alphanumerics and '-', max 63 chars
    suffix = re.sub(r"[^a-z0-9-]", "-", scan_run_id.lower())[:24].strip("-")
    job_name = f"{engine_name}-scan-{suffix}"

    env_vars = {
        "SCAN_ID": scan_id,
        "SCAN_RUN_ID": scan_run_id,
        "ENGINE_NAME": engine_name,
        **(env or {}),
    }

    container = client.V1Container(
        name=engine_name,
        image=image,
        env=[client.V1EnvVar(name=k, value=str(v)) for k, v in env_vars.items()],
        resources=client.V1ResourceRequirements(
            requests={"cpu": cpu_request, "memory": mem_request},
            limits={"cpu": cpu_limit, "memory": mem_limit},
        ),
    )
    pod_spec = client.V1PodSpec(
        restart_policy="Never",
        containers=[container],
        node_selector={"karpenter.sh/capacity-type": "spot"}
        if os.getenv("SCANNER_USE_SPOT", "true").lower() == "true"
        else None,
    )
    job = client.V1Job(
        metadata=client.V1ObjectMeta(
            name=job_name,
            labels={"app": engine_name, "scan-run-id": suffix},
        ),
        spec=client.V1JobSpec(
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": engine_name}),
                spec=pod_spec,
            ),
            backoff_limit=1,
            ttl_seconds_after_finished=86400,
            active_deadline_seconds=active_deadline_seconds,
        ),
    )

    client.BatchV1Api().create_namespaced_job(namespace=namespace, body=job)
    logger.info("Created Job %s in %s (image=%s)", job_name, namespace, image)
    return job_name
