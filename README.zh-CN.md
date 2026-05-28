# memory-governance

[English](README.md) | **中文**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776ab.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io/)
[![CI](https://github.com/mzyag/memory-governance/actions/workflows/ci.yml/badge.svg)](https://github.com/mzyag/memory-governance/actions/workflows/ci.yml)

**你的 AI 助手记住了数据库密码。谁能读取这些记忆？什么时候会被删除？它做决策时知道什么——你能证明吗？**

Memory Governance 是 AI Agent 记忆层的策略引擎，以 [MCP](https://modelcontextprotocol.io/) Server 形式交付。它位于 AI 工具和记忆存储之间，强制执行访问控制、审计日志、留存策略和 PII 脱敏——让治理不再依赖 Agent 的自觉。

```
AI Agent (Claude / Cursor / Copilot)
         │
         ▼
┌─────────────────────────┐
│  memory-governance      │  ← policy enforcement
│  (MCP Server)           │
│                         │
│  Access control (RBAC)  │
│  Audit logging          │
│  PII redaction          │
│  Episode cap + dedup    │
│  Retention policies     │
└─────────┬───────────────┘
          ▼
   Memory Storage (flat files)
```

## 为什么需要

AI 编码助手已经拥有持久化记忆。这很强大——也很危险：

- **没有访问控制。** 任何能读取记忆目录的工具都能看到一切：项目密钥、用户纠正记录、合规备注。
- **没有审计追踪。** 你无法回答"Agent 生成那段代码时知道什么？"——这是监管机构迟早会问的问题。
- **没有留存策略。** Episode 日志中的 PII 永远留存，除非有人手动清理。
- **没有 PII 保护。** 任务描述中的邮箱地址会原样写入记忆文件。

这些不是假设性风险。这是在任何关注数据治理的环境中运行 AI Agent 的现实——金融、医疗、政府，或任何有合规要求的团队。

## 快速开始

### 安装

无需 PyPI 安装——通过 `uvx` 直接从 GitHub 运行：

```bash
uvx --from git+https://github.com/mzyag/memory-governance.git memory-governance
```

或从源码安装（开发用）：

```bash
git clone https://github.com/mzyag/memory-governance.git
cd memory-governance
pip install -e ".[dev]"
```

### 配置

创建 `policy.yaml`：

```yaml
retention:
  project:
    max_age_days: 365
    episode_cap: 10
  feedback:
    max_age_days: null   # 永不过期

access:
  roles:
    default:
      read: [project, area, feedback, resource]
      write: [project]
    compliance_officer:
      read: [project, area, feedback, resource]
      write: []           # 只读

pii:
  enabled: true
  redact_emails: true
  redact_phones: true
  redact_tokens: true

audit:
  retention_days: 2555    # 约 7 年
```

### 接入 Claude Code

添加到 Claude Code MCP 配置 (`~/.claude/settings.json`)：

```json
{
  "mcpServers": {
    "memory-governance": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/mzyag/memory-governance.git", "memory-governance"],
      "env": {
        "MG_POLICY_FILE": "/path/to/policy.yaml",
        "MG_MEMORY_DIR": "/path/to/memory",
        "MG_ROLE": "default"
      }
    }
  }
}
```

### 接入 Cursor

添加到 `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "memory-governance": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/mzyag/memory-governance.git", "memory-governance"],
      "env": {
        "MG_POLICY_FILE": "./policy.yaml",
        "MG_MEMORY_DIR": "./.memory",
        "MG_ROLE": "default"
      }
    }
  }
}
```

## 工具

Server 向所有 MCP 兼容的 AI 客户端暴露六个工具：

| 工具 | 描述 |
|------|------|
| `list_memories` | 列出记忆文件，可按分类过滤 |
| `read_memory` | 读取文件——受访问控制约束 |
| `write_episode` | 追加 Episode——PII 脱敏、去重、上限管控 |
| `create_memory` | 创建新记忆文件（含规范 frontmatter） |
| `check_staleness` | 查找长期未更新的记忆 |
| `query_audit_log` | 按日期、操作、角色、分类查询审计日志 |

所有操作均记录到 `audit.jsonl`，包含时间戳、角色、操作、目标、结果及 PII 检测信息。

## 记忆 Schema

记忆文件使用 4 字段 YAML frontmatter：

```yaml
---
name: ap-my-project
description: 用于相关性匹配的一行摘要
category: project        # project | area | feedback | resource
updated: 2026-05-28
---
```

四个分类，各有不同的治理策略：

| 分类 | 前缀 | 默认权限 | 典型内容 |
|------|------|---------|---------|
| `project` | `ap-` | 读 + 写 | 架构决策、Episode 日志 |
| `area` | `area-` | 只读 | 用户画像、持续职责 |
| `feedback` | `fb-` | 只读 | 行为纠正、已验证的做法 |
| `resource` | `res-` | 只读 | 外部参考、服务索引 |

## 策略即代码

所有治理规则集中在一个 YAML 文件中——可版本控制、可审计、可评审：

- **访问控制**：按角色、按分类的 RBAC。`analyst` 可以读 project 但不能读 feedback；`compliance_officer` 可以读所有但不能写。
- **留存策略**：按分类设置 `max_age_days` 和 `episode_cap`。超过上限时，最早的 Episode 自动归档。
- **PII 脱敏**：邮箱、手机号、Bearer Token、API Key 在存储前被检测并替换为 `[REDACTED:type]`。
- **审计**：每次读取、写入、创建、拒绝访问都带完整上下文记录。

## 设计原则

1. **治理在边界，不在提示词。** 告诉 Agent"不要存 PII"是建议性的（70-90% 合规率）。在 Server 层脱敏是确定性的（100%）。
2. **存储无关。** 当前版本使用 Markdown 文件。治理层不关心底层——换成 SQLite、S3 或向量数据库无需改策略。
3. **策略即代码。** YAML 在版本控制中，不是藏在 UI 设置里。可在 PR 中评审，可被合规团队审计。
4. **本地优先。** 记忆留在你的机器上。Server 在本地运行。无云端依赖。

## 背景

本项目源于在受监管金融服务环境中运行 AI Agent 八个月的实践经验。记忆架构、四维分类体系和治理模式的详细说明：

- [生产级 Agent 的记忆架构](https://mzyag.github.io/writing/memory-architecture.html) — 三层设计、内容分类、预算感知注入
- [维护 Agent 的知识层](https://mzyag.github.io/writing/optimizing-agent-knowledge-layer.html) — Episode 噪声、写路径加固、门控遗忘

## 许可证

MIT
