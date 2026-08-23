from __future__ import annotations

import argparse
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "atlas_image.py"
SPEC = importlib.util.spec_from_file_location("atlas_image", SCRIPT)
assert SPEC and SPEC.loader
atlas_image = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = atlas_image
SPEC.loader.exec_module(atlas_image)


CATALOG = {
    "code": 200,
    "data": [
        {
            "model": "openai/gpt-image-2/text-to-image",
            "display_console": True,
            "schema": "https://schema.example/model.json",
            "price": {"actual": {"base_price": "0.009"}},
        }
    ],
}

SCHEMA = {
    "paths": {
        "/api/v1/model/generateImage": {"post": {}},
        "/api/v1/model/result/{request_id}": {"get": {}},
    },
    "components": {
        "schemas": {
            "Input": {
                "required": ["model", "prompt"],
                "properties": {
                    "prompt": {"type": "string"},
                    "size": {"type": "string", "enum": ["1024x1024", "1536x1024"]},
                    "quality": {"type": "string", "enum": ["low", "medium", "high"]},
                    "output_format": {"type": "string", "enum": ["jpeg", "png"]},
                },
            }
        }
    },
}


def args(**overrides):
    values = {
        "models_url": "https://api.atlascloud.ai/api/v1/models",
        "api_base": "https://api.atlascloud.ai",
        "model": "openai/gpt-image-2/text-to-image",
        "prompt": "a test image",
        "size": "1024x1024",
        "quality": "medium",
        "output_format": "png",
        "timeout": 10,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class AtlasImageTests(unittest.TestCase):
    @patch.object(atlas_image, "_json_request", side_effect=[CATALOG, SCHEMA])
    def test_build_plan_uses_live_catalog_and_schema(self, request):
        plan = atlas_image.build_plan(args())

        self.assertEqual(plan.model, "openai/gpt-image-2/text-to-image")
        self.assertEqual(plan.unit_price, "0.009")
        self.assertEqual(plan.submit_url, "https://api.atlascloud.ai/api/v1/model/generateImage")
        self.assertIn("{request_id}", plan.result_url_template)
        self.assertEqual(request.call_count, 2)

    @patch.object(atlas_image, "_json_request", side_effect=[CATALOG, SCHEMA])
    def test_live_schema_rejects_unsupported_size(self, _request):
        with self.assertRaisesRegex(atlas_image.AtlasError, "size must be one of"):
            atlas_image.build_plan(args(size="999x999"))

    def test_auto_uses_live_schema_default(self):
        schema = json.loads(json.dumps(SCHEMA))
        quality = schema["components"]["schemas"]["Input"]["properties"]["quality"]
        quality["default"] = "medium"
        with patch.object(atlas_image, "_json_request", side_effect=[CATALOG, schema]):
            plan = atlas_image.build_plan(args(quality="auto"))
        self.assertEqual(plan.payload["quality"], "medium")

    def test_submit_is_attempted_once_on_network_error(self):
        plan = atlas_image.ModelPlan(
            model="model",
            schema_url="https://schema.example",
            submit_url="https://api.example/submit",
            result_url_template="https://api.example/result/{request_id}",
            payload={"model": "model", "prompt": "test"},
            unit_price=None,
        )
        with patch.object(atlas_image, "_json_request", side_effect=atlas_image.AtlasError("network")) as request:
            with self.assertRaises(atlas_image.AtlasError):
                atlas_image.submit_once(plan, "secret", 10)
        request.assert_called_once()

    def test_poll_retries_get_until_completed(self):
        plan = atlas_image.ModelPlan(
            model="model",
            schema_url="https://schema.example",
            submit_url="https://api.example/submit",
            result_url_template="https://api.example/result/{request_id}",
            payload={},
            unit_price=None,
        )
        responses = [
            atlas_image.AtlasError("temporary"),
            {"data": {"status": "processing"}},
            {"data": {"status": "completed", "outputs": ["https://cdn.example/image.png"]}},
        ]
        with patch.object(atlas_image, "_json_request", side_effect=responses) as request, patch.object(
            atlas_image.time, "sleep"
        ) as sleep:
            outputs = atlas_image.poll_prediction(
                plan,
                "prediction-1",
                "secret",
                attempts=3,
                interval=1,
                timeout=10,
            )
        self.assertEqual(outputs, ["https://cdn.example/image.png"])
        self.assertEqual(request.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_poll_does_not_retry_terminal_failure(self):
        plan = atlas_image.ModelPlan(
            model="model",
            schema_url="https://schema.example",
            submit_url="https://api.example/submit",
            result_url_template="https://api.example/result/{request_id}",
            payload={},
            unit_price=None,
        )
        with patch.object(
            atlas_image,
            "_json_request",
            return_value={"data": {"status": "failed"}},
        ) as request, patch.object(atlas_image.time, "sleep") as sleep:
            with self.assertRaisesRegex(atlas_image.AtlasError, "ended with status failed"):
                atlas_image.poll_prediction(
                    plan,
                    "prediction-1",
                    "secret",
                    attempts=3,
                    interval=1,
                    timeout=10,
                )
        request.assert_called_once()
        sleep.assert_not_called()

    @patch.object(atlas_image, "build_plan")
    def test_main_dry_run_never_submits(self, build_plan):
        build_plan.return_value = atlas_image.ModelPlan(
            model="model",
            schema_url="https://schema.example",
            submit_url="https://api.example/submit",
            result_url_template="https://api.example/result/{request_id}",
            payload={"model": "model", "prompt": "test"},
            unit_price="0.01",
        )
        with patch.object(atlas_image, "submit_once") as submit, patch("sys.stdout", new_callable=io.StringIO):
            result = atlas_image.main(["--prompt", "test", "--dry-run"])
        self.assertEqual(result, 0)
        submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
