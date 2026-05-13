#!/usr/bin/env python3
"""
Command-line client for the RTAC HMI API described by hmi.yaml.

Implemented endpoints:
  GET    /api/v1/hmi/projects
  POST   /api/v1/hmi/projects
  GET    /api/v1/hmi/projects/{HMIProjectName}
  DELETE /api/v1/hmi/projects/{HMIProjectName}
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import mimetypes
import os
import ssl
import sys
import uuid
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


API_PREFIX = "/api/v1/hmi"
PROJECTS_PATH = f"{API_PREFIX}/projects"
PROJECT_FORM_FIELD = "Project"
DEFAULT_TIMEOUT_SECONDS = 30.0


class HmiApiError(RuntimeError):
    """Raised when the RTAC HMI API returns an unsuccessful response."""

    def __init__(self, status: int, reason: str, body: bytes, headers: Dict[str, str]):
        super().__init__(f"HTTP {status} {reason}")
        self.status = status
        self.reason = reason
        self.body = body
        self.headers = headers


class HmiClient:
    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        insecure: bool = False,
        ca_bundle: Optional[str] = None,
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        self.timeout = timeout
        self.auth_header = build_auth_header(token, username, password)
        self.ssl_context = build_ssl_context(insecure=insecure, ca_bundle=ca_bundle)

    def list_projects(self) -> Tuple[int, Dict[str, str], bytes]:
        """Retrieve information about the HMI projects."""
        return self._request("GET", PROJECTS_PATH)

    def upload_project(self, project_path: Path) -> Tuple[int, Dict[str, str], bytes]:
        """Create an HMI project from an AcSELerator Diagram Builder project file."""
        body, content_type = encode_multipart_file(PROJECT_FORM_FIELD, project_path)
        return self._request(
            "POST",
            PROJECTS_PATH,
            body=body,
            headers={"Content-Type": content_type},
        )

    def download_project(self, project_name: str) -> Tuple[int, Dict[str, str], bytes]:
        """Retrieve an HMI project as an *.hprjson file."""
        return self._request("GET", project_path(project_name))

    def delete_project(self, project_name: str) -> Tuple[int, Dict[str, str], bytes]:
        """Delete an HMI project."""
        return self._request("DELETE", project_path(project_name))

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, Dict[str, str], bytes]:
        request_headers = {
            "Accept": "application/json, application/octet-stream;q=0.9, */*;q=0.8",
            "User-Agent": "rtac-hmi-cli/1.0",
        }
        if self.auth_header:
            request_headers["Authorization"] = self.auth_header
        if headers:
            request_headers.update(headers)

        url = f"{self.base_url}{path}"
        request = Request(url, data=body, headers=request_headers, method=method)

        try:
            with urlopen(
                request,
                timeout=self.timeout,
                context=self.ssl_context,
            ) as response:
                return response.status, dict(response.headers.items()), response.read()
        except HTTPError as exc:
            error_body = exc.read()
            raise HmiApiError(
                exc.code,
                exc.reason,
                error_body,
                dict(exc.headers.items()),
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"Connection failed: {exc.reason}") from exc


def normalize_base_url(base_url: str) -> str:
    value = base_url.rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base URL must include http:// or https:// and a host")
    return value


def project_path(project_name: str) -> str:
    if not project_name:
        raise ValueError("project name must not be empty")
    return f"{PROJECTS_PATH}/{quote(project_name, safe='')}"


def build_auth_header(
    token: Optional[str],
    username: Optional[str],
    password: Optional[str],
) -> Optional[str]:
    if token:
        return f"Bearer {token}"
    if username is not None:
        if password is None:
            password = getpass.getpass(f"Password for {username}: ")
        credential = f"{username}:{password}".encode("utf-8")
        return "Basic " + base64.b64encode(credential).decode("ascii")
    return None


def build_ssl_context(insecure: bool, ca_bundle: Optional[str]) -> Optional[ssl.SSLContext]:
    if insecure:
        return ssl._create_unverified_context()
    if ca_bundle:
        return ssl.create_default_context(cafile=ca_bundle)
    return None


def encode_multipart_file(field_name: str, file_path: Path) -> Tuple[bytes, str]:
    if not file_path.is_file():
        raise FileNotFoundError(f"project file does not exist: {file_path}")

    boundary = f"----rtac-hmi-{uuid.uuid4().hex}"
    filename = file_path.name
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    file_bytes = file_path.read_bytes()

    parts = [
        f"--{boundary}\r\n".encode("utf-8"),
        (
            f'Content-Disposition: form-data; name="{field_name}"; '
            f'filename="{filename}"\r\n'
        ).encode("utf-8"),
        f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
        file_bytes,
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def response_content_type(headers: Dict[str, str]) -> str:
    for key, value in headers.items():
        if key.lower() == "content-type":
            return value.lower()
    return ""


def print_api_response(status: int, headers: Dict[str, str], body: bytes) -> None:
    if not body:
        print(json.dumps({"status": status}, indent=2))
        return

    if "application/json" in response_content_type(headers):
        try:
            print(json.dumps(json.loads(body.decode("utf-8")), indent=2))
            return
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass

    sys.stdout.buffer.write(body)


def write_download(project_name: str, output: Optional[str], body: bytes) -> Path:
    output_path = Path(output) if output else Path(default_project_filename(project_name))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(body)
    return output_path


def default_project_filename(project_name: str) -> str:
    safe_name = project_name.replace("/", "_").replace("\\", "_")
    return safe_name if safe_name.endswith(".hprjson") else f"{safe_name}.hprjson"


def parse_env_bool(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_timeout() -> float:
    raw_value = os.getenv("RTAC_HMI_TIMEOUT")
    if raw_value is None:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError("RTAC_HMI_TIMEOUT must be a number of seconds") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send commands to the RTAC HMI API documented in hmi.yaml.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("RTAC_HMI_BASE_URL") or os.getenv("RTAC_BASE_URL"),
        help="RTAC base URL, such as https://rtac.example.com. "
        "Can also be set with RTAC_HMI_BASE_URL.",
    )

    auth_group = parser.add_mutually_exclusive_group()
    auth_group.add_argument(
        "--token",
        default=os.getenv("RTAC_API_TOKEN"),
        help="Bearer token. Can also be set with RTAC_API_TOKEN.",
    )
    auth_group.add_argument(
        "--username",
        default=os.getenv("RTAC_USERNAME"),
        help="Username for Basic auth. Can also be set with RTAC_USERNAME.",
    )
    auth_group.add_argument(
        "--no-auth",
        action="store_true",
        help="Send requests without an Authorization header.",
    )

    parser.add_argument(
        "--password",
        default=os.getenv("RTAC_PASSWORD"),
        help="Password for Basic auth. Prefer RTAC_PASSWORD to avoid shell history.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=env_timeout(),
        help=f"Request timeout in seconds. Default: {DEFAULT_TIMEOUT_SECONDS}.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        default=parse_env_bool(os.getenv("RTAC_HMI_INSECURE")),
        help="Disable TLS certificate verification. Can also set RTAC_HMI_INSECURE=1.",
    )
    parser.add_argument(
        "--ca-bundle",
        default=os.getenv("RTAC_CA_BUNDLE"),
        help="Path to a CA bundle for validating the RTAC HTTPS certificate.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "list-projects",
        help="GET /api/v1/hmi/projects",
    )

    upload = subparsers.add_parser(
        "upload-project",
        help="POST /api/v1/hmi/projects with multipart field Project",
    )
    upload.add_argument(
        "project_file",
        help="Path to the HMI project file to upload.",
    )

    download = subparsers.add_parser(
        "download-project",
        help="GET /api/v1/hmi/projects/{HMIProjectName}",
    )
    download.add_argument("project_name", help="HMIProjectName path parameter.")
    download.add_argument(
        "--output",
        "-o",
        help="Output path. Defaults to <project_name>.hprjson.",
    )

    delete = subparsers.add_parser(
        "delete-project",
        help="DELETE /api/v1/hmi/projects/{HMIProjectName}",
    )
    delete.add_argument("project_name", help="HMIProjectName path parameter.")

    return parser


def client_from_args(args: argparse.Namespace) -> HmiClient:
    if not args.base_url:
        raise ValueError("--base-url or RTAC_HMI_BASE_URL is required")

    token = None if args.no_auth else args.token
    username = None if args.no_auth else args.username
    if not args.no_auth and not token and not username:
        raise ValueError(
            "authentication is required: provide --token, --username, or --no-auth"
        )

    return HmiClient(
        base_url=args.base_url,
        token=token,
        username=username,
        password=args.password,
        timeout=args.timeout,
        insecure=args.insecure,
        ca_bundle=args.ca_bundle,
    )


def run_command(args: argparse.Namespace) -> int:
    client = client_from_args(args)

    if args.command == "list-projects":
        status, headers, body = client.list_projects()
        print_api_response(status, headers, body)
        return 0

    if args.command == "upload-project":
        status, headers, body = client.upload_project(Path(args.project_file))
        print_api_response(status, headers, body)
        return 0

    if args.command == "download-project":
        status, headers, body = client.download_project(args.project_name)
        output_path = write_download(args.project_name, args.output, body)
        print(
            json.dumps(
                {
                    "status": status,
                    "project": args.project_name,
                    "output": str(output_path),
                    "bytes": len(body),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "delete-project":
        status, headers, body = client.delete_project(args.project_name)
        if body:
            print_api_response(status, headers, body)
        else:
            print(json.dumps({"status": status, "deleted": args.project_name}, indent=2))
        return 0

    raise ValueError(f"unknown command: {args.command}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return run_command(args)
    except HmiApiError as exc:
        print(format_api_error(exc), file=sys.stderr)
        return 1
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def format_api_error(exc: HmiApiError) -> str:
    if not exc.body:
        return f"error: HTTP {exc.status} {exc.reason}"

    content_type = response_content_type(exc.headers)
    if "application/json" in content_type:
        try:
            payload = json.loads(exc.body.decode("utf-8"))
            detail = payload.get("detail") or payload.get("title") or payload
            return f"error: HTTP {exc.status} {exc.reason}: {detail}"
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            pass

    try:
        text = exc.body.decode("utf-8", errors="replace").strip()
    except Exception:
        text = f"{len(exc.body)} response bytes"
    return f"error: HTTP {exc.status} {exc.reason}: {text}"


if __name__ == "__main__":
    raise SystemExit(main())
