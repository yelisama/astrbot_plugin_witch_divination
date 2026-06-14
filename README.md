# astrbot_plugin_witch_divination

AstrBot 魔女占卜插件，支持御神签、塔罗、水晶球等常规占卜。

## 功能

- `/占卜`：使用默认占卜类型
- `/今日运势`、`/御神签`、`/抽签`：御神签
- `/塔罗`：塔罗牌
- `/水晶球`：水晶球
- `/占卜帮助`：查看使用说明
- `/占卜状态`：管理员查看基础状态
- `/占卜诊断`：管理员检查内容池和塔罗图片缺失情况
- `/占卜重载`：管理员重载内容池
- `/占卜清理`：管理员清理过期记录

## 安装

将本插件目录放入 AstrBot 的插件目录，然后重启 AstrBot 或在插件管理中重载。

插件首次运行时会把 `templates/types`、`templates/pools` 和 `templates/assets` 中的模板资源复制到 AstrBot 插件数据目录。

## 塔罗图片素材

为了避免插件仓库过大，建议不要把完整塔罗图库直接放进插件仓库。

塔罗 JSON 中的图片路径类似：

```json
"asset": "assets/tarot_szb/皇帝-逆位.png"
```

实际图片建议放在 AstrBot 插件数据目录：

```text
data/plugin_data/astrbot_plugin_witch_divination/assets/tarot_szb/
```

如果图片不存在，插件会回退为文字结果，不会因为缺图直接崩溃。管理员可以使用 `/占卜诊断` 查看缺失图片数量。

## 维护建议

- 修改 `templates/pools/*.json` 后，先检查 JSON 格式是否正确。
- 修改内容池后，可以使用 `/占卜重载` 让插件重新读取。
- 如果结果异常，先使用 `/占卜诊断`，再查看 AstrBot 日志中的 `WARNING` 和 `ERROR`。
- 不建议提交 `__pycache__`、数据库、日志、运行缓存和大型完整素材包。
