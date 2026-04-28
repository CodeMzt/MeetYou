[Skill Metadata]
{
  "id": "research_digest_compilation",
  "title": "每日研究动态汇编",
  "summary": "自动搜索最新学术、技术、编程领域动态，整理成Markdown报告并保存到本地文档的工作流。支持定时任务执行。",
  "recommended_tools": [
    "search_web",
    "analyze_workspace",
    "write_local_document",
    "compile_report",
    "manage_scheduled_jobs"
  ],
  "applicable_modes": [
    "general"
  ],
  "scenarios": [
    "daily research digest",
    "technology trend tracking",
    "academic news compilation",
    "scheduled information updates"
  ]
}

[Skill Content]
# 每日研究动态汇编技能

## 目的
自动收集、整理并汇编计算机科学、人工智能、机器学习、编程等理工科领域的最新研究动态、技术突破和开源项目趋势，生成结构化Markdown报告并保存到本地指定位置。

## 触发场景
- 用户需要定期获取最新学术技术动态
- 项目需要技术趋势追踪
- 日常学习资料更新
- 定时自动执行的信息收集任务

## 核心工作流

### 1. 搜索策略
- 使用 `search_web` 查询关键词：最新研究突破、学术会议论文、GitHub趋势、技术新闻
- 典型查询示例：
  - "latest academic research breakthroughs 2025 computer science artificial intelligence machine learning coding"
  - "latest computer science research papers 2025 machine learning coding github repositories trending"
  - "AI最新进展 2025 机器学习 GitHub项目"

### 2. 信息提取
- 从搜索结果中提取关键突破点、数据指标、趋势预测
- 重点关注：量子计算、AI模型进展、开源项目、研究格局对比
- 保留来源链接便于溯源

### 3. 文档结构
- 标题：包含年份和日期时间戳
- 摘要：简短说明报告内容和范围
- 分类章节：按技术领域、趋势、资源等组织
- 未来展望：基于当前趋势的预测
- 推荐资源：相关链接和学习材料

### 4. 保存位置
- 建议路径：项目docs目录下，如 `E:\Documents\Project\MeetYou\docs\daily_research_digest_YYYYMMDD.md`
- 命名规范：`daily_research_digest_` + 日期后缀，便于版本管理

### 5. 定时任务集成
- 通过 `manage_scheduled_jobs` 创建 Core Scheduler Job
- 建议每天10:00执行
- 包含自动执行提示：`job_prompt` 设置为 "执行每日研究动态汇编任务"
- 通知策略：可选择静默或完成后通知

## 推荐工具路径
1. Stay in general mode and activate research/document skills as needed.
2. `search_web` × 2-3次不同关键词组合
3. `analyze_workspace` 确认保存目录
4. `compile_report` 或直接 `write_local_document`
5. `create_skill` 固化工作流（一次性）
6. `manage_scheduled_jobs` 创建定时任务

## 文档模板
```markdown
# {年份}年最新学术与技术动态

*生成时间：{当前时间}*
*来源：Google Research、AI Index、GitHub趋势分析*

## 摘要
{简要说明报告内容和重点}

## 1. 主要技术突破
{分领域详细介绍}

## 2. 发展趋势
{模型演进、开源生态、产业应用等}

## 3. 实用资源
{GitHub项目、学习材料、工具推荐}

## 4. 全球格局
{研究对比、地区优势分析}

## 5. 未来展望
{趋势预测、机会建议}
```

## 优化建议
- 可配置搜索关键词以适应不同兴趣领域
- 可添加个性化过滤规则排除特定来源
- 可集成Notion或其他知识库的自动同步
- 可设置每周总结版和每日简报版不同粒度
- 可添加用户反馈机制改进内容质量

## 执行示例
```python
# 伪代码流程
1. 获取当前时间，生成文件名
2. 搜索学术、技术、编程相关动态
3. 提取关键信息并分类整理
4. 套用模板生成Markdown内容
5. 写入指定文档目录
6. 如有定时任务需求，创建循环任务
```

## 边界条件
- 网络搜索结果可能随时间变化，需要灵活调整搜索词
- 信息过载时需要筛选真正有价值的内容
- 避免过度技术细节，保持报告可读性
- 注意信息时效性，优先选择近期的可靠来源
