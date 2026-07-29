"""
Parameter resolver.
Loads binding files from local folder, resolves ${TOKEN} in quad objects.
"""
import logging
import os
import re
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# Matches ${...} tokens — this is the analyzer's syntax, not app-specific
TOKEN_PATTERN = re.compile(r'\$\{([^}]+)\}')


class Resolver:
    def __init__(self, bindings_dir: str):
        self.bindings: dict[str, str] = {}
        self._load_all(bindings_dir)

    def _load_all(self, bindings_dir: str):
        """Load all .yaml/.yml files from the bindings directory."""
        if not bindings_dir:
            # An unset/empty source means "no bindings" — never fall back to
            # globbing the current working directory.
            logger.info("No bindings source configured — tokens will stay as ${...}")
            return
        folder = Path(bindings_dir)
        if not folder.exists():
            logger.info(f"No bindings directory at {bindings_dir} — skipping resolution")
            return

        files = list(folder.glob("*.yaml")) + list(folder.glob("*.yml"))
        if not files:
            logger.info(f"No binding files found in {bindings_dir}")
            return

        for f in sorted(files):
            try:
                with open(f) as fh:
                    data = yaml.safe_load(fh)
            except Exception as e:
                logger.warning(f"  Failed to load {f.name}: {e}")
                continue
            valid, skipped = self._validate(data)
            if not valid:
                logger.warning(
                    f"  {f.name} is not a bindings file (expected a flat "
                    f"placeholder -> value map) — skipped")
                continue
            if skipped:
                logger.warning(f"  {f.name}: skipped {skipped} non-scalar entr"
                               f"{'y' if skipped == 1 else 'ies'}")
            self.bindings.update(valid)
            logger.info(f"  Loaded {len(valid)} bindings from {f.name}")

        logger.info(f"  Total bindings loaded: {len(self.bindings)}")

    @staticmethod
    def _validate(data) -> tuple[dict[str, str], int]:
        """A binding is placeholder -> scalar value. Anything else (nested maps,
        lists — e.g. a quad file dropped in the wrong folder) is rejected, never
        half-loaded into the resolver."""
        if not isinstance(data, dict):
            return {}, 0
        valid: dict[str, str] = {}
        skipped = 0
        for key, value in data.items():
            if isinstance(key, str) and isinstance(value, (str, int, float, bool)):
                valid[key] = str(value)
            else:
                skipped += 1
        return valid, skipped

    def resolve(self, value: str) -> tuple[str, bool]:
        """
        Resolve ${TOKEN} patterns in a string.

        Returns:
            (resolved_string, was_resolved)
            - If all tokens were resolved: ("real_name", True)
            - If some tokens remain: ("partially_resolved", False)
            - If no tokens existed: ("original", True)
        """
        if "${" not in value:
            return value, True

        if not self.bindings:
            return value, False

        def replace_token(match):
            token = match.group(1)
            return self.bindings.get(token, match.group(0))

        resolved = TOKEN_PATTERN.sub(replace_token, value)
        fully_resolved = "${" not in resolved

        return resolved, fully_resolved

    def merged(self, extra: dict) -> "Resolver":
        """A new resolver combining ``extra`` (e.g. the quad file's own repo-declared
        bindings) with this one's. THIS resolver's entries win on conflict — the
        human worksheet beats a repo file (doc 10's trust ladder)."""
        out = Resolver("")
        valid, _ = self._validate(extra or {})
        out.bindings = {**valid, **self.bindings}
        return out

    @property
    def has_bindings(self) -> bool:
        return len(self.bindings) > 0

    @property
    def binding_count(self) -> int:
        return len(self.bindings)
