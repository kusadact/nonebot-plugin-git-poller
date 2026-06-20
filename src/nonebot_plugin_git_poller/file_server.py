from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from secrets import token_urlsafe
import time
from urllib.parse import quote, urlencode

from nonebot import get_driver, logger
from nonebot_plugin_localstore import get_plugin_cache_dir

from .config import Config

_runtime_file_token = token_urlsafe(24)
_route_registered = False
ARCHIVE_FILE_ROUTE_PREFIX = "/git-poller/files"
ARCHIVE_FILE_TOKEN_TTL_SECONDS = 3600


def register_archive_file_route(config: Config) -> bool:
    driver = get_driver()
    server_app = getattr(driver, "server_app", None)
    if server_app is None or not hasattr(server_app, "add_api_route"):
        message = "git poller archive HTTP route is unavailable: current driver has no server_app"
        if config.git_poller_file_base_url:
            raise RuntimeError(
                f"{message}. git_poller_file_base_url is configured, so OneBot needs "
                "an HTTP route to download archives. Use a driver with server_app support "
                "or unset git_poller_file_base_url."
            )
        logger.warning(message)
        return False

    if not config.git_poller_file_base_url:
        return False

    global _route_registered
    if _route_registered:
        return True

    from starlette.responses import FileResponse, Response

    route_prefix = ARCHIVE_FILE_ROUTE_PREFIX

    async def serve_archive(
        filename: str,
        expires: str | None = None,
        token: str | None = None,
    ) -> Response:
        if not valid_archive_download_token(filename, expires, token):
            logger.warning(f"git poller archive download rejected for {filename}: invalid token")
            return Response(status_code=403)
        if "/" in filename or "\\" in filename:
            logger.warning(f"git poller archive download rejected for unsafe filename: {filename}")
            return Response(status_code=404)

        archive_dir = (get_plugin_cache_dir() / "archives").resolve()
        archive_path = (archive_dir / filename).resolve()
        try:
            archive_path.relative_to(archive_dir)
        except ValueError:
            return Response(status_code=404)

        if not archive_path.is_file():
            logger.warning(f"git poller archive download not found: {archive_path}")
            return Response(status_code=404)

        logger.info(f"git poller serving archive download: {archive_path}")
        return FileResponse(
            archive_path,
            media_type="application/x-7z-compressed",
            filename=filename,
        )

    server_app.add_api_route(
        f"{route_prefix}/{{filename}}",
        serve_archive,
        methods=["GET"],
    )
    _route_registered = True
    logger.info(f"git poller archive HTTP route registered: {route_prefix}/{{filename}}")
    return True


def build_archive_download_url(path: Path, config: Config) -> str | None:
    if not config.git_poller_file_base_url:
        return None
    base_url = config.git_poller_file_base_url.rstrip("/")
    route_prefix = ARCHIVE_FILE_ROUTE_PREFIX
    filename = quote(path.name)
    expires_at = int(time.time()) + ARCHIVE_FILE_TOKEN_TTL_SECONDS
    query = urlencode(
        {
            "expires": str(expires_at),
            "token": archive_download_token(path.name, expires_at),
        }
    )
    return f"{base_url}{route_prefix}/{filename}?{query}"


def _archive_file_token() -> str:
    return _runtime_file_token


def valid_archive_download_token(
    filename: str,
    expires: str | None,
    token: str | None,
) -> bool:
    if not expires or not token:
        return False
    try:
        expires_at = int(expires)
    except ValueError:
        return False
    if expires_at < int(time.time()):
        return False
    expected = archive_download_token(filename, expires_at)
    return hmac.compare_digest(token, expected)


def archive_download_token(filename: str, expires_at: int) -> str:
    message = f"{filename}\0{expires_at}".encode("utf-8")
    secret = _archive_file_token().encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()
