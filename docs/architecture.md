# 架构与实现取舍

## 工作流

`Notebook → parse → discover → verify → conditions → schedule → validate → Repository`

单个 LangGraph 有向无环图，递归上限 8；整个生成请求超时 180 秒，同时最多 3 个生成任务。搜索最大两次，模型只接收目的地、题材、日期与发现目的，不接收密钥或任意执行工具。搜索原文和模型输出没有 shell、环境变量、数据库写权限。

`TripBrief` 与其余 Pydantic 模型在 `models.py`。模型之外的第三方 JSON 仅在 `providers.py` 消化。统一错误不输出 HTTP 请求对象、带 Key 的 URL 或原始异常。

## 为什么没有引入更多服务

- 本地默认 SQLite + SQLAlchemy，保证安装后可直接演示；Compose 使用 PostgreSQL/PostGIS，与本地共用事务实现。
- 版本化计划 JSON 为事实存储。PostGIS 保存当前版本的相机、入口、第一主体空间投影，具有 GiST 索引，保存/批准/撤销时同事务更新。
- Redis 可选，服务失败回退到有界内存 TTL；当前缓存搜索返回及原始获取时间。天气刷新依照证据有效期判断。
- 前端用普通 CSS 实现视觉样式，减少 Tailwind 配置依赖；Next.js、TypeScript、MapLibre 保留。
- 未引入孙卡前端重复计算，太阳事实统一由后端 Astral 生成，以免两套计算出现时差。
- 未增加多 Agent 对话，数值与安全门控由确定性代码执行。

## 数值规则

时间存储为带 UTC 时区的 datetime，展示时转换目的地时区。Astral 按日计算太阳窗口，极昼/极夜返回空窗口。排程由可用时间、黄金/蓝调窗口和 25 分钟任务、路线耗时及 10 分钟换点缓冲构成。总换点距离不超出用户预算。首站到达及末站返程不计入，界面明确提示。

强降水、雷暴、大风、关闭、开放冲突、危险机位、票务冲突、脚架限制等先门控，再排程。评分为题材化加权几何平均，权重可在 `engine.WEIGHTS` 调整；置信度独立，不代表经校准的概率。

参数按现有镜头与画幅约束，手持长焦按倒数快门规则收紧，脚架夜景低 ISO，最大光圈不会超出镜头能力。手机使用等效焦段和自动曝光指导。

## 存储与并发

`plans` 保存当前版本；`plan_versions` 保存不可变快照；`proposals` 保存待审批方案；`requests` 保存幂等键与请求指纹。批准使用数据库条件更新 `WHERE version = expected`；不同请求不能覆盖已更新版本。拒绝不改计划。Undo 追加一个恢复旧内容的新版本，从不回退版本号。

生成任务进度暂在内存，已完成计划持久化。重启后可查保存计划；未完成任务不自动续跑、也不自动重试收费请求。当前 API 应使用单 worker，详细扩展限制见 limitations。

## API

| 路径 | 行为 |
|---|---|
| POST `/v1/notebook` | 解析中文基础字段并追问缺失信息 |
| POST `/v1/photo-research` | 幂等创建生成任务 |
| GET `/v1/photo-research/{id}/events` | SSE 步骤和完成状态 |
| GET `/v1/plans`、`/v1/plans/{id}` | 保存计划列表与详情 |
| POST `/v1/plans/{id}/proposals` | 单任务变化提案 |
| POST `/v1/proposals/{id}/decision` | 批准/拒绝，乐观锁 |
| POST `/v1/plans/{id}/undo` | 追加恢复版本 |
| POST `/v1/plans/{id}/spots/{spot}/confirm` | 坐标变更提案 |
| POST `/v1/plans/{id}/refresh` | 过期天气刷新与材料变化提案 |

完整、可执行 Schema 由 FastAPI `/docs` 提供。
