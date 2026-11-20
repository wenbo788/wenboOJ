# 🧪 测试环境搭建工具

## 概述

`setup_test_env.py` 是一个用于快速在本地搭建 NLNOJ 测试环境的脚本。它会自动创建数据库并插入测试数据，让你可以快速开始开发或调试工作。

## 功能

- ✅ 自动创建 SQLite 测试数据库（`test_oj.db`）
- ✅ 初始化所有表结构
- ✅ 创建 3 个测试用户（含不同权限级别）
- ✅ 创建 4 个论坛帖子及评论
- ✅ 创建 6 条犇犇（动态）
- ✅ 创建 5 条图床图片记录

## 使用方法

### 前置条件

1. 确保已安装项目依赖：
   ```bash
   cd service/
   pip install -r requirements.txt
   # 或使用 uv:
   uv sync
   ```

2. 进入 `service` 目录：
   ```bash
   cd /home/gr3yph4ntom/oj/service/
   ```

### 运行脚本

```bash
# 方式一：直接执行
python scripts/setup_test_env.py

# 方式二：作为模块运行
python -m scripts.setup_test_env
```

### 使用流程

1. 首次运行时，如果数据库文件已存在会提示是否覆盖
2. 确认后脚本将自动创建表和插入测试数据
3. 完成后即可启动后端服务进行测试

## 测试账号信息

| 用户名 | 密码 | 角色 | 说明 |
|--------|------|------|------|
| testuser01 | test1234 | 普通用户 | 无特殊权限 |
| admin_test | test1234 | 管理员 | 可管理用户和帖子 |
| superadmin_test | test1234 | 超级管理员 | 最高权限 |

**注意**：所有测试用户的密码都是 `test1234`

## 创建的数据概览

### 论坛帖子（4 个）
- 【新手指南】如何开始你的 OJ 之旅？（置顶）
- 关于最近比赛的一些说明（站务版，置顶）
- 灌水专区：今天你刷题了吗？
- 【讨论】Dijkstra 算法的优化思路

### 犇犇/动态（6 条）
- 包括普通发言、回复互动等场景

### 图床图片（5 条）
- 使用 picsum.photos 占位图 URL
- 需在 `static/uploads/images/` 目录放入实际图片以完整测试

## 注意事项

⚠️ **重要提示**：
- 此脚本仅用于**本地测试**，不会碰触生产数据库
- 如果 `test_oj.db` 已存在，会提示是否删除重建
- 图床需要手动上传真实图片到指定目录才能完整测试
- 脚本使用的 bcrypt 哈希对应密码为 `test1234`

## 后续操作

搭建完成后，你可以：

1. **启动后端服务**：
   ```bash
   cd service/
   uv run fastapi dev --factory app.main:create_app
   ```

2. **访问前端页面**（需单独配置）：
   ```bash
   cd web/
   npm run dev
   ```

3. **清理测试数据**：
   直接删除 `test_oj.db` 文件即可

## 自定义测试数据

如果你想修改测试数据，可以编辑 `scripts/setup_test_env.py` 中的以下部分：
- `users_data` - 修改用户信息
- `posts_data` - 修改帖子内容
- `benben_data` - 修改犇犇内容
- `image_urls` - 修改图片链接
