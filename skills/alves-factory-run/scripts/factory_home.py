"""Where the factory keeps its config and run state, outside every project repo.

ALVES_FACTORY_HOME when set, else ~/.alves-factory. It holds projects.json, the optional
policy.json, policies/ and .env, and the runs/, triage/ and sweep/ work dirs.
"""

import os
from pathlib import Path

VARIABLE = "ALVES_FACTORY_HOME"


def factory_home(environ=os.environ):
    value = environ.get(VARIABLE, "").strip()
    return Path(value).expanduser() if value else Path.home() / ".alves-factory"
