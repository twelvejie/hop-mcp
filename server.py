"""
Apache Hop MCP Server（单个 Hop，多个项目）
-------------------------------------------
项目自动从 $HOP_HOME/config/hop-config.json 的 projectsConfig 读取，
在 Hop GUI 新建项目后无需改配置即可访问。

环境变量：
  HOP_HOME            Hop 安装目录（含 hop-run.sh），必填
  HOP_WORKSPACE       额外的非项目目录（可选），以项目名 "mcp" 访问
  HOP_DEFAULT_PROJECT 未指定 project 时使用的项目（默认：有 mcp 用 mcp，否则 Hop 的 defaultProject）
  HOP_CONFIG_FOLDER   Hop 配置目录（默认 $HOP_HOME/config）
  HOP_RUN_TIMEOUT     执行超时秒数，默认 1800
  HOP_SERVER_URL / HOP_SERVER_USER / HOP_SERVER_PASSWORD  Hop Server（可选）
"""

import json
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from mcp.server.fastmcp import FastMCP

HOP_HOME = Path(os.environ.get("HOP_HOME", "")).expanduser().resolve()
CONFIG_DIR = Path(os.environ.get("HOP_CONFIG_FOLDER", HOP_HOME / "config")).expanduser()
EXTRA_ROOT = os.environ.get("HOP_WORKSPACE")
DEFAULT_PROJECT = os.environ.get("HOP_DEFAULT_PROJECT", "")
RUN_TIMEOUT = int(os.environ.get("HOP_RUN_TIMEOUT", "1800"))
SERVER_URL = os.environ.get("HOP_SERVER_URL", "").rstrip("/")
SERVER_AUTH = (
    os.environ.get("HOP_SERVER_USER", "cluster"),
    os.environ.get("HOP_SERVER_PASSWORD", "cluster"),
)
MAX_LOG_CHARS = 20000
MAX_READ_CHARS = 200000
READABLE_EXT = (".csv", ".txt", ".json", ".log", ".xml", ".yaml", ".yml", ".tsv")

mcp = FastMCP("apache-hop")


# ---------------- 项目 ----------------
def _hop_config() -> dict:
    f = CONFIG_DIR / "hop-config.json"
    return json.loads(f.read_text(encoding="utf-8")).get("projectsConfig", {}) if f.exists() else {}


def _projects() -> dict:
    """{项目名: {"home": Path, "is_project": bool}}，每次调用实时读取。"""
    result = {}
    for p in _hop_config().get("projectConfigurations", []):
        raw = p["projectHome"].replace("${HOP_HOME}", str(HOP_HOME))
        ph = Path(os.path.expandvars(raw)).expanduser()
        if not ph.is_absolute():
            ph = HOP_HOME / ph
        result[p["projectName"]] = {"home": ph.resolve(), "is_project": True}
    if EXTRA_ROOT:
        result.setdefault("mcp", {"home": Path(EXTRA_ROOT).expanduser().resolve(), "is_project": False})
    return result


def _project(name: str) -> tuple[str, dict]:
    projs = _projects()
    if not name:
        name = DEFAULT_PROJECT or ("mcp" if "mcp" in projs else _hop_config().get("defaultProject", ""))
    if name not in projs:
        raise ValueError(f"未知项目: {name}，可选: {list(projs)}")
    return name, projs[name]


def _resolve(project: str, rel: str) -> tuple[str, dict, Path]:
    name, p = _project(project)
    root = p["home"]
    path = (root / rel).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"路径超出项目目录: {rel}")
    return name, p, path


def _tail(text: str) -> str:
    return text if len(text) <= MAX_LOG_CHARS else "...(截断)...\n" + text[-MAX_LOG_CHARS:]


@mcp.tool()
def list_projects() -> list[dict]:
    """列出 Hop 中注册的所有项目（以及额外目录 mcp），含目录和是否存在。"""
    default, _ = _project("")
    return [
        {
            "name": n,
            "home": str(p["home"]),
            "is_hop_project": p["is_project"],
            "exists": p["home"].exists(),
            "default": n == default,
        }
        for n, p in _projects().items()
    ]


# ---------------- 文件 ----------------
@mcp.tool()
def list_hop_files(project: str = "", subdir: str = "") -> list[str]:
    """列出项目下所有 .hpl / .hwf（相对项目目录）。project 为空用默认项目。"""
    _, p, base = _resolve(project, subdir)
    root = p["home"]
    return sorted(
        str(f.relative_to(root))
        for ext in ("*.hpl", "*.hwf")
        for f in base.rglob(ext)
        if ".git" not in f.parts
    )


@mcp.tool()
def read_hop_file(file: str, project: str = "") -> str:
    """读取 .hpl / .hwf 的 XML。"""
    return _resolve(project, file)[2].read_text(encoding="utf-8")


@mcp.tool()
def describe_hop_file(file: str, project: str = "") -> dict:
    """解析 pipeline/workflow：名称、参数、transform/action 列表、连线。"""
    root = ET.parse(_resolve(project, file)[2]).getroot()
    info = root.find("info")
    params = [
        {"name": x.findtext("name"), "default": x.findtext("default_value"), "description": x.findtext("description")}
        for x in (info.findall("parameters/parameter") if info is not None else [])
    ]
    if root.tag == "pipeline":
        nodes = [{"name": t.findtext("name"), "type": t.findtext("type")} for t in root.findall("transform")]
        hops = root.findall("order/hop")
    else:
        nodes = [{"name": a.findtext("name"), "type": a.findtext("type")} for a in root.findall("actions/action")]
        hops = root.findall("hops/hop")
    return {
        "kind": root.tag,
        "name": info.findtext("name") if info is not None else None,
        "parameters": params,
        "nodes": nodes,
        "hops": [{"from": x.findtext("from"), "to": x.findtext("to"), "enabled": x.findtext("enabled")} for x in hops],
    }


@mcp.tool()
def write_hop_file(file: str, xml_content: str, project: str = "", overwrite: bool = False) -> str:
    """写入 .hpl / .hwf（XML 校验后写入，默认不覆盖）。"""
    if not file.endswith((".hpl", ".hwf")):
        raise ValueError("只能写 .hpl 或 .hwf 文件")
    root = ET.fromstring(xml_content)
    if root.tag not in ("pipeline", "workflow"):
        raise ValueError(f"根节点应为 pipeline 或 workflow，实际是 {root.tag}")
    path = _resolve(project, file)[2]
    if path.exists() and not overwrite:
        raise FileExistsError(f"{file} 已存在，如需覆盖请设置 overwrite=true")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml_content, encoding="utf-8")
    return f"已写入 {path}"


@mcp.tool()
def read_output_file(file: str, project: str = "", max_chars: int = 20000) -> str:
    """读取项目目录内的文本输出（csv/txt/json/log/xml/yaml/tsv），用于查看运行结果。"""
    path = _resolve(project, file)[2]
    if path.suffix.lower() not in READABLE_EXT:
        raise ValueError(f"只允许读取: {READABLE_EXT}")
    text = path.read_text(encoding="utf-8", errors="replace")
    n = min(max_chars, MAX_READ_CHARS)
    return text if len(text) <= n else text[:n] + f"\n...(截断，共 {len(text)} 字符)"


# ---------------- 执行 ----------------
def _run(file, project, params, environment, run_config, level) -> dict:
    name, p, path = _resolve(project, file)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {file}")
    exe = HOP_HOME / ("hop-run.bat" if os.name == "nt" else "hop-run.sh")
    if not exe.exists():
        raise FileNotFoundError(f"找不到 {exe}，请检查 HOP_HOME")
    cmd = [str(exe), "-f", str(path), "-r", run_config, "-l", level]
    if p["is_project"]:
        cmd += ["-j", name]
    if environment:
        cmd += ["-e", environment]
    for k, v in (params or {}).items():
        cmd += ["-p", f"{k}={v}"]
    try:
        r = subprocess.run(cmd, cwd=str(HOP_HOME), capture_output=True, text=True, timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"执行超时（{RUN_TIMEOUT}s）"}
    return {
        "success": r.returncode == 0,
        "exit_code": r.returncode,
        "project": name,
        "command": " ".join(cmd),
        "log": _tail(r.stdout + ("\n[stderr]\n" + r.stderr if r.stderr else "")),
    }


@mcp.tool()
def run_pipeline(
    file: str,
    project: str = "",
    params: dict[str, str] | None = None,
    environment: str = "",
    run_config: str = "local",
    log_level: str = "Basic",
) -> dict:
    """用 hop-run 执行 .hpl。project 为空用默认项目；params 如 {"INPUT_FILE": "/a.xlsx"}。
    log_level: Nothing/Error/Minimal/Basic/Detailed/Debug/Rowlevel"""
    return _run(file, project, params, environment, run_config, log_level)


@mcp.tool()
def run_workflow(
    file: str,
    project: str = "",
    params: dict[str, str] | None = None,
    environment: str = "",
    run_config: str = "local",
    log_level: str = "Basic",
) -> dict:
    """用 hop-run 执行 .hwf workflow。"""
    return _run(file, project, params, environment, run_config, log_level)


# ---------------- Hop Server ----------------
def _server_get(path: str, **params) -> str:
    if not SERVER_URL:
        raise RuntimeError("未配置 HOP_SERVER_URL")
    r = requests.get(f"{SERVER_URL}{path}", params=params, auth=SERVER_AUTH, timeout=30)
    r.raise_for_status()
    return r.text


@mcp.tool()
def server_status() -> str:
    """查询 Hop Server 整体状态（XML）。"""
    return _server_get("/hop/status/", xml="Y")


@mcp.tool()
def server_pipeline_status(name: str, id: str = "", from_log_line: int = 0) -> str:
    """查询 Hop Server 上某 pipeline 的状态与日志（XML）。"""
    return _server_get("/hop/pipelineStatus/", name=name, id=id, xml="Y", **{"from": from_log_line})


@mcp.tool()
def server_workflow_status(name: str, id: str = "", from_log_line: int = 0) -> str:
    """查询 Hop Server 上某 workflow 的状态与日志（XML）。"""
    return _server_get("/hop/workflowStatus/", name=name, id=id, xml="Y", **{"from": from_log_line})


@mcp.tool()
def server_stop_pipeline(name: str, id: str = "") -> str:
    """停止 Hop Server 上运行中的 pipeline。"""
    return _server_get("/hop/stopPipeline/", name=name, id=id, xml="Y")


# ---------------- Hop GUI 远程控制（需安装 hop-misc-gui-remote 插件） ----------------
GUI_INFO_FILE = Path.home() / ".hop-gui-remote.json"


def _gui(endpoint: str, payload: dict | None = None) -> dict:
    if not GUI_INFO_FILE.exists():
        raise RuntimeError("未发现运行中的 Hop GUI（缺少 ~/.hop-gui-remote.json），请先启动 Hop GUI 并安装 gui-remote 插件")
    info = json.loads(GUI_INFO_FILE.read_text(encoding="utf-8"))
    try:
        r = requests.post(
            info["url"] + endpoint,
            json=payload or {},
            headers={"Authorization": f"Bearer {info['token']}"},
            timeout=40,
        )
    except requests.ConnectionError:
        raise RuntimeError("连接 Hop GUI 失败，GUI 可能已关闭或重启，请确认 Hop GUI 正在运行")
    try:
        return r.json()
    except ValueError:
        return {"ok": False, "status": r.status_code, "error": r.text[:500]}


@mcp.tool()
def gui_status() -> dict:
    """Hop GUI 当前状态：项目、环境、活动标签、所有打开的标签及是否有未保存修改。"""
    return _gui("/status")


@mcp.tool()
def gui_open(file: str) -> dict:
    """在 Hop GUI 中打开 .hpl/.hwf（绝对路径，或相对 GUI 当前项目目录）；已打开则切换过去。"""
    return _gui("/open", {"file": file})


@mcp.tool()
def gui_activate(file: str) -> dict:
    """切换到 GUI 中已打开的某个标签。"""
    return _gui("/activate", {"file": file})


@mcp.tool()
def gui_save(file: str = "") -> dict:
    """保存 GUI 中的文件（缺省为当前标签）。"""
    return _gui("/save", {"file": file})


@mcp.tool()
def gui_reload(file: str = "") -> dict:
    """让 GUI 从磁盘重新加载文件（用 write_hop_file 改完后调用）。"""
    return _gui("/reload", {"file": file})


@mcp.tool()
def gui_close(file: str = "", force: bool = False) -> dict:
    """关闭 GUI 标签。有未保存修改时默认拒绝；force=true 会丢弃修改。"""
    return _gui("/close", {"file": file, "force": force})


@mcp.tool()
def gui_run(
    file: str = "",
    run_config: str = "local",
    params: dict[str, str] | None = None,
    log_level: str = "Basic",
    dialog: bool = False,
) -> dict:
    """在 GUI 中运行 pipeline/workflow，日志与指标显示在 GUI 中。
    默认跳过运行配置对话框，直接用 run_config（默认 local）启动；params 为参数值；
    dialog=true 时改为弹出原来的运行对话框，由用户在 GUI 里确认。运行后用 gui_run_status 查看结果。"""
    return _gui(
        "/run",
        {"file": file, "run_config": run_config, "params": params or {}, "log_level": log_level, "dialog": dialog},
    )


@mcp.tool()
def gui_stop(file: str = "") -> dict:
    """停止 GUI 中正在运行的 pipeline/workflow。"""
    return _gui("/stop", {"file": file})


@mcp.tool()
def gui_run_status(file: str = "", log_lines: int = 200) -> dict:
    """读取 GUI 中最近一次运行的结果：状态(running/finished/finished_with_errors/stopped/never_run)、
    错误数、各组件读/写/输入/输出/拒绝行数与耗时（pipeline），以及日志尾部 log_lines 行。
    file 缺省为当前标签。"""
    return _gui("/run-status", {"file": file, "log_lines": log_lines})


@mcp.tool()
def gui_switch_project(name: str) -> dict:
    """切换 Hop GUI 的当前项目。"""
    return _gui("/project", {"name": name})


if __name__ == "__main__":
    mcp.run()
