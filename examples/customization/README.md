# Openmim customization examples

这里是可直接作为 `CUSTOMIZATION_FILE` 使用的 Openmim 文案 / prompt 示例。

## 使用方式

```bash
CUSTOMIZATION_FILE=/root/openmim/examples/customization/mimchan.customization.json ./start.sh
# 或
CUSTOMIZATION_FILE=/root/openmim/examples/customization/cecilia.customization.json ./start.sh
```

也可以把其中一个文件内容复制到：

```text
/root/openmim/data/customization.json
```

## 文件

- `mimchan.customization.json`：参考 `/root/data/.../telegram-chat-bot` 的咪姆酱猫娘风格。
- `cecilia.customization.json`：参考 `/root/data/.../ceciliabot` 的塞西莉亚白圣女风格。

这些示例只包含 persona / prompt / user-facing copy，不包含 token、管理员 ID、模型 API 等运行配置。
