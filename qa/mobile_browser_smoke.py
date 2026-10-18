"""Actual touch-sized Chromium browser smoke against the running FastAPI + FFmpeg.

Run from repo root after starting an isolated local uvicorn backend. CI supplies
two synthetic source MP4s and tests the same UI the Android browser loads.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


def make_clip(path: Path, color: str, audio: bool) -> None:
    args = ["ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=15"]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    args += ["-t", "2.6", "-c:v", "mpeg4"]
    if audio:
        args += ["-c:a", "aac"]
    subprocess.run(args + [str(path)], check=True, capture_output=True)


def main() -> None:
    url = os.environ.get("BROWSER_BASE_URL", "http://127.0.0.1:8000")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        a, b = path / "android-red.mp4", path / "android-blue.mp4"
        make_clip(a, "red", True)
        make_clip(b, "blue", False)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 393, "height": 852},
                device_scale_factor=2.5, is_mobile=True,
                has_touch=True, accept_downloads=True,
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(url, wait_until="domcontentloaded")
            expect(page.locator("#video")).to_have_attribute("multiple", "")
            page.locator("#video").set_input_files([str(a), str(b)])
            expect(page.locator("#selectedList li")).to_have_count(2)
            expect(page.locator("#fileName")).to_contain_text("2 vidéos")
            # Mobile user can reorder the sources.
            page.get_by_role("button", name="Descendre android-red.mp4").click()
            expect(page.locator("#selectedList li").first).to_contain_text("android-blue.mp4")
            # Test only the real HTTP API, no mocked frontend/network requests.
            page.locator("#seconds").select_option("30")
            page.locator("#start").click()
            expect(page.locator("#preview")).to_be_visible(timeout=180_000)
            expect(page.locator("#resultVideo")).to_have_attribute("src", re.compile(r"/download"))
            expect(page.locator("#filterOptions button")).to_have_count(7)
            expect(page.locator("#metadata")).to_be_visible()
            # A fitness-recommended grade should be rendered by the backend.
            page.locator('[data-preset="impact"]').click()
            expect(page.locator("#applyFilter")).to_be_enabled()
            page.locator("#applyFilter").click()
            expect(page.locator("#filterStatus")).to_contain_text(
                "MP4 prêt à télécharger", timeout=180_000,
            )
            with page.expect_download(timeout=45_000) as download_context:
                page.locator("#download").click()
            download = download_context.value
            assert download.suggested_filename.endswith(".mp4"), download.suggested_filename
            assert not errors, f"JavaScript errors: {errors}"
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator("#deleteJob").click()
            expect(page.locator("#stage")).to_have_text(
                "Fichiers supprimés", timeout=20_000,
            )
            context.close()
            browser.close()
    print("Android-sized real browser, multi-video MP4, themed filter and download: OK")


if __name__ == "__main__":
    main()
