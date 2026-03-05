from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    canonical = Path(__file__).with_name("vm_config_to_azure_instance.py")
    runpy.run_path(str(canonical), run_name="__main__")
