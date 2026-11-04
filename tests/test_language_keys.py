"""The panels' wording is in resources/languages/en.json, and every place that asks for a text asks for one that is there.

Run: python -m unittest discover -s tests -t .
"""

import html
import json
import re
import unittest
from pathlib import Path

from src.core.i18n import placeholders

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "src" / "ui" / "web"
LANGUAGES = ROOT / "resources" / "languages"

HTML_KEY = re.compile(r'data-i18n(?:-html)?="([^"]+)"')
ATTR_KEYS = re.compile(r'data-i18n-attr="([^"]+)"')
JS_KEY = re.compile(r"""\b(?:i18n\.t|t|text)\(\s*['"]([a-z0-9_]+(?:\.[a-z0-9_]+)+)['"]""")
PY_KEY = re.compile(r"""\bt\(\s*['"]([a-z0-9_]+(?:\.[a-z0-9_]+)+)['"]""")   # t("key", name=value) from core.i18n
TEXT_ELEMENT = re.compile(r'<(\w+)\b[^>]*\sdata-i18n="([^"]+)"[^>]*>([^<]*)</\1>')   # an element that holds text only


def english():
    return json.loads((LANGUAGES / "en.json").read_text(encoding="utf-8"))["strings"]


def web_files(pattern):
    return sorted(path for path in WEB.rglob(pattern) if path.is_file())


def keys_asked_for():
    """{key: [file, ...]} for every text a page's HTML or scripts ask for."""
    asked = {}
    for path in web_files("*.html"):
        source = path.read_text(encoding="utf-8")
        found = HTML_KEY.findall(source)
        for pairs in ATTR_KEYS.findall(source):
            found += [pair.split(":", 1)[1].strip() for pair in pairs.split(";") if ":" in pair]
        for key in found:
            asked.setdefault(key, []).append(path.name)
    for path in web_files("*.js"):
        for key in JS_KEY.findall(path.read_text(encoding="utf-8")):
            asked.setdefault(key, []).append(path.name)
    for path in sorted((ROOT / "src").rglob("*.py")):
        for key in PY_KEY.findall(path.read_text(encoding="utf-8")):
            asked.setdefault(key, []).append(path.name)
    return asked


class EnglishFileTests(unittest.TestCase):
    def test_every_text_a_page_asks_for_is_in_english(self):
        strings = english()
        missing = {key: files for key, files in keys_asked_for().items() if key not in strings}
        self.assertEqual(missing, {}, "These texts are asked for but are not in resources/languages/en.json")

    def test_english_has_no_text_nothing_asks_for(self):
        asked = keys_asked_for()
        python_source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src").rglob("*.py"))
        unused = [key for key in english() if key not in asked and f'"{key}"' not in python_source]
        self.assertEqual(unused, [], "These texts in en.json are not used anywhere")

    def test_the_english_a_page_shows_before_the_language_arrives_is_the_text_in_en_json(self):
        strings, wrong = english(), []
        for path in web_files("*.html"):
            for _tag, key, inline in TEXT_ELEMENT.findall(path.read_text(encoding="utf-8")):
                if key in strings and " ".join(html.unescape(inline).split()) != " ".join(strings[key].split()):
                    wrong.append(f"{path.name}: {key}: {inline.strip()!r} is not {strings[key]!r}")
        self.assertEqual(wrong, [])


class OtherLanguageFileTests(unittest.TestCase):
    def test_a_shipped_language_has_only_keys_english_has_with_the_same_placeholders(self):
        strings = english()
        for path in sorted(LANGUAGES.glob("*.json")):
            if path.stem == "en":
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(data.get("language"), path.name)
            for key, text in data["strings"].items():
                self.assertIn(key, strings, f"{path.name}: {key}")
                self.assertEqual(placeholders(text), placeholders(strings[key]), f"{path.name}: {key}")


if __name__ == "__main__":
    unittest.main()
