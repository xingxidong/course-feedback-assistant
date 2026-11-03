# 课程反馈工作台

面向每周物理课程反馈的本地工具：一次填写课程内容，为多名学生生成个性化反馈，审核后通过 macOS 微信桌面端精准投递。

## 安全边界

- 服务只监听 `127.0.0.1:8765`，不会暴露到局域网。
- 默认只生成草稿，不会自动发送。
- “写入微信”只填入输入框，不按发送键。
- 真实发送必须输入 `确认发送`。
- 每次操作先搜索并再次核验聊天标题；标题不匹配或存在歧义时停止。
- 已发送草稿默认禁止重复发送。
- 不读取微信私有数据库，不注入微信进程，不破解微信协议。

## 启动

1. 保持 macOS 微信已登录并打开主窗口。
2. 确保 Terminal/ChatGPT 已获得：
   - 系统设置 → 隐私与安全性 → 辅助功能
3. 在终端运行：

```bash
cd /Users/dongxingxi/wechat-course-feedback
zsh start.command
```

浏览器会打开：<http://127.0.0.1:8765>

## 首次使用

1. 点击“添加”，填写学生姓名、年级和微信中的准确群名。
2. 填写本周课程概述和知识点（每行一个）。
3. 填写每位学生本周课堂观察。
4. 点击“生成选中学生反馈”。
5. 在草稿卡片中审核或修改并保存。
6. 先用“写入微信”测试：系统只把第一条写入微信输入框，不发送。
7. 确认群名和正文无误后，再使用“发送”或“发送选中反馈”。

## 生成模式

默认使用内置物理课程反馈生成器，无需 API。它会：

- 保持“课程内容 + 课堂表现”的固定结构；
- 识别常见物理知识点并扩写；
- 将“笨、坐不住、提升不上来”等原始观察转换成客观、适合家长阅读的表达；
- 给出具体改进建议。

如需启用 OpenAI 兼容模型，可设置：

```bash
export COURSE_FEEDBACK_API_BASE="https://your-api/v1"
export COURSE_FEEDBACK_API_KEY="your-key"
export COURSE_FEEDBACK_MODEL="your-model"
./start.command
```

模型调用失败时自动退回内置生成器。

## 自检

```bash
cd /Users/dongxingxi/wechat-course-feedback
zsh scripts/doctor.command
```

自检包括：Python、Node、微信桥接、Python 语法和单元测试。

## 数据

所有数据保存在本机：

```text
data/course_feedback.sqlite3
```

包含学生与群名映射、每周课程、反馈草稿和发送日志。删除数据库前请先备份。

## 目录

```text
app.py                         本地 HTTP 服务
course_feedback/db.py          SQLite 数据层
course_feedback/generator.py   反馈生成器
course_feedback/wechat.py      微信桥接封装
scripts/wechat-cli.mjs         Node 命令行桥接
static/index.html              审核页面
vendor/wechat-fastbridge/      微信辅助功能底座
```

## 第三方组件

微信辅助功能底座改编自：

- wechat-fastbridge
- https://github.com/huj28-creator/wechat-fastbridge
- MIT License

原许可证位于：

```text
vendor/wechat-fastbridge/LICENSES/LICENSE
```

本项目增加了 `draft` 动作：在完成会话标题核验后，只向微信输入框写入并回读验证，不触发发送。
