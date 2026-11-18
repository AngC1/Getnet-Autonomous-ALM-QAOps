"""Adaptador S3 fino para el Bucket_Medios (us-east-1).

- ``put/get/exists`` con reintentos de 1, 2 y 4 s.
- Si falla tambien el tercer reintento, la operacion se marca fallida, se
  notifica operacion y activo y los datos locales quedan pendientes.
- Solo se permiten los prefijos ``brand/`` e ``incidents/``.
- Sin credenciales en codigo: boto3 usa la cadena estandar de credenciales.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Union

REGION = "us-east-1"
BUCKET_ENV = "MEDIA_BUCKET"
DEFAULT_BUCKET = "me-hack-media-385927210791-us-east-1"
ALLOWED_PREFIXES = ("brand/", "incidents/")
RETRY_DELAYS_S = (1, 2, 4)

log = logging.getLogger(__name__)


class S3OperationFailed(Exception):
    """La operacion S3 fallo tras agotar los reintentos."""

    def __init__(self, operation: str, key: str, asset_id: Optional[str], cause: BaseException):
        self.operation = operation
        self.key = key
        self.asset_id = asset_id
        self.cause = cause
        super().__init__(
            "S3 %s fallida (activo=%s, clave=%s): %s"
            % (operation, asset_id, key, type(cause).__name__)
        )


@dataclass
class PendingOp:
    """Operacion fallida cuyos datos locales siguen pendientes de subir."""

    operation: str
    key: str
    asset_id: Optional[str]
    data: Optional[bytes] = None
    local_path: Optional[str] = None


def check_key(key: str) -> str:
    """Valida que la clave este bajo un prefijo permitido y no escape de el."""
    if (
        not isinstance(key, str)
        or not key.startswith(ALLOWED_PREFIXES)
        or ".." in key.split("/")
    ):
        raise ValueError("Clave S3 fuera de los prefijos permitidos: %r" % (key,))
    return key


def _is_not_found(exc: BaseException) -> bool:
    err = getattr(exc, "response", None)
    if not isinstance(err, dict):
        return False
    code = str(err.get("Error", {}).get("Code", ""))
    status = err.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in ("404", "NoSuchKey", "NotFound") or status == 404


class S3IO:
    def __init__(
        self,
        client: Any = None,
        bucket: Optional[str] = None,
        sleep: Callable[[float], None] = time.sleep,
        notify: Optional[Callable[[str, Optional[str], str], None]] = None,
        delays: tuple = RETRY_DELAYS_S,
    ):
        if client is None:
            import boto3  # import perezoso: los tests inyectan un cliente falso

            client = boto3.client("s3", region_name=REGION)
        self._client = client
        self.bucket = bucket or os.environ.get(BUCKET_ENV) or DEFAULT_BUCKET
        self._sleep = sleep
        self._notify = notify
        self._delays = tuple(delays)
        self.pending: List[PendingOp] = []

    # -- nucleo de reintentos -------------------------------------------------
    def _run(self, operation: str, key: str, asset_id: Optional[str], fn: Callable[[], Any],
             pending: Optional[PendingOp] = None) -> Any:
        last: Optional[BaseException] = None
        for attempt in range(len(self._delays) + 1):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001 - se reintenta cualquier fallo de red/S3
                if operation == "exists" and _is_not_found(exc):
                    raise
                last = exc
                if attempt < len(self._delays):
                    log.warning("S3 %s fallo (activo=%s), reintento en %ss", operation,
                                asset_id, self._delays[attempt])
                    self._sleep(self._delays[attempt])
        assert last is not None
        if pending is not None:
            self.pending.append(pending)
        msg = "S3 %s FALLIDA para activo=%s clave=%s; datos locales pendientes" % (
            operation, asset_id, key)
        log.error(msg)
        if self._notify is not None:
            self._notify(operation, asset_id, key)
        raise S3OperationFailed(operation, key, asset_id, last)

    # -- API publica ----------------------------------------------------------
    def put(self, key: str, data: Union[bytes, str], asset_id: Optional[str] = None,
            content_type: Optional[str] = None) -> None:
        """Sube bytes, o el fichero local si ``data`` es una ruta (str)."""
        check_key(key)
        if isinstance(data, str):
            path = data
            pend = PendingOp("put", key, asset_id, local_path=path)

            def fn() -> None:
                with open(path, "rb") as fh:
                    self._put_body(key, fh.read(), content_type)
        else:
            body = bytes(data)
            pend = PendingOp("put", key, asset_id, data=body)

            def fn() -> None:
                self._put_body(key, body, content_type)

        self._run("put", key, asset_id, fn, pend)

    def _put_body(self, key: str, body: bytes, content_type: Optional[str]) -> None:
        kwargs = {"Bucket": self.bucket, "Key": key, "Body": body}
        if content_type:
            kwargs["ContentType"] = content_type
        self._client.put_object(**kwargs)

    def get(self, key: str, asset_id: Optional[str] = None) -> bytes:
        check_key(key)

        def fn() -> bytes:
            resp = self._client.get_object(Bucket=self.bucket, Key=key)
            return resp["Body"].read()

        return self._run("get", key, asset_id, fn)

    def exists(self, key: str, asset_id: Optional[str] = None) -> bool:
        check_key(key)

        def fn() -> bool:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True

        try:
            return self._run("exists", key, asset_id, fn)
        except S3OperationFailed:
            raise
        except Exception as exc:  # 404 sin reintentos
            if _is_not_found(exc):
                return False
            raise
