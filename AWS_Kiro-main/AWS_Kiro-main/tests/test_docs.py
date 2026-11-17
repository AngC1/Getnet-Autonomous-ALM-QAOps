"""Smoke tests de documentación: Agent.md y TEAM.md (tarea 11.3; Req. 11.1, 12.x, 10.5)."""
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "Agent.md"
TEAM = ROOT / "TEAM.md"
REQS = ROOT / ".kiro" / "specs" / "atm-card-incident-video-simulation" / "requirements.md"

SECTIONS = [
    "Contexto",
    "Requisitos",
    "Arquitectura",
    "Flujo del agente",
    "Esquemas de datos",
    "Gestión de secretos",
    "Plan de demo",
    "Criterios de aceptación",
]
OUTPUTS = [
    "AgentUrl", "AgentTokenSecret", "CanvasUrl", "AudienceDataURI", "HackathonAssetsBucketName",
    "MediaToolkitIngestBucket", "MediaToolkitRegion", "MediaToolkitStackName", "TestVideosURI",
]
WEB_VARS = ["REDIS_URL", "MEDIA_BUCKET", "PORT", "MEDIA_DIR"]


def _load_scan_text():
    spec = importlib.util.spec_from_file_location("check_secrets", ROOT / "scripts" / "check_secrets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.scan_text


def _sections(text, level_prefix):
    """Divide en {titulo: cuerpo} por encabezados exactos de ese nivel, ignorando bloques de código."""
    result, current, in_fence = {}, None, False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith(level_prefix + " "):
            current = line[len(level_prefix) + 1:].strip()
            result[current] = []
            continue
        if current is not None:
            result[current].append(line)
    return {k: "\n".join(v) for k, v in result.items()}


def _parse_requirements():
    """[(numero, titulo, [criterios])] de requirements.md."""
    reqs, cur = [], None
    for line in REQS.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^### Requirement (\d+): (.+?)\s*$", line)
        if m:
            cur = (int(m.group(1)), m.group(2), [])
            reqs.append(cur)
            continue
        c = re.match(r"^\d+\. (.+?)\s*$", line)
        if c and cur is not None:
            cur[2].append(c.group(1))
    return reqs


@pytest.fixture(scope="module")
def agent_text():
    assert AGENT.is_file(), "falta Agent.md"
    return AGENT.read_text(encoding="utf-8")


def test_agent_max_lines(agent_text):
    assert len(agent_text.splitlines()) <= 1000


def test_agent_eight_sections_in_order_non_empty(agent_text):
    secs = _sections(agent_text, "##")
    assert list(secs) == SECTIONS
    for name, body in secs.items():
        assert body.strip(), "sección vacía: %s" % name


def test_agent_contains_all_requirements(agent_text):
    reqs = _parse_requirements()
    assert [r[0] for r in reqs] == list(range(1, 14))
    body = _sections(agent_text, "##")["Requisitos"]
    for num, title, criteria in reqs:
        assert re.search(r"^#{3,} .*Requirement %d: %s\s*$" % (num, re.escape(title)), body, re.M), \
            "falta Requirement %d: %s" % (num, title)
        assert criteria, "requirements.md sin criterios en el requisito %d" % num
        for crit in criteria:
            assert crit in body, "falta un criterio del requisito %d: %s" % (num, crit[:60])


def test_agent_event_outputs_and_connect(agent_text):
    for name in OUTPUTS:
        lines = [l for l in agent_text.splitlines() if l.startswith("- `%s`" % name)]
        assert lines, "falta la línea de uso de %s" % name
    assert "bash media-toolkit/connect.sh" in agent_text


def test_agent_web_and_env_vars(agent_text):
    for needle in ["Web_Visor", "API_Visor", "Almacen_Redis", "React", "Vite", "Express",
                   "web/run.sh start|stop|status"]:
        assert needle in agent_text, needle
    for var in WEB_VARS:
        assert var in agent_text, var


def test_agent_cli_and_references(agent_text):
    for needle in ["python3 -m brand_verifier run", "python3 -m brand_verifier validate",
                   "python3 -m brand_verifier incident", "assets/brand/", "brand/reference/",
                   "Verificador_Marca", "CanvasUrl", "AgentUrl"]:
        assert needle in agent_text, needle


def test_team_sections_word_counts():
    text = TEAM.read_text(encoding="utf-8")
    block = _sections(text, "##")["Before you build"]
    items = re.split(r"(?m)^(?=\d+\. )", block)
    items = [i.strip() for i in items if re.match(r"\d+\. ", i.strip())]
    assert len(items) == 5
    for item in items:
        words = len(re.sub(r"^\d+\.\s*\*\*[^*]+\*\*", "", item).split())
        assert 1 <= words <= 150, item[:40]


@pytest.mark.parametrize("path", [AGENT, TEAM], ids=lambda p: p.name)
def test_docs_pass_secret_scanner(path):
    scan_text = _load_scan_text()
    assert scan_text(path.read_text(encoding="utf-8"), str(path)) == []
