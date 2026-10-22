"""Container entry. Configuration is read-only and mounted by the operator."""

import json
import os
from pathlib import Path

from .api import create_app
from .contracts import DemoSettings

app = create_app(
    DemoSettings.model_validate(
        json.loads(
            Path(os.environ.get("DEMO_WEB_CONFIG", "/etc/demo/web.json")).read_text()
        )
    )
)
