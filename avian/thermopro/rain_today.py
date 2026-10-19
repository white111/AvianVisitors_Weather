"""Turn a rain gauge's running total into "rain today".

La Crosse rain gauges (LTV-R1/R3) report the rain counted since their
batteries went in. This keeps, per sensor, the total at local midnight so the
badge can show today's rain. A drop in the total means the gauge restarted
(new batteries); today's rain so far is kept and counting carries on.
State is saved to a small JSON file so a receiver restart keeps the day.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Dict, Optional


class RainToday:
    def __init__(self, path: Optional[str]) -> None:
        self._path = path
        self._state: Dict[str, dict] = {}
        if path:
            try:
                with open(path, encoding='utf-8') as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    self._state = {k: v for k, v in data.items() if isinstance(v, dict)}
            except (OSError, ValueError):
                self._state = {}

    def update(self, key: str, total_mm: float, now: Optional[float] = None) -> float:
        """Record a new running total; return today's rain in mm."""
        day = time.strftime('%Y-%m-%d', time.localtime(now if now is not None else time.time()))
        entry = self._state.get(key)
        if entry is None or entry.get('day') != day:
            # First reading of the day (or ever): today starts here.
            entry = {'day': day, 'base': total_mm, 'last': total_mm}
        elif total_mm < entry['last']:
            # The gauge restarted; keep what fell today before the restart.
            entry['base'] = total_mm - (entry['last'] - entry['base'])
            entry['last'] = total_mm
        else:
            entry['last'] = total_mm
        self._state[key] = entry
        self._save()
        return round(max(0.0, entry['last'] - entry['base']), 2)

    def _save(self) -> None:
        if not self._path:
            return
        directory = os.path.dirname(self._path) or '.'
        try:
            fd, tmp = tempfile.mkstemp(prefix='.rain-', dir=directory)
            with os.fdopen(fd, 'w') as handle:
                json.dump(self._state, handle)
            os.replace(tmp, self._path)
        except OSError:
            pass
