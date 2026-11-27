# hop-mcp — Apache Hop MCP Server

通过 [MCP](https://modelcontextprotocol.io) 让 AI 助手操作 Apache Hop：管理 pipeline / workflow 文件、用 `hop-run` 执行、查询 Hop Server，以及（配合 gui-remote 插件）直接控制正在运行的 Hop GUI。

- 一个 Hop 安装，多个项目：项目列表每次调用时从 `hop-config.json` 实时读取，在 Hop GUI 里新建项目后无需改配置
- 所有文件读写都限制在已注册的项目目录内

## 安装

```bash
cd hop-mcp
bash setup.sh          # 创建 .venv 并安装依赖（mcp<2、requests）
```

> `server.py` 基于 MCP Python SDK 1.x 的 `FastMCP`。2.x 中已改名为 `MCPServer`，所以依赖锁定为 `mcp[cli]<2`。

## 配置

复制 `mcp.json.example` 为 `mcp.json`，按本机路径修改后导入 MCP 客户端：

| 环境变量 | 必填 | 说明 |
|---|---|---|
| `HOP_HOME` | 是 | Hop 安装目录（包含 `hop-run.sh`） |
| `HOP_CONFIG_FOLDER` | 否 | Hop 配置目录，默认 `$HOP_HOME/config`。如果终端里设置过该变量，这里要填同一个值，否则读到的项目列表会和 GUI 不一致 |
| `HOP_WORKSPACE` | 否 | 额外的非项目目录，以项目名 `mcp` 访问 |
| `HOP_DEFAULT_PROJECT` | 否 | 不指定 `project` 时使用的项目 |
| `HOP_RUN_TIMEOUT` | 否 | `hop-run` 超时秒数，默认 1800 |
| `HOP_SERVER_URL` / `HOP_SERVER_USER` / `HOP_SERVER_PASSWORD` | 否 | Hop Server 地址和账号 |

## 工具

### 项目与文件
| 工具 | 作用 |
|---|---|
| `list_projects` | 列出 Hop 中注册的项目及目录 |
| `list_hop_files` | 列出项目下的 `.hpl` / `.hwf` |
| `read_hop_file` / `describe_hop_file` | 读取 XML / 解析参数、组件和连线 |
| `write_hop_file` | 校验 XML 后写入（默认不覆盖） |
| `read_output_file` | 读取项目目录内的 csv/txt/json 等输出文件 |

### 命令行执行
| 工具 | 作用 |
|---|---|
| `run_pipeline` / `run_workflow` | 调用 `hop-run`，自动带上 `-j 项目`，返回退出码和日志 |

### Hop Server
| 工具 | 作用 |
|---|---|
| `server_status` / `server_pipeline_status` / `server_workflow_status` / `server_stop_pipeline` | 查询或停止 Hop Server 上的任务 |

### Hop GUI 远程控制（需要 gui-remote 插件）
| 工具 | 作用 |
|---|---|
| `gui_status` | 当前项目、打开的标签和未保存状态 |
| `gui_open` / `gui_activate` | 打开文件 / 切换标签 |
| `gui_save` / `gui_reload` / `gui_close` | 保存 / 从磁盘重新加载 / 关闭 |
| `gui_run` | 在 GUI 中运行，默认跳过运行配置对话框；可传 `run_config`、`params`、`log_level`，`dialog=true` 时弹出原对话框 |
| `gui_stop` | 停止运行 |
| `gui_run_status` | 读取最近一次运行的状态、各组件读写行数和日志 |
| `gui_switch_project` | 切换 GUI 当前项目 |

## gui-remote 插件

GUI 控制工具依赖 Hop GUI 内的 gui-remote 插件（源码：[twelvejie/hop `gui-remote` 分支](https://github.com/twelvejie/hop/tree/gui-remote) 的 `plugins/misc/gui-remote`，基于 Hop 2.20.0）。

- 插件随 Hop GUI 启动，只监听 `127.0.0.1` 的随机端口，请求需要 Bearer token
- 端口和 token 写入 `~/.hop-gui-remote.json`（权限 600），GUI 退出时删除
- 设置 `HOP_GUI_REMOTE_ENABLED=false` 可关闭插件

编译后将 `hop-misc-gui-remote-2.20.0.jar` 放到 `$HOP_HOME/plugins/misc/gui-remote/`，重启 Hop GUI。

## 本地调试

```bash
HOP_HOME=/path/to/hop HOP_WORKSPACE=$PWD/pipelines ./.venv/bin/python server.py
# 或用 MCP Inspector
./.venv/bin/mcp dev server.py
```
