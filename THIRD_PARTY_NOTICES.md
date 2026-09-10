# 第三方来源与许可说明

- [百炼联网搜索文档](https://help.aliyun.com/en/model-studio/web-search)：qwen3.7-plus 使用多模态原生流式搜索和 `search_info`。API 配额、搜索费用及来源内容使用受账户条款约束。
- [高德 Web 服务](https://developer.amap.com/api/webservice/guide/api/search)、[步行路线](https://developer.amap.com/api/webservice/guide/api/direction)：仅服务器调用。GCJ-02 转换为近似 WGS84，不提供测绘精度承诺。
- [Open-Meteo 天气](https://open-meteo.com/en/docs)、[空气质量](https://open-meteo.com/en/docs/air-quality-api)：模型预测，不是机位实测；AQI 使用 US AQI，遵守署名、非商业/商业使用条款。
- [Astral](https://astral.readthedocs.io/en/latest/)：Apache-2.0，太阳计算使用 v3.2。
- [OpenStreetMap](https://www.openstreetmap.org/copyright)：在线底图显示署名，数据 ODbL。公共瓦片仅在用户点击加载后请求；不批量下载、不离线缓存。商用或较高流量应更换合适的瓦片服务。
- MapLibre GL JS、Next.js、React、FastAPI、Pydantic、LangGraph、SQLAlchemy、Redis 等依赖保持原有许可证，完整依赖版本见锁文件。
- 界面离线示意图由代码绘制，南京 Seed 为合成开发样例，不声称来自真实社区用户帖子。Live 新增按需代理真实参考图片，保留来源和授权说明，不作为批量图片托管服务。

本仓库不替用户接受条款、创建云账户或购买服务；公网发布前应确认使用场景与各 Provider 授权。


## 真实参考图（0.2）

- [高德 POI 扩展数据](https://developer.amap.com/api/webservice/guide/api-advanced/search)：使用接口返回的 photos，不猜测图片地址；未给出作者/许可时明确缺失，不授予再分发权。
- [Wikimedia Imageinfo](https://www.mediawiki.org/wiki/API:Imageinfo/en)：读取真实图片地址和 extmetadata；显示原作者与 API 提供的许可证，原文件页为权利信息入口。
- [Flickr photos.search](https://www.flickr.com/services/api/flickr.photos.search.htm)、[getExif](https://www.flickr.com/services/api/flickr.photos.getExif.html)：仅公开参考图片，当前筛选 CC BY 2.0 / CC BY-SA 2.0，保留摄影师原页与署名；EXIF 不可用时留空。API 使用需符合 [Flickr 条款](https://www.flickr.com/help/terms/api)。
- 小红书、抖音、Bilibili、微博只通过公开搜索索引发现摄影线索；不绕过登录或访问控制，不复制受限图库。
