# 校准包（Profile & Anchors）分享指南（M1）

本指南说明如何把「假 UIA 树校准结果」打包分享给社区，以及如何使用别人分享的校准包。

> 官方**不固化**任何第三方截图/校准结果；包完全由使用者自行导出、导入。
> 锚点图只允许包含**操作界面元素**的裁剪（按钮/输入框/消息区等），
> **禁止包含消息内容、头像、昵称、账号信息**（红线 R3 与隐私要求）。

---

## 1. 什么是校准包

一份校准包 = 一份 `profile.json`（假 UIA 树结构）+ 一组锚点图（PNG）。

```
my-wechat-1280x720@1/
├── package.json          # 清单（package_version / profile / 分辨率 / anchor 文件列表）
├── profile.json          # 假 UIA 树 profile（schema=1）
└── anchors/              # 锚点裁剪图（与 profile.json 同级目录）
    ├── main_window.png
    ├── chat_title.png
    ├── search_box.png
    ├── message_area.png
    ├── input_box.png
    └── send_button.png
```

**必需文件清单**

| 文件 | 必需 | 说明 |
|---|---|---|
| `profile.json` | 是 | 元素定义（role / purpose / parent / anchors），锚点路径相对 `anchors/` |
| `anchors/*` | 是 | profile 中引用的每一张锚点图，缺一不可 |
| `package.json` | 建议 | 清单：`package_version`（当前 1）、`profile`、`width`/`height`、`dpi_scale`、`anchor_files` |
| 说明文档 | 建议 | 写明微信版本、主题、分辨率/DPI、录制日期（可写在 README 一并分享） |

包内**不应**包含：聊天截图原图、消息文本、联系人/账号信息、`data/logs`、`.env`。

---

## 2. 导出分享包

```powershell
# 先把当前机器校准好（生成 profile + anchors）
python -m wechat_agent calibrate --elements main_window,chat_title,search_box,message_area,input_box,send_button

# 导出可分享目录（目标非空需 --force）
python -m wechat_agent calibrate --export ./share/wechat-1280x720@1
```

导出时会自动回验：锚点文件必须存在、profile 结构必须合法；成功后打印文件数与分享提示。

---

## 3. 导入别人分享的包

```powershell
# 目录或 .zip 均可；默认导入到 config.yaml 推导的 data 路径
python -m wechat_agent calibrate --import ./share/wechat-1280x720@1

# 目标已存在时必须显式 --force 覆盖
python -m wechat_agent calibrate --import ./share/wechat-1280x720@1 --force

# 可选：导入时用当前截图校验分辨率是否匹配（不匹配退出码 7）
python -m wechat_agent calibrate --import ./share/wechat-1280x720@1 --image ./current_screen.png
```

导入流程（框架自动执行）：

1. 校验包结构：`profile.json`、`anchors/`、`package.json` 版本（`package_version=1`）；
2. 校验 profile 结构：schema、父链/环、锚点文件是否齐全；
3. 校验通过后复制到本机目标路径（`config.profile_path()` / `config.profile_anchors_dir()`）；
4. 打印导入结果与下一步命令（`validate-tree --strict` / `locate`）。

> 安全提示：导入第三方包后仍建议先跑 `validate-tree --strict` 做一次现场校验；不要直接用于真实发送。

---

## 4. 直接用外部路径（不复制）

若校准包已在团队共享盘/固定目录，可让配置直接指向外部绝对路径：

```yaml
uia_tree:
  profile: auto
  dir: ./data/uia_tree
  anchors_dir: ./data/anchors
  # 可选：外部校准包（设置后优先于 dir/anchors_dir 推导）
  profile_path: D:/shared/wechat/1280x720@1/profile.json
  anchors_root: D:/shared/wechat/1280x720@1/anchors
```

- 只设置 `profile_path` 时，锚点目录默认为 `profile.json` 同级的 `anchors/`；
- 外部路径不会被复制进 `data/`，升级/更新分享包只需替换共享目录内容；
- `selftest` 会显示实际生效的 profile 路径。

校验命令：

```powershell
python -m wechat_agent validate-tree --strict     # 真实截屏
python -m wechat_agent locate input_box --json    # 单个元素坐标/分数
```

---

## 5. 兼容性要求

| 维度 | 要求 | 不匹配表现 |
|---|---|---|
| 分辨率 | 与录制时一致 | `ProfileMismatch`，退出码 7 |
| DPI 缩放 | 与录制时一致（100%/125%/150%） | 同上 |
| 客户端版本/主题 | 同大版本、同浅色/深色主题 | 锚点匹配分数低 → `ElementNotVisible`（退出码 3） |
| 窗口布局 | 目标会话布局与录制时一致 | 部分元素定位失败，`validate-tree` 会列出问题元素 |

终端尺寸/DPI 变化后不要强行复用旧包，请重新 `calibrate` 或寻找匹配的分享包。

---

## 6. 分享者检查清单

- [ ] `profile.json` + `anchors/` 齐全，`validate-tree --strict` 本机通过；
- [ ] 锚点图已检查：**不含**任何消息内容/昵称/头像/手机号/二维码；
- [ ] 已写明录制环境（分辨率、DPI、客户端版本、主题、录制日期）；
- [ ] 未附带 `data/`、日志、`.env`、账号信息；
- [ ] 说明「包仅适配录制环境，使用前请自行校验」的免责声明。

---

## 7. 命令速查

```powershell
# 导出
python -m wechat_agent calibrate --export ./share/<name> [--force]
# 导入
python -m wechat_agent calibrate --import ./share/<name> [--force] [--image screenshot.png]
# 外部路径
#   config.yaml -> uia_tree.profile_path / uia_tree.anchors_root（绝对路径）
# 校验
python -m wechat_agent validate-tree --strict [--image screenshot.png] [--json]
python -m wechat_agent locate <element_id> [--image screenshot.png] [--json]
```
