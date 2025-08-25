# 国内青年人才项目评估服务（Web）

这是一个基于AI的国内青年人才项目多维度评估系统。系统基于成功经验和失败教训，采用针对性的5个核心维度对申请材料进行全面分析，并提供具体的改进建议。

## 环境要求
- Python 3.9+
- Linux/macOS/Windows

## 安装依赖（示例）
```bash
# 1) 选择/激活你的 Conda/虚拟环境（不要使用 base）
conda activate benzieval

# 2) 安装依赖
pip install flask openai requests PyPDF2
```

## 运行
```bash
cd AI-Scientist-research-plan-eval
python app_overseas_young_scholar.py
```
访问 `http://localhost:4091`

### 执行过程（流式评估）
- 点击“开始评估”后，后端按轮次流式返回：
  1) 输入验证专家：校验文本有效性
  2) 内容质量分析专家：深度内容分析
  3) 各维度评估专家：5 个维度逐项评分与依据
  4) 综合评审专家：综合评分与建议
  5) 结构化评估专家：生成结构化 JSON
  6) 政策分析专家：根据设置调用政策模型，输出“最新政策分析”（Markdown 渲染）

### API 接口
- POST `/evaluate_stream`：主评估（SSE），请求体字段：
  - `proposal_text`（必填）
  - `api_name`、`api_base`、`api_key`（可选）
  - `policy_api_name`、`policy_api_base`、`policy_api_key`（可选）
- POST `/evaluate`：非流式备用（当前返回提示使用流式接口）
- POST `/extract_pdf`：PDF 文本提取（支持 URL 或上传文件）

## 配置方式（优先级从高到低）
1) 前端页面设置（保存在浏览器 localStorage，仅本机有效）
- API 设置：`api_name`、`api_base`、`api_key`
- 政策分析设置：`policy_api_name`、`policy_api_base`、`policy_api_key`
- 建议：主评估 `api_name` 可用 `deepseek-v3`；政策分析 `policy_api_name` 建议使用检索/搜索模型，如 `deepseek-r1-search-pro`

2) 后端环境变量（默认值）
- `OPENAI_BASE_URL`（默认网关）
- `OPENAI_API_KEY`（默认密钥）
- `OPENAI_MODEL`（默认评估模型，例如 `deepseek-v3`）

3) 代码内默认
- Base URL: `https://api.chatfire.cn/v1`
- Model: `deepseek-v3`

说明：
- 主评估使用主评估设置；
- 政策分析可单独配置，若 `policy_api_name` 留空，后端仍可按你的策略选择默认；推荐显式填写 `deepseek-r1-search-pro`。

## 使用流程
1. 粘贴申请材料或通过“PDF URL/上传 PDF”提取文本
2. 可在“API 设置（可选）”中填写主评估的 `api_name/api_base/api_key`
3. 可在“政策分析设置（可选）”中填写 `policy_api_name/policy_api_base/policy_api_key`
4. 点击“开始评估”查看：
   - 总分与雷达图
   - 关键维度细项（证据/问题/建议）
   - 优先级改进建议
   - 详细评估信息
   - 最新政策分析（Markdown 渲染）

## 评估标准说明
- 评分维度与权重（总权重=100）：
  - 教育、学术与科研工作经历：15%
  - 已取得科学研究及技术创新的成果及贡献：30%
  - 学术见解及技术成果独特性和原始创新性评价：20%
  - 发展潜力的评价：20%
  - 申请工作设想和国内依托单位支持情况：15%

- 评分尺度（每个维度 1-5 分）：
  - 5 分：世界级突破性成果/顶级期刊/重大社会影响
  - 4 分：国际一流/顶级期刊/重要学术贡献
  - 3 分：国内先进/有学术价值但缺乏突破
  - 2 分：一般水平/成果有限/创新性不足
  - 1 分：质量较差/不适合申请

- 加权总分计算（满分 100）：
  - 每个维度加权分 = (维度得分/5) × 维度权重
  - 总分 = 各维度加权分之和

- 辅助信息：
  - 证据（evidence）：支持该维度评分的客观要点/实例
  - 问题（issues）：该维度存在的不足或风险点
  - 建议（suggestion）：面向该维度的改进动作

## 结果解读
- 总分与等级：
  - ≥90：优秀
  - ≥80 且 <90：良好
  - ≥70 且 <80：中等
  - ≥60 且 <70：及格
  - <60：需要改进

- 雷达图：
  - 各轴表示 5 个维度的原始分（1-5）
  - 形状越均衡越好；凹陷的维度是短板
  - 悬浮提示会展示该点对应的加权信息（便于感知该维度对总分的影响）

- 关键维度卡片：
  - 维度名称、原始分与加权分
  - 维度描述（标准释义）
  - 证据/问题：用于定位“为什么得这个分”
  - 建议：优先从分值低、权重高且有明确建议的维度着手

- 优先级改进建议（Top-N）：
  - 跨维度的具体可执行动作，按优先级排序
  - 适合作为近期行动清单

- 详细评估信息：
  - 主要优势（strengths）：应在申请材料中继续强化与凸显
  - 主要风险（risks）：需在材料与策略中正面化解

- 最新政策分析：
  - 使用政策分析模型（可单独配置）生成，Markdown 展示
  - 聚焦近年的相关政策要点、影响评估与策略建议
  - 建议结合真实政策文件交叉验证关键信息

## 隐私与安全
- 前端输入的 API Key 仅保存在浏览器 `localStorage`，并随请求发送到后端；后端不将其写入磁盘
- 生产环境建议使用自有网关/密钥，并通过反向代理/防火墙限制访问

## 免责声明
本系统不会存储您的申请材料；评估与政策分析基于公开资料与模型输出，仅供学习与参考，不构成任何评审结论或正式意见。请自行核验关键信息，并遵守相关政策与申报要求。

## 常见问题排查
- 页面打不开：确认 4091 端口监听，或修改 `app.run(..., port=4091)` 后重启
- PDF 提取失败：确认 URL 可达或文件为有效 PDF
- LLM 报错：检查 `api_base/api_key` 是否正确，或更换 `api_name/policy_api_name`

## 许可证
此示例仅用于研究与教学，请遵守相关政策法规与平台条款。

## 引用
```
@misc{nuo2025benzieval,
  author = {Nuo Chen},
  title = {BenziEval},
  year = {2025},
  publisher = {GitHub},
  journal = {GitHub repository},
  howpublished = {\url{https://github.com/nuojohnchen/BenziEval}}
}
```
