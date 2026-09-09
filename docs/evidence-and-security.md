# 证据、安全与服务边界

每个来源有类别、URL（如适用）、获取时间，发布日期未知时保留空。Claim 保留来源身份，不自动把搜索摘要升级成现场事实。Evidence 使用 VERIFIED、REPORTED、CALCULATED、INFERRED、UNKNOWN、STALE、CONFLICT、FIXTURE、USER_CONFIRMED 标签。

离线案例是明确编写的合成 Fixture，不能作为真实开放、天气或人流依据，也不编造对应的社区帖子 URL。Live 来源仅来自 DashScope 返回的 `search_info.search_results`，没有引用的模型输出被拒绝。官方来源仅从政府域名规则识别；此规则不能覆盖所有景区官方企业域名，因此宁可漏识别，不泛化授信。

`resolve_access` 只允许尚未过期、已核验的官方 Claim 影响 OPEN/CLOSED。冲突保留 CONFLICT 并阻断。当前自动搜索的开放线索不标 VERIFIED，所以计划仍为 TENTATIVE。用户记录坐标也不会解除开放/危险门控。

数字的证据链包括太阳算法、UTC 排程规则、天气 API/Fixture、路线 API/Fixture、镜头参数规则、评分分项。最终 Pydantic 校验所有 `evidence_ids` 引用均存在，Evidence 来源均存在，任务时间不重叠。

坐标只保留 WGS84；高德原始 GCJ-02 在后端近似转换。区域和 POI 都不冒充实测点，入口为空就不生成入口导航。离线连接线不是实际路网，绘图文字明确告知。

密钥由 pydantic `SecretStr` 承载，只保存在 `.env` 或部署环境；根目录 `.env` 被 Git 和 Docker 忽略。前端不读取后端密钥。`scripts/check_secrets.py` 仅打印泄漏文件名，不打印密钥。上游异常被映射为静态错误代码，禁用 httpx/httpcore 请求日志。

本地前端写请求使用同源接口代理；后端接受明确允许的本地前端 Origin，不信任任意跨站请求。当前没有公网认证，不应将 8000、数据库、Redis 暴露到公网。

Prompt Injection 被限制在结构化发现输出；服务不执行网页指令，无任意 HTTP 转发、无 shell tool、无环境读取 tool、无模型驱动数据库 mutation。危险词门控只是额外保护，不能代替现场核验。

客流没有数据时统一 UNKNOWN。`fresh_crowd` 会把过期信号标 STALE，并拒绝道路交通或单纯热力图渲染器冒充客流。
