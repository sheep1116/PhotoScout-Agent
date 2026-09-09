# 第三方来源与许可说明

- [百炼联网搜索文档](https://help.aliyun.com/en/model-studio/web-search)：qwen3.7-plus 使用多模态原生流式搜索和 `search_info`。API 配额、搜索费用及来源内容使用受账户条款约束。
- [高德 Web 服务](https://developer.amap.com/api/webservice/guide/api/search)、[步行路线](https://developer.amap.com/api/webservice/guide/api/direction)：仅服务器调用。GCJ-02 转换为近似 WGS84，不提供测绘精度承诺。
- [Open-Meteo 天气](https://open-meteo.com/en/docs)、[空气质量](https://open-meteo.com/en/docs/air-quality-api)：模型预测，不是机位实测；AQI 使用 US AQI，遵守署名、非商业/商业使用条款。
- [Astral](https://astral.readthedocs.io/en/latest/)：Apache-2.0，太阳计算使用 v3.2。
- [OpenStreetMap](https://www.openstreetmap.org/copyright)：在线底图显示署名，数据 ODbL。公共瓦片仅在用户点击加载后请求；不批量下载、不离线缓存。商用或较高流量应更换合适的瓦片服务。
- MapLibre GL JS、Next.js、React、FastAPI、Pydantic、LangGraph、SQLAlchemy、Redis 等依赖保持原有许可证，完整依赖版本见锁文件。
- 界面离线示意图由代码绘制，未下载第三方参考照片。南京 Seed 为合成开发样例，不声称来自真实社区用户帖子，不重新托管摄影作品。

本仓库不替用户接受条款、创建云账户或购买服务；公网发布前应确认使用场景与各 Provider 授权。
