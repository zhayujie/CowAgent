# Web Search Skill

基于 Bing China (cn.bing.com) 的网络搜索技能，无需 API Key，开箱即用。

## 特性

- ✅ **无需 API Key** - 直接使用 Bing China 公开搜索接口
- ✅ **国内可用** - cn.bing.com 在中国大陆可正常访问
- ✅ **结构化结果** - 返回标题、URL、摘要
- ✅ **可配置** - 支持自定义结果数量（1-10条）
- ✅ **轻量级** - 仅依赖 curl 和 python3

## 使用方法

```bash
<base_dir>/scripts/search.sh "搜索关键词" [结果数量]
```

**参数说明：**
- `搜索关键词`（必需）：要搜索的内容
- `结果数量`（可选）：返回结果数，默认 5，最大 10

**示例：**

```bash
# 基础搜索（返回 5 条结果）
<base_dir>/scripts/search.sh "Python 教程"

# 指定返回 3 条结果
<base_dir>/scripts/search.sh "Docker 容器" 3

# 英文搜索
<base_dir>/scripts/search.sh "Kubernetes tutorial" 5
```

**输出示例：**

```
🔍 搜索 'Python 教程' 的结果 (3 条):

1. **Python 基础教程 | 菜鸟教程**
   🔗 https://www.runoob.com/python/python-tutorial.html
   📄 本教程适合想从零开始学习 Python 编程语言的开发人员...

2. **简介 - Python教程 - 廖雪峰的官方网站**
   🔗 https://www.liaoxuefeng.com/wiki/1016959663602400
   📄 这是小白的Python新手教程，具有如下特点：中文，免费...
```

## 依赖

- `curl` - 用于发送 HTTP 请求
- `python3` - 用于解析 HTML 和 URL 编码

## 限制

- 单次搜索最多返回 10 条结果（Bing 限制）
- 依赖 cn.bing.com 的可用性
- 频繁请求可能触发 Bing 的速率限制

## 故障排除

**无结果返回：**
- 检查网络连接
- 尝试不同的搜索词
- 等待几分钟后重试（可能触发速率限制）

**脚本执行失败：**
- 确认已安装 curl 和 python3
- 检查脚本权限：`chmod +x scripts/search.sh`
