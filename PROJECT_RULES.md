# 0. 总则

自动化AI工具禁止直接修改本文件。

本文件属于：

- 长期架构规则
- 项目设计哲学
- 历史设计约束
- RAG行为规范

只能由人工审核后修改。

本文件优先级高于：

- AI默认最佳实践
- 通用RAG教程
- 通用ChatBot设计
- 自动化重构建议

---

# 1. 项目名称

企业知识库问答 / 企业结构化RAG系统

---

# 2. 项目目标

本项目不是通用聊天机器人。

核心目标：

- 企业内部知识检索
- 通信领域术语解释
- 历史版本功能追踪
- 数据结构/库表查询
- 原始文档辅助阅读
- 企业系统维护辅助

系统重点：

- 正确性
- 可追溯性
- 原文参考
- 低延迟
- 可解释性
- 文档结构保持

不是：

- 自然聊天
- AI陪伴
- 长对话记忆
- 通用Agent
- 创意生成

本项目核心理念：

Retrieval First，而不是 Chat First。

---

# 3. 系统设计哲学

## 3.1 原文优先

LLM回答可能遗漏信息。

用户必须可以：

- 查看原文
- 查看命中文档
- 查看命中位置
- 验证AI回答
- 跳转完整文档

因此：

- 必须保留 source reference
- 必须支持原文预览
- 必须支持命中区域定位
- chunk不足时允许查看完整文档

系统目标：

不是“替代文档”。

而是：

帮助用户快速定位和阅读文档。

---

## 3.2 不追求“100%完整召回”

企业文档本身：

- 可能重复
- 可能矛盾
- 可能跨文件
- 可能历史遗留严重
- 可能存在错误

因此：

系统目标是：

- 提供高价值上下文
- 提供原文入口
- 提供辅助阅读能力

而不是：

- 保证100%正确
- 保证100%完整
- 代替人工确认

---

## 3.3 企业RAG与通用RAG不同

企业文档存在：

- 大型表结构
- 长版本历史
- OCR内容
- 通信协议内容
- 中英混合术语
- 结构化字段说明
- 大量重复内容

传统通用RAG问题：

- SentenceSplitter破坏表格
- Markdown标题层级丢失
- 字段说明上下文断裂
- 长版本历史被切碎
- OCR内容结构丢失
- 代码块语义被破坏

因此：

本项目采用：

- Heading-aware parsing
- Content-aware parsing
- Block-aware splitting
- Structured metadata
- Retrieval grounding

而不是默认Splitter。

---

# 4. 系统架构

## 4.1 系统组成

系统主要由以下模块组成：

- Dict 精确术语系统
- Markdown结构化解析系统
- Chunk构建系统
- Metadata增强系统
- Vector RAG检索系统
- 原文引用系统
- NiceGUI WebUI

---

## 4.2 数据流

    Markdown
        ↓
    MarkdownHeadingAwareParser
        ↓
    MarkdownContentAwareParser
        ↓
    Block Dispatch
        ↓
    Chunk Split / Merge
        ↓
    Metadata Enrich
        ↓
    Embedding
        ↓
    Vector Store
        ↓
    Retrieval
        ↓
    LLM
        ↓
    Source Reference
        ↓
    UI

---

## 4.3 Dict 与 RAG 是不同系统

### Dict系统

特点：

- 毫秒级响应
- 精确术语解释
- 不经过向量检索
- 不依赖LLM理解
- 用于缩写/字段/术语释义

适用：

- IMSI
- MSISDN
- CF
- CW
- STN-SR
- HSS

等通信术语。

---

### RAG系统

特点：

- 用于复杂问题
- 用于文档推理
- 用于版本历史
- 用于多Chunk综合
- 用于上下文分析

适用：

- 功能是否支持
- 哪个版本新增
- 数据结构含义
- 配置流程
- 历史修改记录

禁止：

- 用Embedding替代Dict
- 用LLM代替精确术语系统

---

# 5. Markdown解析规则

## 5.1 Heading-Aware Parsing

MarkdownHeadingAwareParser负责：

- 按标题层级切分
- 构建header_path
- 保持章节独立
- 保持层级关系
- 保持行号

规则：

- 每个标题章节独立
- 父章节不包含子章节正文
- 子章节继承完整header_path
- 标题本身不进入正文内容

示例：

    # A

    aaa

    ## B

    bbb

得到：

    /A/   -> aaa
    /A/B/ -> bbb

---

## 5.2 Content-Aware Parsing

MarkdownContentAwareParser负责：

- 识别结构化Block
- 保持Block完整
- 避免破坏语义结构
- 避免过度碎片化

当前支持：

- text
- table
- code
- math
- ocr

不同block：

- 使用不同chunk策略
- 使用不同metadata
- 后续可能有不同retrieval权重

---

## 5.3 Block保护原则

以下内容默认不允许普通文本切分：

- markdown table
- code fence
- math block
- OCR block

原因：

这些内容一旦被切断：

- 语义容易丢失
- 格式容易损坏
- retrieval质量会下降

---

# 6. Chunk构建规则

## 6.1 Chunk切分流程

Chunk构建流程：

1. Markdown标题结构切分
2. 内容感知Block切分
3. Block类型分发处理
4. 大Chunk二次拆分
5. 小Chunk动态合并
6. Metadata增强

chunk_size仅作为参考目标。

不是严格限制。

---

## 6.2 Chunk允许不完整

尤其：

- 表结构
- 字段说明
- 大型版本历史
- OCR区域

可能被切断。

因此：

LLM回答不保证完整。

必须允许用户查看原文。

---

## 6.3 Chunk动态合并

允许：

- 合并同父章节
- 合并子章节
- 合并小Chunk

目标：

- 减少碎片化
- 保持语义完整
- 提高检索质量

不是严格固定Chunk大小。

---

## 6.4 表格特殊处理

大型表格允许：

- 保留表头
- 动态分行拆分
- 保留字段结构
- 保留行号范围

原因：

企业文档中：

表格通常比普通正文更重要。

---

## 6.5 不强制统一Chunk策略

不同block：

- text
- table
- code
- math
- ocr

允许：

- 不同split策略
- 不同merge策略
- 不同metadata
- 不同retrieval行为

禁止：

“所有内容统一Splitter”。

---

# 7. Metadata设计规则

## 7.1 Metadata不是附属信息

Metadata属于：

- 原文定位基础
- UI高亮基础
- retrieval grounding基础
- rerank基础
- citation基础
- chunk merge基础

不是可选附加信息。

---

## 7.2 必须保留的Metadata

当前必须保留：

- header_path
- line_start
- line_end
- block_type

可能扩展：

- merged_headers
- table_row_start
- table_row_end
- source_file
- source_document
- retrieval_score

---

## 7.3 Header Path非常重要

header_path用于：

- 保持文档结构
- retrieval理解
- UI显示
- chunk merge
- 原文定位

禁止删除。

---

## 7.4 行号非常重要

line_start / line_end用于：

- 原文定位
- UI高亮
- Debug
- Citation
- 后续原文跳转

禁止删除。

# 8. Retrieval规则

## 8.1 Retrieval优先于生成

系统核心：

先正确召回。

再生成回答。

错误召回：

Prompt再强也无意义。

---

## 8.2 必须允许查看原文

用户必须可以查看：

- 命中文档
- markdown原文
- 命中区域
- 引用图片
- 完整上下文

系统不能只返回AI答案。

---

## 8.3 动态TopK扩展

默认：

- TopK retrieval

当：

- score接近
- chunk命中较多
- 文档明显存在连续性

允许动态扩展：

    5 -> 15

原因：

企业大型文档：

即使：

    1000 * 15

也可能无法完整覆盖。

---

## 8.4 Retrieval不等于完整阅读

RAG不是：

“替代完整阅读文档”。

而是：

“帮助快速定位高价值上下文”。

---

# 9. Prompt设计规则

## 9.1 禁止模型编造

如果上下文不足：

必须：

- 明确说明
- 提示查看原文
- 提示可能存在截断

禁止：

- 幻觉补全
- 猜测版本功能
- 自行脑补缺失内容

---

## 9.2 模型必须接受“上下文可能不完整”

尤其：

- 表结构
- 长版本历史
- OCR内容
- 多Chunk场景

模型必须理解：

当前上下文：

可能只是局部内容。

---

## 9.3 推理模型可能忽略系统约束

部分推理模型会：

- 过度总结
- 自行推断
- 跳过引用
- 忽略原文
- 忽略限制

因此：

Prompt必须：

- 强约束
- 重复强调
- 明确禁止行为
- 强调原文优先

---

# 10. Dict系统规则

## 10.1 英文缩写必须严格匹配

禁止 substring 模糊匹配。

错误案例：

    windows
    → WIN
    → DO
    → WS

属于错误行为。

---

## 10.2 英文匹配使用单词边界

用于中英混合场景。

必须：

- regex word boundary
- token matching

例如：

    HLR中IMSI和MSISDN的关系

正确：

- IMSI
- MSISDN
- HLR

错误：

- windows 命中 WIN
- domain 命中 IM

---

## 10.3 短横线允许忽略

运营商实际输入：

- STR-SN
- STRSN

可能混用。

因此允许：

- 去除 "-"
- 再做严格匹配

仅适用于：

- 通信缩写
- 英文术语

不适用于：

- 普通英文句子
- 下划线

---

## 10.4 中文允许substring

中文没有天然单词边界。

例如：

    MSISDN和IMSI的关系

需要拆出：

- MSISDN
- IMSI

---

## 10.5 长词覆盖短词

例如：

    MSISDN

覆盖：

    ISDN

避免短词污染结果。

实现方式：

- 长词优先
- occupied区域过滤

---

# 11. UI设计规则

## 11.1 调试信息必须可见

必须支持：

- retrieval trace
- chunk score
- timing
- token usage
- chunk metadata

方便：

- 排查问题
- 调整chunk
- 调整prompt
- 调整retrieval

---

## 11.2 输入框必须固定可见

页面布局：

- 上：标题
- 中：聊天区域 + 调试面板
- 下：输入区域

聊天区域允许滚动。

输入框不可被挤出屏幕。

---

## 11.3 自动滚动

新消息时：

- 自动滚到底部
- “滚动到底部”按钮

---

## 11.4 原文阅读体验非常重要

用户需要：

- 快速查看原文
- 根据行号高亮

后续允许支持：

- 原文展示行号
- 快速跳转文档

UI不能只关注聊天体验。

---

# 12. 历史设计决策

## 12.1 为什么不用默认Splitter

原因：

默认Splitter：

- 不理解Markdown结构
- 不理解表格
- 不理解OCR
- 不理解代码块
- 不理解章节层级

会严重破坏企业文档语义。

---

## 12.2 为什么必须保留header_path

因为：

企业文档：

章节结构本身就是重要语义。

例如：

    用户管理 > 鉴权 > IMS注册

与：

    网络配置 > IMS注册

语义可能完全不同。

---

## 12.3 为什么必须保留line number

因为：

用户最终需要：

- 定位原文
- 阅读原文
- 验证AI回答

RAG不是最终结果。

文档才是最终结果。

---

## 12.4 为什么不能只依赖LLM

因为：

LLM：

- 可能遗漏
- 可能幻觉
- 可能总结错误
- 可能忽略表格

因此：

必须：

- retrieval grounding
- source reference
- 原文引用

---

# 13. 禁止的错误优化

禁止：

- 删除metadata
- 删除line number
- 删除header_path
- 删除block_type
- 用默认Splitter替代结构化Parser
- 所有内容统一chunk
- 用embedding替代dict
- 只返回AI答案
- 删除原文引用能力
- 强依赖LLM总结
- 自动重构历史兼容逻辑
- 简化通信行业特殊规则

很多逻辑：

不是“最佳实践”。

而是：

- 企业现实妥协
- 通信行业习惯
- 历史Bug规避
- retrieval质量妥协

禁止AI擅自：

- 重构
- 简化
- 改写核心流程

---

# 14. AI协作规则

## 14.1 AI不理解历史背景

代码中很多逻辑：

可能看起来“不优雅”。

但实际原因可能包括：

- 历史兼容
- 企业文档脏数据
- OCR问题
- markdown格式异常
- 通信行业输入习惯
- retrieval质量问题

AI必须：

先理解原因。

再提出修改建议。

---

## 14.2 AI回答必须人工审核

尤其：

- 正则
- 编码
- 通信协议
- Oracle
- 向量检索
- Chunk逻辑
- Prompt逻辑

必须人工确认。

---

## 14.3 Parser属于核心模块

以下模块属于核心设计：

- MarkdownHeadingAwareParser
- MarkdownContentAwareParser

目标：

让RAG理解：

- 文档层级
- 表格结构
- OCR区域
- 数学区域
- 代码区域

禁止轻易替换。

---

# 15. 后续规划

未来可能增加：

- 原始文档与Markdown关联
- docx/pdf/xlsx原文回溯
- 图片OCR自动关联
- 图片描述自动生成
- 更多block类型
- Metadata过滤检索
- rerank优化
- retrieval routing
- hybrid retrieval
- 更复杂的chunk策略
- dict自动扩展
- web辅助词典更新

目标：

尽量合理、快速、可追溯地呈现用户需要的数据。

---

# 16. 明确不做的内容

当前项目阶段：

不会优先考虑：

- 用户系统
- 权限系统
- 企业级RBAC
- 多租户
- 分布式架构
- 高并发
- 长期聊天记忆
- 多Session管理
- Agent编排平台

原因：

当前项目重点是：

结构化RAG本身。

不是完整企业平台。

额外需求：

应基于本项目重新立项。

---