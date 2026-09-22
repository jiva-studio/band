import tempfile
import shutil
import unittest
from pathlib import Path
from done.cache import ClaimCache

class TestClaimCache(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.cache = ClaimCache(self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_cache_miss_and_put(self):
        claim = {"id": "c1", "kind": "make", "target": "check"}
        # Initial check should be cache miss
        cached = self.cache.get("c1", claim)
        self.assertIsNone(cached)

        # Put cached result
        res = {"success": True, "message": "All passed"}
        self.cache.put("c1", claim, res)

        # Retrieve cached result
        cached2 = self.cache.get("c1", claim)
        self.assertIsNotNone(cached2)
        self.assertTrue(cached2.get("success"))
        self.assertEqual(cached2.get("message"), "All passed")

    def test_cache_invalidation_on_claim_params_change(self):
        claim_v1 = {"id": "c1", "kind": "make", "target": "check", "params": {"PKG": "@vidya/domain"}}
        self.cache.put("c1", claim_v1, {"success": True, "message": "v1 passed"})

        claim_v2 = {"id": "c1", "kind": "make", "target": "check", "params": {"PKG": "@vidya/api"}}
        cached_v2 = self.cache.get("c1", claim_v2)
        self.assertIsNone(cached_v2)

    def test_cache_clear(self):
        claim = {"id": "c1", "kind": "make", "target": "check"}
        self.cache.put("c1", claim, {"success": True})
        self.assertIsNotNone(self.cache.get("c1", claim))

        self.cache.clear()
        self.assertIsNone(self.cache.get("c1", claim))

if __name__ == "__main__":
    unittest.main()
