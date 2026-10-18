"""Static UI regressions: Android-first controls, portable assets and JS syntax."""
import json
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path


WEB = Path(__file__).resolve().parents[1] / "web"


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_script = False
        self.blocks = []
    def handle_starttag(self, tag, attrs):
        if tag == "script" and not dict(attrs).get("src"):
            self.in_script = True
    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False
    def handle_data(self, data):
        if self.in_script:
            self.blocks.append(data)


class StaticMobileTests(unittest.TestCase):
    def test_mobile_interface_and_assets(self):
        source = (WEB / "index.html").read_text(encoding="utf-8")
        manifest = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["display"], "standalone")
        self.assertIn("video/*", source)
        self.assertIn('id="resumeJob"', source)
        self.assertIn('id="testBackend"', source)
        self.assertIn('[hidden]{display:none!important}', source)
        self.assertIn('monteur-video-beta.onrender.com', source)
        self.assertIn('monteur-video-hd.onrender.com', source)
        self.assertIn('LOCAL_HOST ? "" : DEFAULT_BACKEND', source)
        self.assertIn('127.0.0.1', source)
        self.assertIn('localStorage.removeItem("backendUrl")', source)
        self.assertIn('id="tokenLabel" hidden', source)
        self.assertIn('id="retryRender"', source)
        self.assertIn('id="retention"', source)
        self.assertIn('"/api/session"', source)
        self.assertIn('"/retry"', source)
        self.assertIn('pollFailures++', source)
        self.assertIn('id="download"', source)
        self.assertIn("download-link", source)
        self.assertIn("ongoingUpload", source)
        self.assertIn('localStorage.getItem("ongoingUploads")', source)
        self.assertIn('id="filterPanel"', source)
        self.assertIn('id="filterOptions"', source)
        self.assertIn('id="applyFilter"', source)
        self.assertIn('type="file" multiple', source)
        self.assertIn('"/api/montages"', source)
        self.assertIn("project_id:batch.id", source)
        self.assertIn('"?preset=" + encodeURIComponent(activePreset)', source)
        self.assertIn('credentials: API_BASE ? "omit"', source)
        self.assertIn("Bearer ", source)
        self.assertTrue((WEB / "icon.svg").exists())
        self.assertTrue((WEB / "sw.js").exists())
        self.assertNotIn('caches.open(CACHE).then(cache => cache.add("/api', (WEB / "sw.js").read_text())

    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable")
    def test_inline_javascript_and_service_worker_parse(self):
        parser = Scripts()
        parser.feed((WEB / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(len(parser.blocks), 1)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "studio.js"
            target.write_text(parser.blocks[0], encoding="utf-8")
            subprocess.run(["node", "--check", str(target)], check=True, capture_output=True)
        subprocess.run(["node", "--check", str(WEB / "sw.js")],
                       check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
