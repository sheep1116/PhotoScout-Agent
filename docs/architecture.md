# 架构与实现取舍

## 工作流

`Notebook → parse → discover → verify → conditions → schedule → validate → Repository`

单个 LangGraph 有向无环图，递归上限 8；整个生成请求超时 180 秒，同时最多 3 个生成任务。搜索最大两次，模型只接收目的地、题材、日期与发现目的，不接收密钥或任意执行工具。搜索原文和模型输出没有 shell、环境变量、数据库写权限。

`TripBrief` 与其余 Pydantic 模型在 `models.py`。模型之外的第三方 JSON 在 `providers.py` 与 `discovery.py` 消化。统一错误不输出 HTTP 请求对象、带 Key 的 URL 或原始异常。

## 为什么没有引入更多服务

- 本地默认 SQLite + SQLAlchemy，保证安装后可直接演示；Compose 使用 PostgreSQL/PostGIS，与本地共用事务实现。
- 版本化计划 JSON 为事实存储。PostGIS 保存当前版本的相机、入口、第一主体空间投影，具有 GiST 索引，保存/批准/撤销时同事务更新。
- Redis 可选，服务失败回退到有界内存 TTL；当前缓存搜索返回及原始获取时间。天气刷新依照证据有效期判断。
- 前端用普通 CSS 实现视觉样式，减少 Tailwind 配置依赖；Next.js、TypeScript、MapLibre 保留。
- 未引入孙卡前端重复计算，太阳事实统一由后端 Astral 生成，以免两套计算出现时差。
- 未增加多 Agent 对话，数值与安全门控由确定性代码执行。

## 数值规则

新结果使用独立候选模式：时间存储为带 UTC 时区的 datetime，显示按用户 IANA 时区。Astral 先按本地日历计算再转 UTC。每个机位比较自己的天气和可用窗口，加入精确光线边界；多个机位窗口允许重叠，不计算换点序列或默认步行硬预算。旧 build_plan 仅为历史兼容保留。

强降水、雷暴、大风、关闭、开放冲突、危险机位、脚架限制等先门控，再独立评估候选；票务与出行偏好仅作为提示。评分为题材化加权几何平均，权重可在 `engine.WEIGHTS` 调整；置信度独立，不代表经校准的概率。

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


## 0.2 真实图与多源发现

`PhotographyIntent` 统一类别、主体、风格、光线、器材和限制；兼容原 `TripBrief` 字段。类别作为评分权重数据，不复制 LangGraph 流程。`CommunityDiscovery` 负责两次有界联网检索；`DiscoveryHub` 注册 `PhotoProvider` 接口的 Wikimedia/Flickr 适配器。高德 POI 原生图片优先。

模型只提取有来源索引的展示名、地图地标名、所属地点、主体名和站位/构图线索。高德分别定位相机与主体；Place 和 PhotoSpot 不再要求同一 POI。若只能找到父级地点，标记 `area_candidate`；缺主体坐标则不产生方位角。限定景区的请求检查景区相关性，避免只因同城就加入其他景区。

`PhotoReference` 通过 Evidence 与 WebSource 绑定，统一输出真实接口返回的图片元数据；图片 Claim 单独分类，不能改变开放状态。页面通过 `GET /v1/plans/{id}/photos/{photo_id}` 获取图像，代理从已保存计划解析源地址。没有任意 URL 代理入口。详见 [升级指南](product-upgrade.md)。

## 社区与候选发现增量

详见 [本轮结构、数据流和测试](candidate-discovery.md)。新增 `community/` 隔离平台、`recommendations.py` 负责独立窗口、`location.py` 提供 `GET /v1/location/ip` 和 `POST /v1/location/reverse`。`schedule` 节点名为兼容进度协议保留，实际执行候选评估；`presentation=candidates` 明确结果语义。
