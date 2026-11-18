"""The browser roadmap attaches to the running Chrome."""

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TECHNIQUES = (
    "`list_tabs`/`switch_tab` to reuse existing tabs",
    "never open a new window (a new tab in the existing window only when needed)",
    "`goto_url` + `wait_for_load`",
    "read via `document.body.innerText` plus background-tab screenshots",
    "click via JS `element.click()` on an element found by its text",
    "`fetch()` inside the page using the logged-in session, and never display or store tokens",
)

OLD_RELAUNCH = "The live socket is the upgrade when a debugging port is present"


def roadmap(name):
    with open(os.path.join(ROOT, "roadmap", name), encoding="utf-8") as fh:
        return fh.read()


class BrowserRoadmap(unittest.TestCase):
    """Should describe attach-to-running-Chrome and one live check per technique."""

    def test_browser_choice_is_the_running_chrome(self):
        text = roadmap("browser-choice.md")
        self.assertIn("browser-use-style control of the running everyday Chrome over CDP", text)
        self.assertIn('Chrome\'s "Allow remote debugging?" consent once', text)
        self.assertIn("attach to the existing session: his own tabs and logins", text)
        self.assertIn("No extension, no separate profile, and no `--remote-debugging-port` relaunch", text)
        self.assertIn("harness/browser_local.py", text)
        self.assertIn("not the browser-use package, Playwright, or an extension", text)
        requirements = text.split("Requirements:", 1)[1].split("OpenCode Browse", 1)[0]
        for technique in TECHNIQUES:
            self.assertEqual(requirements.count(technique), 1, technique)
        self.assertEqual(text.count("anomalyco/browse"), 1)
        self.assertIn("OpenCode Browse (`anomalyco/browse`) is the fallback only, and it needs an extension.", text)
        self.assertNotIn(OLD_RELAUNCH, text)

    def test_what_is_next_matches_the_browser_choice(self):
        text = roadmap("05-roadmap.md")
        section = text.split("## What is next", 1)[1].split("\n## ", 1)[0]
        self.assertIn("browser-use-style", section)
        self.assertIn("running everyday Chrome over CDP", section)
        self.assertIn('Chrome\'s "Allow remote debugging?" consent once', section)
        self.assertIn("existing session: his own tabs and logins", section)
        self.assertIn("No extension, no separate profile, and no `--remote-debugging-port` relaunch", section)
        self.assertIn("harness/browser_local.py", section)
        self.assertIn("not the browser-use package, Playwright, or an extension", section)
        self.assertIn("Run one hosted model behind both OpenBot", section)
        self.assertIn("Try a second real ACP agent", section)
        self.assertIn("approvals should be removable per bot", section)
        self.assertNotIn("](", section)
        requirements = section.split("Requirements:", 1)[1].split("OpenCode Browse", 1)[0]
        for technique in TECHNIQUES:
            self.assertEqual(requirements.count(technique), 1, technique)
        self.assertEqual(section.count("anomalyco/browse"), 1)
        self.assertIn("OpenCode Browse (`anomalyco/browse`) is the fallback only, and it needs an extension.", section)
        self.assertNotIn(OLD_RELAUNCH, text)

    def test_live_chrome_has_one_benchmark_per_technique(self):
        text = roadmap("capability-iteration.md")
        self.assertIn("python -m harness.capability --scratch", text)
        section = text.split("## Live Chrome", 1)[1]
        self.assertIn("Run each check against the live Chrome", section)
        bullets = [line[2:] for line in section.splitlines() if line.startswith("- ")]
        self.assertEqual(bullets, list(TECHNIQUES))
        self.assertNotIn("anomalyco/browse", text)
        self.assertNotIn(OLD_RELAUNCH, text)
        self.assertNotIn("harness/benchmark.py", text)
