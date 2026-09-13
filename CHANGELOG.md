# Changelog

PhotoScout 的重要产品变化记录在此。实现细节、验收原始数据和已知边界继续保存在 `docs/`。

## Unreleased

### Changed

- 高德文本搜索只要返回非空候选，即采用服务端排序第一项，不再叠加本地精确名称、别名或唯一子地标门槛。
- 参考图搜索兼容字符串形式的 `subject_locations`，避免非关键格式差异丢弃整批候选。
- README 重构为产品首页，版本更新、测试数量和验收记录移出首屏。

## 2026-09-12 — 结构化拍摄建议

- 完整时间、器材、推荐模式和摄影意图进入联网发现任务。
- 候选与引用先结构化，再叠加高德、天气、太阳和多主体距离/方向核验。
- 结果页使用产品化机位卡、时间轴和参考样片，不直接展示模型长文。
- 详细设计与验收见 [结构化拍摄建议与地图核验](docs/agent-first-discovery.md) 和 [升级记录](docs/discovery-agent-upgrade.md)。

## 2026-09-11 — 候选发现

- 新增隔离的 Bilibili 公共元数据适配器与搜索降级。
- 候选改为独立推荐，不再强制安排访问顺序或使用默认步行预算硬筛选。
- 定位、本地时间、跨天默认值与器材输入流程升级。
- 当时验收：140 项后端测试、12 项页面 E2E、63 条离线评测、18 项 Live 检查。
- 详情见 [候选发现升级](docs/candidate-discovery.md)；外部平台可用性边界见 [已知限制](docs/limitations.md)。

## 2026-09-10 — 真实图片与多源发现

- 接入真实高德照片、多源发现适配层和风光、人像、人文、建筑等组合摄影意图。
- 将 Place、PhotoSpot 与 Subject 拆分，分别表达地点、相机站位和被摄主体。
- 增加可审查 Proposal / Diff、并发审批与 Undo。
- 当时验收：119 项后端测试、8 项浏览器 E2E、62 条离线评测、14 项 Live 检查。
- 详情见 [产品升级说明](docs/product-upgrade.md) 和 [验收原始报告](docs/verification/product-upgrade-live.json)。

## 验收资料

- [Live 验收说明](docs/live-acceptance.md)
- [参考照片定位 QA](docs/verification/reverse-photo-qa.json)
- [参考照片定位 Live 结果](docs/verification/reverse-photo-live.json)
- [候选发现 QA](docs/verification/candidate-discovery-qa.json)
- [结构化发现 QA](docs/verification/discovery-agent-qa.json)
- [全部验证产物](docs/verification/)
