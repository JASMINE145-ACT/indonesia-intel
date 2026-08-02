# WorkBuddy 配置指南（朋友上手）

把 GitHub 地址发给 WorkBuddy **不够**。本插件是 **本机 MCP 服务**，需要先 clone、装依赖、配密钥，再在 WorkBuddy 里挂 MCP，并贴上行为手册。

仓库：https://github.com/JASMINE145-ACT/indonesia-intel

---

## 你要完成的 4 步

### 1) Clone + 安装

```bat
git clone https://github.com/JASMINE145-ACT/indonesia-intel.git
cd indonesia-intel
copy .env.example .env
python -m pip install -e ".[dev]"
```

要求：本机已装 **Python 3.11+**，且 `python` 在 PATH 里。

### 2) 编辑 `.env`（最少配置）

打开仓库根目录的 `.env`：

| 变量 | 要不要 | 说明 |
|------|--------|------|
| `API_KEY` | 建议保留默认 | 看板/HTTP 用；默认 `dev-local-key` |
| `EXA_API_KEY` | **强烈建议** | 广搜通道之一 |
| `TAVILY_API_KEY` | **强烈建议** | 广搜通道之一（与 Exa 二选一或都配） |
| `DATABASE_URL` / `BLOB_ROOT` | 可不动 | 默认本地 SQLite + `./data/blobs` |

两个搜索 Key **都空**时，搜索会落到 mock，看不到真实印尼资讯。

可选（默认关，不配也能用主流程）：

- `INTEL_REACH_ENABLED=1` + `YOUTUBE_API_KEY` — 社交 Reach
- `INTEL_FETCH_JINA_FALLBACK=1` + `JINA_API_KEY` — Jina 兜底抓取
- `PROXY_URL` — 部分官方站需要代理时

### 3) 在 WorkBuddy 挂 MCP

在 WorkBuddy 的 MCP / `mcp.json` 里加入（**把 `cwd` 改成你本机 clone 路径**）：

```json
{
  "mcpServers": {
    "indonesia-intel": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "cwd": "C:\\Users\\你的用户名\\indonesia-intel"
    }
  }
}
```

注意：

- `cwd` 必须是**本机目录**，不能写成 GitHub URL。
- 改完后**重启 WorkBuddy**（或重载 MCP）。
- 成功标志：工具列表里出现 `intel_search` / `intel_list` / `intel_confirm` 等。

冒烟（可选）：

```bat
cd /d C:\Users\你的用户名\indonesia-intel
python -m mcp_server
```

能启动、不立刻报错即可（MCP 由宿主拉起时一般不用你手动常驻）。

### 4) 把「怎么用」告诉 WorkBuddy（必做）

MCP 只提供工具能力，**不含审核红线与六环顺序**。

请把仓库里的整份手册贴进 WorkBuddy **系统提示 / Agent 说明 / 项目说明**：

- 文件：`docs/agent_playbook.md`
- 在线：https://github.com/JASMINE145-ACT/indonesia-intel/blob/main/docs/agent_playbook.md

也可以对 WorkBuddy 说：

> 请严格按 `docs/agent_playbook.md` 使用 indonesia-intel MCP：未确认候选不得进分析；分类必须用 `intel_taxonomy_list`；抓取失败必须展示完整 `open_url`。

---

## 你可以怎么对 WorkBuddy 说话（示例）

配好之后再说这些即可，不要只丢 GitHub 链接：

```text
用 indonesia-intel：先 intel_poll_sources，再 intel_fetch，然后 intel_list(pending_review) 给我审核卡片。
抓取失败的条目请贴完整 open_url。
```

```text
按 playbook 审核待审池，不要自动 confirm。
```

---

## 可选：浏览器看板（给人看，不是 MCP）

```bat
cd /d C:\Users\你的用户名\indonesia-intel
uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

打开：http://127.0.0.1:8765/app/#feed  
页面里填与 `.env` 相同的 `API_KEY`。

---

## 常见问题

| 现象 | 处理 |
|------|------|
| WorkBuddy 没有 `intel_*` 工具 | 检查 `cwd` 是否本机路径；是否 `pip install -e .`；是否重启宿主 |
| 搜索结果假/空 | `.env` 里配 `EXA_API_KEY` 或 `TAVILY_API_KEY` |
| Agent 乱确认入库 | 没贴 playbook；补贴 `docs/agent_playbook.md` |
| 只给了 GitHub 地址 | 不够；必须完成本页 1–4 步 |

---

## 给仓库主人转述的一句话

> Clone https://github.com/JASMINE145-ACT/indonesia-intel ，照 `docs/workbuddy-setup.md` 配 `.env` + MCP `cwd`，再把 `docs/agent_playbook.md` 贴进 WorkBuddy。
