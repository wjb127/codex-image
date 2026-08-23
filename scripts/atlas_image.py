#!/usr/bin/env python3
"""Generate images through Atlas Cloud with one-submit semantics."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


DEFAULT_API_BASE = "https://api.atlascloud.ai"
DEFAULT_MODELS_URL = f"{DEFAULT_API_BASE}/api/v1/models"
DEFAULT_MODEL = "openai/gpt-image-2/text-to-image"
TERMINAL_SUCCESS = {"completed", "succeeded"}
TERMINAL_FAILURE = {"failed", "canceled", "cancelled"}


class AtlasError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelPlan:
    model: str
    schema_url: str
    submit_url: str
    result_url_template: str
    payload: dict[str, Any]
    unit_price: str | None


def _json_request(
    url: str,
    *,
    method: str = "GET",
    api_key: str | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "codex-image-atlas/1.0",
    }
    body = None
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except HTTPError as exc:
        raise AtlasError(f"{method} {url} failed with HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise AtlasError(f"{method} {url} failed: {exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AtlasError(f"{method} {url} returned invalid JSON") from exc

    if not isinstance(data, dict):
        raise AtlasError(f"{method} {url} returned a non-object response")
    if data.get("code") not in (None, 0, 200, "0", "200"):
        raise AtlasError(f"{method} {url} returned API code {data.get('code')}")
    return data


def _response_data(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data", response)
    if not isinstance(data, dict):
        raise AtlasError("Atlas response data is not an object")
    return data


def _catalog_models(response: dict[str, Any]) -> list[dict[str, Any]]:
    data = response.get("data", response.get("models", response))
    if not isinstance(data, list):
        raise AtlasError("Atlas model catalog is not a list")
    return [item for item in data if isinstance(item, dict)]


def _schema_paths(schema: dict[str, Any], api_base: str) -> tuple[str, str]:
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        raise AtlasError("Model schema has no paths object")

    submit_path = next(
        (path for path, methods in paths.items() if isinstance(methods, dict) and "post" in methods),
        None,
    )
    result_path = next(
        (
            path
            for path, methods in paths.items()
            if isinstance(methods, dict) and "get" in methods and "{request_id}" in path
        ),
        None,
    )
    if not submit_path or not result_path:
        raise AtlasError("Model schema does not expose submit and result endpoints")

    base = api_base.rstrip("/") + "/"
    return urljoin(base, submit_path.lstrip("/")), urljoin(base, result_path.lstrip("/"))


def _validate_payload(schema: dict[str, Any], payload: dict[str, Any]) -> None:
    components = schema.get("components", {})
    input_schema = components.get("schemas", {}).get("Input", {})
    properties = input_schema.get("properties", {})
    required = input_schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise AtlasError("Model schema has an invalid Input definition")

    allowed = set(properties) | {"model"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise AtlasError(f"Payload fields absent from the live schema: {', '.join(unknown)}")
    missing = sorted(field for field in required if field not in payload)
    if missing:
        raise AtlasError(f"Payload is missing required fields: {', '.join(missing)}")

    for field, value in payload.items():
        definition = properties.get(field)
        if not isinstance(definition, dict):
            continue
        choices = definition.get("enum")
        if isinstance(choices, list) and value not in choices:
            rendered = ", ".join(str(choice) for choice in choices)
            raise AtlasError(f"{field} must be one of: {rendered}")


def _schema_value(schema: dict[str, Any], field: str, value: Any) -> Any:
    definition = (
        schema.get("components", {})
        .get("schemas", {})
        .get("Input", {})
        .get("properties", {})
        .get(field, {})
    )
    if value != "auto" or not isinstance(definition, dict):
        return value
    choices = definition.get("enum")
    if isinstance(choices, list) and "auto" in choices:
        return value
    default = definition.get("default")
    return default if default is not None else value


def build_plan(args: argparse.Namespace) -> ModelPlan:
    catalog = _json_request(args.models_url, timeout=args.timeout)
    entry = next(
        (
            model
            for model in _catalog_models(catalog)
            if (model.get("model") or model.get("id")) == args.model
            and model.get("display_console") is True
        ),
        None,
    )
    if entry is None:
        raise AtlasError(f"Model is not available in the live Atlas catalog: {args.model}")

    schema_url = entry.get("schema") or entry.get("schema_url")
    if not isinstance(schema_url, str) or not schema_url.startswith("https://"):
        raise AtlasError("The live model entry has no HTTPS schema URL")
    schema = _json_request(schema_url, timeout=args.timeout)

    payload = {
        "model": args.model,
        "prompt": args.prompt,
        "size": _schema_value(schema, "size", args.size),
        "quality": _schema_value(schema, "quality", args.quality),
        "output_format": args.output_format,
    }
    _validate_payload(schema, payload)
    submit_url, result_url_template = _schema_paths(schema, args.api_base)

    price = entry.get("price") or entry.get("pricing") or {}
    actual = price.get("actual", {}) if isinstance(price, dict) else {}
    unit_price = actual.get("base_price") if isinstance(actual, dict) else None
    return ModelPlan(
        model=args.model,
        schema_url=schema_url,
        submit_url=submit_url,
        result_url_template=result_url_template,
        payload=payload,
        unit_price=str(unit_price) if unit_price is not None else None,
    )


def submit_once(plan: ModelPlan, api_key: str, timeout: float) -> str:
    response = _json_request(
        plan.submit_url,
        method="POST",
        api_key=api_key,
        payload=plan.payload,
        timeout=timeout,
    )
    request_id = _response_data(response).get("id") or _response_data(response).get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise AtlasError("Atlas submission returned no prediction ID")
    return request_id


def poll_prediction(
    plan: ModelPlan,
    request_id: str,
    api_key: str,
    *,
    attempts: int,
    interval: float,
    timeout: float,
) -> list[str]:
    result_url = plan.result_url_template.replace("{request_id}", request_id)
    delay = interval
    last_error: AtlasError | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = _json_request(result_url, api_key=api_key, timeout=timeout)
        except AtlasError as exc:
            last_error = exc
        else:
            data = _response_data(response)
            status = str(data.get("status", "")).lower()
            if status in TERMINAL_SUCCESS:
                outputs = data.get("outputs") or data.get("output") or []
                if isinstance(outputs, str):
                    outputs = [outputs]
                if not isinstance(outputs, list) or not all(isinstance(url, str) for url in outputs):
                    raise AtlasError("Completed prediction returned invalid outputs")
                if not outputs:
                    raise AtlasError("Completed prediction returned no outputs")
                return outputs
            if status in TERMINAL_FAILURE:
                raise AtlasError(f"Atlas prediction {request_id} ended with status {status}")
            last_error = None

        if attempt < attempts:
            time.sleep(delay)
            delay = min(delay * 2, 10)

    if last_error:
        raise AtlasError(f"Prediction polling exhausted after {attempts} attempts: {last_error}")
    raise AtlasError(f"Prediction {request_id} is still pending after {attempts} attempts")


def _output_path(directory: Path, base: str, index: int | None, extension: str) -> Path:
    stem = f"{base}-{index}" if index is not None else base
    candidate = directory / f"{stem}.{extension}"
    suffix = 1
    while candidate.exists():
        candidate = directory / f"{stem}-{suffix}.{extension}"
        suffix += 1
    return candidate


def download_outputs(urls: list[str], out_dir: Path, base: str, output_format: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    multi = len(urls) > 1
    for index, url in enumerate(urls, start=1):
        if not url.startswith(("https://", "http://")):
            raise AtlasError("Atlas returned a non-HTTP output URL")
        path = _output_path(out_dir, base, index if multi else None, output_format)
        try:
            request = Request(
                url,
                headers={"Accept": "image/*", "User-Agent": "codex-image-atlas/1.0"},
            )
            with urlopen(request, timeout=120) as response:
                with path.open("xb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            if path.exists():
                path.unlink()
            raise AtlasError(f"Failed to download generated image: {exc}") from exc
        saved.append(path)
    return saved


def _print_plan(plan: ModelPlan, count: int) -> None:
    estimated = None
    if plan.unit_price is not None:
        try:
            estimated = float(plan.unit_price) * count
        except ValueError:
            pass
    summary = {
        "model": plan.model,
        "schema": plan.schema_url,
        "payload": plan.payload,
        "submissions": count,
        "unit_price_usd": plan.unit_price,
        "estimated_total_usd": f"{estimated:.6f}" if estimated is not None else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--quality", default="medium")
    parser.add_argument("--output-format", choices=("png", "jpeg"), default="png")
    parser.add_argument("--out", type=Path, default=Path.cwd())
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate live catalog/schema and print price without submitting",
    )
    parser.add_argument("--yes", action="store_true", help="Confirm the displayed paid submissions")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--models-url", default=DEFAULT_MODELS_URL)
    parser.add_argument("--poll-attempts", type=int, default=30)
    parser.add_argument("--poll-interval", type=float, default=2)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 10:
        parser.error("--count must be between 1 and 10")
    if args.poll_attempts < 1 or args.poll_interval <= 0 or args.timeout <= 0:
        parser.error("polling and timeout values must be positive")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        plan = build_plan(args)
        _print_plan(plan, args.count)
        if args.dry_run:
            return 0
        if not args.yes:
            raise AtlasError("Paid generation not confirmed; inspect the plan, then rerun with --yes")
        api_key = os.environ.get("ATLASCLOUD_API_KEY")
        if not api_key:
            raise AtlasError("ATLASCLOUD_API_KEY is not set")

        all_urls: list[str] = []
        for _ in range(args.count):
            request_id = submit_once(plan, api_key, args.timeout)
            print(f"submitted: {request_id}", file=sys.stderr)
            all_urls.extend(
                poll_prediction(
                    plan,
                    request_id,
                    api_key,
                    attempts=args.poll_attempts,
                    interval=args.poll_interval,
                    timeout=args.timeout,
                )
            )

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        saved = download_outputs(
            all_urls,
            args.out.expanduser().resolve(),
            f"codex-image-atlas-{timestamp}",
            args.output_format,
        )
        for path in saved:
            print(path)
        return 0
    except AtlasError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
