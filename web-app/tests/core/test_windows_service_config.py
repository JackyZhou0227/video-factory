from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


CONFIG_PATH = Path(__file__).resolve().parents[2] / "scripts" / "VideoFactory.xml"


def test_windows_service_config_runs_production_server() -> None:
    root = ET.parse(CONFIG_PATH).getroot()

    assert root.findtext("id") == "VideoFactory"
    assert root.findtext("executable") == '"%BASE%\\..\\..\\.venv\\Scripts\\python.exe"'
    assert root.findtext("arguments") == "main.py"
    assert root.findtext("workingdirectory") == "%BASE%\\.."
    assert root.findtext("startmode") == "Automatic"
    assert root.find("delayedAutoStart") is not None
    assert root.findtext("stopparentprocessfirst") == "true"

    env = {item.attrib["name"]: item.attrib["value"] for item in root.findall("env")}
    assert env["VIDEO_FACTORY_ENV"] == "production"
    assert env["VIDEO_FACTORY_RELOAD"] == "0"
    assert env["VIDEO_FACTORY_HOST"] == "0.0.0.0"
    assert env["VIDEO_FACTORY_PORT"] == "18888"

    log = root.find("log")
    assert log is not None
    assert log.attrib["mode"] == "roll-by-size"
    assert [item.attrib["action"] for item in root.findall("onfailure")] == ["restart", "restart"]
