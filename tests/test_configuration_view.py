"""The configuration index on the Info page.

Two properties, and the second is the one that rots:

* **The description is the file's own comment.** It is read from `config/config.yaml` at
  render time rather than restated in code, so the page and the file cannot drift. That is
  the whole reason the parser exists, and it is asserted against a real comment.
* **The index stays complete.** Every key listed resolves to a value and has a comment
  explaining it. A renamed key would otherwise vanish from the page silently -- the value
  resolves to `None` and the row is skipped -- and an uncommented one renders an empty cell.
"""

from __future__ import annotations

from pathlib import Path

from awltux.web import configuration


class TestReadingTheFilesOwnComments:
    def test_a_comment_above_a_key_describes_it(self, tmp_path: Path):
        path = tmp_path / "config.yaml"
        path.write_text(
            "app:\n  # The zone timestamps are shown in.\n  timezone: Europe/London\n",
            encoding="utf-8",
        )

        assert configuration.annotations(path)["app.timezone"] == (
            "The zone timestamps are shown in."
        )

    def test_a_comment_above_a_section_describes_the_section(self, tmp_path: Path):
        """And is not inherited by the keys inside it, which have their own."""
        path = tmp_path / "config.yaml"
        path.write_text("# About the section.\napp:\n  timezone: Europe/London\n", encoding="utf-8")

        found = configuration.annotations(path)

        assert found["app"] == "About the section."
        assert "app.timezone" not in found

    def test_a_nested_key_is_named_by_its_whole_path(self, tmp_path: Path):
        """Two sections can hold a key of the same name, and the page lists both."""
        path = tmp_path / "config.yaml"
        path.write_text(
            "# Outer.\nllm:\n  # Inner.\n  model: a\nnews:\n  # The other one.\n  model: b\n",
            encoding="utf-8",
        )

        found = configuration.annotations(path)

        assert found["llm.model"] == "Inner."
        assert found["news.model"] == "The other one."

    def test_a_comment_beside_the_value_is_used_when_there_is_no_block(self, tmp_path: Path):
        """Which is where the schedule section keeps its reasons."""
        path = tmp_path / "config.yaml"
        path.write_text(
            "schedule:\n  prices_eod: 86400   # once after the close\n",
            encoding="utf-8",
        )

        assert configuration.annotations(path)["schedule.prices_eod"] == "once after the close"

    def test_a_block_wins_over_the_comment_beside_the_value(self, tmp_path: Path):
        path = tmp_path / "config.yaml"
        path.write_text(
            "# The block is the description.\nkey: 1  # not this one\n",
            encoding="utf-8",
        )

        assert configuration.annotations(path)["key"] == "The block is the description."

    def test_a_blank_line_ends_the_block(self, tmp_path: Path):
        """The rule a reader applies by eye: a comment separated from its key is not about it."""
        path = tmp_path / "config.yaml"
        path.write_text("# Something else entirely.\n\nkey: 1\n", encoding="utf-8")

        assert "key" not in configuration.annotations(path)

    def test_an_empty_comment_line_does_not_end_the_block(self, tmp_path: Path):
        """`#` on its own is how the file separates paragraphs inside one explanation."""
        path = tmp_path / "config.yaml"
        path.write_text("# First.\n#\n# Second.\nkey: 1\n", encoding="utf-8")

        assert configuration.annotations(path)["key"] == "First. Second."


class TestTheIndex:
    def test_every_listed_key_resolves(self, settings):
        """A renamed setting would otherwise drop off the page without a word: the row is
        skipped when the value is absent, which is silent by construction."""
        resolved = {row.name for row in configuration.rows(settings)}

        assert resolved == {path for path, _ in configuration.INTERESTING}

    def test_every_listed_key_has_a_description(self, settings):
        """The page says "the description is the file's own comment", so a listed key the
        file does not explain is an empty column on a page that promised one."""
        described = configuration.annotations(settings.env.config_file)

        assert [path for path, _ in configuration.INTERESTING if path not in described] == []

    def test_a_duration_is_shown_as_the_schedule_it_is(self, settings):
        """`604800` tells a reader nothing; `7d` is the interval they think in."""
        rows = {row.name: row.value for row in configuration.rows(settings)}

        assert rows["schedule.valuation"] == "1d"
        assert rows["schedule.held_refresh"] == "1h"
        assert rows["schedule.retention"] == "7d"

    def test_the_value_is_the_running_processs_not_the_files(self, settings):
        """This is the distinction that mattered for the budget: `config.py`'s default was
        raised and changed nothing, because the YAML value is the one in use."""
        settings.yaml.llm.monthly_budget_usd = 123.5

        rows = {row.name: row.value for row in configuration.rows(settings)}

        assert rows["llm.monthly_budget_usd"] == "123.5"

    def test_a_long_comment_is_trimmed_to_a_cell(self, settings):
        """Some of them are the record of a measurement and run to dozens of lines. The table
        is an index; the file is where the whole argument is."""
        rows = {row.name: row.description for row in configuration.rows(settings)}

        trimmed = rows["news.embeddings.same_event_threshold"]

        assert trimmed.endswith("…")
        assert len(trimmed) <= configuration.DESCRIPTION_CHARS + 1


class TestRenderingAValue:
    def test_a_number_is_grouped(self):
        assert configuration._render(28000, "number") == "28,000"

    def test_a_fraction_is_shown_as_a_percentage(self):
        assert configuration._render(0.055, "percent") == "5.5%"

    def test_a_boolean_is_a_word(self):
        assert configuration._render(True, "bool") == "yes"
        assert configuration._render(False, "bool") == "no"

    def test_an_empty_list_is_an_absence_rather_than_nothing(self):
        assert configuration._render([], "list") == "—"

    def test_an_absent_value_is_a_dash_and_never_a_zero(self):
        """The codebase's rule: an unknown renders as a visible placeholder, because `0`
        and `off` are both things a setting can legitimately be."""
        assert configuration._render(None, "text") == "—"
        assert configuration._render(None, "number") == "—"
