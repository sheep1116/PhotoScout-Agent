# PhotoScout 实施记录

## 2026-09-08：从空仓库建立 MVP

- 读取自主执行方案及 V3.2 产品方案；保留现有 `.env`、`.env.example` 与 `.gitignore`。
- 找到系统 Python 3.12，创建项目独立 `.venv`，锁定 Python/npm 依赖。
- 实现领域模型、规则引擎、太阳窗口、器材与画幅、时间/步行预算、安全门控及证据引用校验。
- 实现南京双场景合成 Fixture、DashScope 多模态流式引用适配、高德消歧/POI/步行、Open-Meteo 天气/AQI。
- 建立单 LangGraph 受限工作流、FastAPI/SSE、SQLite/PostgreSQL Repository、Proposal/Diff/乐观锁/Undo。
- Next.js 页面、地图、四类偏好、Notebook、历史、导出、证据抽屉、坐标提案、天气刷新。
- 首轮 57 个后端测试通过，随后补足坐标与刷新用例到 62 个。
- 实际浏览器联调修复 Next.js 代理 Host 与 Origin 不一致导致的 403。

## 2026-09-09：恢复任务与交付验证

- 发现 Windows 保留 3000–3352 附近端口，改用本地 3800，未修改系统网络配置。
- 修复 PowerShell JSON 日期自动反序列化导致停止脚本未匹配进程的 bug；使用进程 ID + 启动时间核对，只停止自己的进程树。
- 完整 Playwright E2E **6/6 通过**：人像全流程/夜景/缺日期/坐标审批/移动布局/禁外网离线演示。
- 增加完整 Live 模拟契约（含注入字符串、来源归一、去重）、天气 AQI 对齐和入口路由用例，再补上时间戳与负路线边界，后端最终 **67/67 通过**。
- `python -m evals.run`：**62/62 离线评测通过**；Schema/证据引用完整率 100%，门控违反率 0%，局部改动率 100%。完整逐例结果在 `evals/reports/latest.json`，不是 Live 质量指标。
- `npm run build`、`npm run typecheck`、Ruff 通过。
- `scripts/check_secrets.py` 通过：`.env` 被忽略，候选仓库文件中未发现已配置密钥。
- Docker 引擎本轮可用，前后端镜像构建通过；`docker compose up -d --build --wait` 成功。容器版 PostgreSQL/PostGIS/Redis 运行，**6/6 E2E 再次通过**。数据库查询确认 camera/subject 空间投影和 SRID 4326；Redis PING 返回 PONG。
- 当前预览由 Docker Compose 运行于 `http://127.0.0.1:3800`。本地进程已正常停止；原 SQLite 数据保留。通过 `docker compose down` 停止容器，保留 PG 数据卷。
- README、架构、证据与安全、限制、双场景演示、第三方说明、CI、启动停止脚本已补齐。

## 有意的取舍

更新：2026-09-09 晚间，经用户明确授权，已完成真实账户 Live 验收。修复 SSE 引用重复、跨请求 token 统计、POI 名称规范化、高德业务错误与节流、搜索意图偏移和无关来源展示。79 项后端、6 项浏览器回归通过；最终南京人像 Live 样本 24 项检查通过，后端重启后完整读取。冷缓存两次搜索 9,050 tokens，最终同需求复验使用两次搜索缓存。详见 [Live 验收](live-acceptance.md)。

- SQLite 默认、Redis 可选，降低离线演示启动成本；Compose 提供 PostGIS 实际投影与索引。
- 前端使用普通 CSS；天文只在后端计算。
- 官方开放未核验时保留 UNKNOWN/TENTATIVE；不自动升级社区内容。
- 入口未知时 Live 采用单区域序列，避免制造路线。
- 环境变化优先取消受影响段并等待审批，避免虚构备选地点。
- 首轮未自动试调用付费账户；后续经用户明确授权完成了南京人像 Live 验收。密钥存在与当前账户可用性仍分开表述。

## 验证命令

```text
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check backend tests evals scripts demo
.venv/Scripts/python -m evals.run
.venv/Scripts/python scripts/check_secrets.py
.venv/Scripts/python demo/export_seeds.py
npm run build
npm run typecheck
npm test
docker compose config --quiet
docker compose build
```

未推送 GitHub、未公开仓库、未部署公网、未创建云资源，未修改真实 API 密钥。
