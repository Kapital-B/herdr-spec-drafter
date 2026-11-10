"""Small JSON state file: the Specs space id and every ticket ever launched."""

import json
import os
import tempfile
from pathlib import Path


class State:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {"space_id": None, "dispatcher_tab_id": None, "tickets": {}}
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text()))

    @property
    def tickets(self):
        return self.data["tickets"]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".state-")
        with os.fdopen(fd, "w") as f:
            json.dump(self.data, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)
