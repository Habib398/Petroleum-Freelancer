"""Shared test reporter — produces consistent PASS/FAIL output across every block.

Each test block script creates a :class:`TestReporter`, calls :meth:`check`
after each assertion, optionally opens new :meth:`section` groups, then calls
:meth:`summary` at the end and uses its return value as the process exit code.

The output is intentionally plain-text (no fancy colors) so it works in CMD,
PowerShell and CI logs alike. Sections appear as ``[N] Title`` headers; each
check is indented with ``OK`` or ``FAIL`` markers.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

# Force UTF-8 on stdout/stderr so Spanish accents and arrows render correctly
# on Windows CMD/PowerShell (default cp1252 chokes on '→', 'ñ', 'á', etc.).
# Guarded with hasattr because reconfigure exists from Python 3.7 onwards.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


@dataclass
class TestReporter:
    block_name: str
    _passed: list[str] = field(default_factory=list)
    _failed: list[tuple[str, str]] = field(default_factory=list)
    _section_index: int = 0

    def section(self, title: str) -> None:
        """Open a new section group. Call once per logical group of checks."""
        self._section_index += 1
        print(f"\n[{self._section_index}] {title}")

    def check(self, label: str, condition: bool, detail: str = "") -> bool:
        """Record one assertion. Returns ``condition`` so callers can branch.

        Failures get queued for the summary; passing checks just print and
        continue. ``detail`` is shown only on failure (keeps output tight).
        """
        if condition:
            self._passed.append(label)
            print(f"  OK    {label}")
            return True
        self._failed.append((label, detail))
        print(f"  FAIL  {label}")
        if detail:
            print(f"        {detail}")
        return False

    @property
    def failed_count(self) -> int:
        return len(self._failed)

    @property
    def total_count(self) -> int:
        return len(self._passed) + len(self._failed)

    def summary(self) -> int:
        """Print the per-block summary. Returns ``0`` for clean run, ``1`` otherwise.

        Callers should ``sys.exit(reporter.summary())`` so the block script
        propagates the result to the shell / run_all wrapper.
        """
        total = self.total_count
        print()
        print("=" * 64)
        print(f"Bloque: {self.block_name}")
        print(f"Verificaciones: {len(self._passed)}/{total} OK")
        if self._failed:
            print(f"Fallidas: {len(self._failed)}")
            for label, detail in self._failed:
                print(f"  - {label}")
                if detail:
                    print(f"    {detail}")
            print("RESULTADO: FALLA")
            print("=" * 64)
            return 1
        print("RESULTADO: TODO OK")
        print("=" * 64)
        return 0
