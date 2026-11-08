"""Explicit secret serialization ONLY for the private supervisor stdin pipe."""

import os
from collections.abc import Mapping


def browser_environment(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    private = {
        "PROXY_BALANCE",
        "PROXY_PASSWORD",
        "JWT_SIGNING_KEY",
        "AUTH_USERS",
        "ADMIN_AUTH_TOKEN",
        "OPERATOR_PASSWORD_HASH",
        "WORKER_TOKENS",
        "WORKER_TOKEN_EXPIRES_AT",
        "METRICS_AUTH_TOKEN",
        "PROXIES",
        "PROFILE_PROXY_POOL",
        "PROXY_PORT_POOL",
        "SHARED_PROXY_CHANNEL_IDS",
        "WORKER_AUTH_TOKEN",
        "S3_SECRET_KEY",
        "S3_ACCESS_KEY",
        "PROFILE_MESH_SECRET",
    }
    sanitized = {
        name: value
        for name, value in (os.environ if environment is None else environment).items()
        if name.upper().split("__", 1)[0] not in private
    }
    # Module imports run before the private stdin packet is decoded. Do not
    # bootstrap a controller/remote worker after removing its credentials.
    sanitized.update(
        CONTROLLER_URL="",
        DISTRIBUTED_WORKERS="false",
        PRODUCTION_MODE="false",
        RUNTIME_ROLE="worker",
    )
    return sanitized
