import unittest
from done.pipeline_loader import load_pipeline_config, validate_pipeline_manifest

class TestPipelineLoader(unittest.TestCase):
    def test_load_and_validate_hardened_pipeline(self):
        pipeline = load_pipeline_config("hardened")
        self.assertIsNotNone(pipeline)
        is_valid, errors = validate_pipeline_manifest(pipeline)
        self.assertTrue(is_valid, f"Validation errors: {errors}")

    def test_load_and_validate_all_builtin_pipelines(self):
        for name in ["hardened", "standard", "fast", "docs"]:
            pipeline = load_pipeline_config(name)
            self.assertIsNotNone(pipeline, f"Pipeline {name} failed to load")
            is_valid, errors = validate_pipeline_manifest(pipeline)
            self.assertTrue(is_valid, f"Pipeline {name} validation errors: {errors}")

    def test_validate_invalid_pipeline_structure(self):
        invalid_pipeline = {
            "version": 1,
            "tools": {
                "custom": {"description": "missing executable"}
            }
        }
        is_valid, errors = validate_pipeline_manifest(invalid_pipeline)
        self.assertFalse(is_valid)
        self.assertTrue(any("stages" in e or "pipelines" in e for e in errors))

if __name__ == "__main__":
    unittest.main()
