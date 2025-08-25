from flask import Flask, render_template, request, jsonify, Response
import json
import requests
from openai import OpenAI
import PyPDF2
import io
import re
from datetime import datetime
import os

app = Flask(__name__)

def safe_json_dumps(data):
    """安全地序列化JSON数据，处理Unicode字符"""
    try:
        return json.dumps(data, ensure_ascii=False)
    except Exception as e:
        # 如果序列化失败，尝试清理数据
        def clean_string(obj):
            if isinstance(obj, str):
                # 移除或替换可能导致JSON序列化问题的字符
                return obj.encode('utf-8', errors='ignore').decode('utf-8')
            elif isinstance(obj, dict):
                return {k: clean_string(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean_string(item) for item in obj]
            else:
                return obj
        
        cleaned_data = clean_string(data)
        return json.dumps(cleaned_data, ensure_ascii=False)

def stream_response_with_buffer(response, round_num, reviewer):
    """使用缓冲区流式处理响应，避免JSON截断问题"""
    result = ""
    content_buffer = ""
    
    try:
        for chunk in response:
            if hasattr(chunk, 'choices') and len(chunk.choices) > 0:
                if hasattr(chunk.choices[0], 'delta') and hasattr(chunk.choices[0].delta, 'content'):
                    if chunk.choices[0].delta.content:
                        content_buffer += chunk.choices[0].delta.content
                        result += chunk.choices[0].delta.content
                        
                        # 当缓冲区达到一定大小或遇到句子结束符时发送
                        if len(content_buffer) >= 50 or any(char in content_buffer for char in ['。', '！', '？', '；', '\n']):
                            try:
                                json_data = safe_json_dumps({'round': round_num, 'reviewer': reviewer, 'status': 'streaming', 'content': content_buffer})
                                yield f"data: {json_data}\n\n"
                                content_buffer = ""  # 清空缓冲区
                            except Exception as json_error:
                                error_data = safe_json_dumps({'round': round_num, 'reviewer': reviewer, 'status': 'error', 'message': f'数据序列化失败: {str(json_error)}'})
                                yield f"data: {error_data}\n\n"
        
        # 发送剩余的缓冲区内容
        if content_buffer:
            try:
                json_data = safe_json_dumps({'round': round_num, 'reviewer': reviewer, 'status': 'streaming', 'content': content_buffer})
                yield f"data: {json_data}\n\n"
            except Exception as json_error:
                error_data = safe_json_dumps({'round': round_num, 'reviewer': reviewer, 'status': 'error', 'message': f'数据序列化失败: {str(json_error)}'})
                yield f"data: {error_data}\n\n"
    
    except Exception as e:
        error_data = safe_json_dumps({'round': round_num, 'reviewer': reviewer, 'status': 'error', 'message': f'流式处理失败: {str(e)}'})
        yield f"data: {error_data}\n\n"
    
    return result

# Defaults for model and API
DEFAULT_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.chatfire.cn/v1")
DEFAULT_API_KEY = os.getenv("OPENAI_API_KEY")
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "deepseek-v3")

# Initialize default OpenAI client (used when未传自定义设置)
client = OpenAI(base_url=DEFAULT_BASE_URL, api_key=DEFAULT_API_KEY)
model = DEFAULT_MODEL

@app.route('/')
def index():
    return render_template('overseas_young_scholar.html')

@app.route('/evaluate_stream', methods=['POST'])
def evaluate_stream():
    # 在请求上下文中获取数据
    data = request.json
    proposal_text = data.get('proposal_text', '').strip()
    # 可选：前端透传的自定义模型、API网关与API密钥
    api_name = (data.get('api_name') or '').strip() if isinstance(data, dict) else ''
    api_base = (data.get('api_base') or '').strip() if isinstance(data, dict) else ''
    api_key = (data.get('api_key') or '').strip() if isinstance(data, dict) else ''
    # 政策分析单独设置
    policy_api_name = (data.get('policy_api_name') or '').strip() if isinstance(data, dict) else ''
    policy_api_base = (data.get('policy_api_base') or '').strip() if isinstance(data, dict) else ''
    policy_api_key = (data.get('policy_api_key') or '').strip() if isinstance(data, dict) else ''
    effective_base_url = api_base if api_base else DEFAULT_BASE_URL
    effective_model = api_name if api_name else DEFAULT_MODEL
    effective_client = OpenAI(base_url=effective_base_url, api_key=(api_key or DEFAULT_API_KEY))
    # 政策分析专用 client & model（独立于主评估设置）
    policy_base_url = policy_api_base if policy_api_base else effective_base_url
    policy_api_key_eff = policy_api_key if policy_api_key else (api_key or DEFAULT_API_KEY)
    effective_policy_model = policy_api_name if policy_api_name else "deepseek-r1-search-pro"
    policy_client = OpenAI(base_url=policy_base_url, api_key=policy_api_key_eff)
    
    def generate():
        try:
            
            if not proposal_text:
                yield f"data: {safe_json_dumps({'error': '请提供研究计划文本'})}\n\n"
                return
            
            # 第一轮：输入验证
            yield f"data: {safe_json_dumps({'round': 1, 'reviewer': '输入验证专家', 'status': 'start', 'message': '开始验证输入内容...'})}\n\n"
            
            validation_prompt = f"""作为输入验证专家，请验证以下申请材料的有效性：

{proposal_text}

**验证标准**：
- 检查是否包含基本的申请材料内容
- 评估内容的完整性和学术价值
- 判断是否适合进行深入评估
- 对于PDF提取的内容，要理解可能包含一些格式信息

请以对话形式回答：
1. 这段内容是否包含有效的国内青年人才申请材料？
2. 内容长度和质量如何？是否包含学术相关要素？
3. 是否值得进行深入评估？
4. 您的初步判断是什么？

请用自然语言回答，就像在与其他专家讨论一样。对于合理的申请材料，应该给予评估机会。"""

            try:
                validation_response = effective_client.chat.completions.create(
                    model=effective_model,
                    messages=[
                        {"role": "system", "content": "你是一位资深的国内青年人才项目评审专家，正在与其他专家进行讨论。"},
                        {"role": "user", "content": validation_prompt}
                    ],
                    temperature=0.3,
                    max_tokens=1000,
                    stream=True
                )
                
                # 使用缓冲区流式处理
                validation_result = ""
                for chunk_data in stream_response_with_buffer(validation_response, 1, '输入验证专家'):
                    yield chunk_data
                    # 提取内容用于后续处理
                    if isinstance(chunk_data, str) and 'content' in chunk_data:
                        try:
                            data = json.loads(chunk_data.replace('data: ', ''))
                            if 'content' in data:
                                validation_result += data['content']
                        except:
                            pass
                
                yield f"data: {safe_json_dumps({'round': 1, 'reviewer': '输入验证专家', 'status': 'complete', 'message': '输入验证完成'})}\n\n"
                
                # 检查是否包含URL链接（只在URL占主导地位时拒绝）
                url_count = proposal_text.count("http://") + proposal_text.count("https://")
                text_length = len(proposal_text)
                
                # 如果URL数量过多或文本太短，则拒绝
                if url_count > 3 or (url_count > 0 and text_length < 100):
                    yield f"data: {safe_json_dumps({'round': 1, 'reviewer': '输入验证专家', 'status': 'error', 'message': '检测到过多URL链接或内容过短，请提供实际的申请材料文本内容'})}\n\n"
                    yield f"data: {safe_json_dumps({'status': 'validation_failed', 'message': '输入验证失败'})}\n\n"
                    return
                
            except Exception as e:
                yield f"data: {safe_json_dumps({'round': 1, 'reviewer': '输入验证专家', 'status': 'error', 'message': f'输入验证失败: {str(e)}'})}\n\n"
                return
            
            # 第二轮：内容质量分析
            yield f"data: {safe_json_dumps({'round': 2, 'reviewer': '内容质量分析专家', 'status': 'start', 'message': '开始分析内容质量...'})}\n\n"
            
            analysis_prompt = f"""作为内容质量分析专家，请深入分析以下申请材料：

{proposal_text}

**极其严格的评估标准**：
- 只有世界顶级水平的研究才能获得高分评价
- 普通水平的研究只能获得中等评价
- 质量差的研究必须给予严厉批评
- 如果材料不完整、缺乏具体数据、没有突出成果，必须指出严重不足

请从以下角度进行详细分析，并以对话形式与其他专家讨论：

1. **内容完整性分析**：
   - 是否包含详细的教育背景信息？是否来自世界顶级大学？
   - 是否有具体的研究成果？是否发表在顶级期刊？
   - 是否描述了突破性创新贡献？是否有重大社会影响？
   - 是否有明确的发展计划？是否具有可操作性？

2. **学术水平评估**：
   - 体现了什么水平的学术能力？是否达到世界级水平？
   - 研究实力如何？是否有独立解决重大科学问题的能力？
   - 与国际水平相比如何？是否具有国际竞争力？

3. **具体程度分析**：
   - 提供了哪些具体数据？是否有量化指标？
   - 成果描述是否具体？是否有详细的技术细节？
   - 计划是否可操作？是否有明确的时间表和里程碑？

4. **逻辑性评价**：
   - 内容结构是否清晰？逻辑是否严密？
   - 各部分是否协调？是否形成完整的研究体系？
   - 是否体现了高水平的学术思维？

请用自然语言详细回答，就像在评审会议上发言一样。记住：宁可严厉批评也不要给予过高评价！"""

            try:
                analysis_response = effective_client.chat.completions.create(
                    model=effective_model,
                    messages=[
                        {"role": "system", "content": "你是一位资深的学术内容分析专家，正在评审会议上发言。"},
                        {"role": "user", "content": analysis_prompt}
                    ],
                    temperature=0.3,
                    max_tokens=1500,
                    stream=True
                )
                
                # 使用缓冲区流式处理
                analysis_result = ""
                for chunk_data in stream_response_with_buffer(analysis_response, 2, '内容质量分析专家'):
                    yield chunk_data
                    # 提取内容用于后续处理
                    if isinstance(chunk_data, str) and 'content' in chunk_data:
                        try:
                            data = json.loads(chunk_data.replace('data: ', ''))
                            if 'content' in data:
                                analysis_result += data['content']
                        except:
                            pass
                
                yield f"data: {safe_json_dumps({'round': 2, 'reviewer': '内容质量分析专家', 'status': 'complete', 'message': '内容质量分析完成'})}\n\n"
                
            except Exception as e:
                yield f"data: {safe_json_dumps({'round': 2, 'reviewer': '内容质量分析专家', 'status': 'error', 'message': f'内容质量分析失败: {str(e)}'})}\n\n"
                return
            
            # 第三轮：各维度详细评估
            yield f"data: {safe_json_dumps({'round': 3, 'reviewer': '各维度评估专家', 'status': 'start', 'message': '开始详细评估各维度...'})}\n\n"
            
            dimension_prompt = f"""作为各维度评估专家，请对以下申请材料进行详细评估：

{proposal_text}

**极其严格的评分标准**：
- 5分：世界级突破性成果，发表在Nature/Science级别期刊，有重大社会影响
- 4分：国际一流成果，发表在顶级期刊，有重要学术贡献
- 3分：国内先进水平，有一定学术价值，但缺乏突破性
- 2分：一般水平，成果有限，缺乏创新性
- 1分：质量很差，缺乏学术价值，不适合申请

请分别评估以下5个维度，并以对话形式详细说明：

**维度1：教育、学术与科研工作经历 (权重15%)**
- 教育背景如何？是否来自世界顶级大学？
- 海外科研经历如何？是否在顶级机构工作？
- 项目负责经验如何？是否独立负责重大项目？
- 评分理由是什么？严格按照上述标准评分

**维度2：已取得科学研究及技术创新的成果及贡献 (权重30%)**
- 主要成果有哪些？是否发表在顶级期刊？
- 创新贡献如何？是否有突破性发现？
- 社会影响如何？是否有重大应用价值？
- 评分理由是什么？严格按照上述标准评分

**维度3：学术见解及技术成果独特性和原始创新性评价 (权重20%)**
- 工作的原创性如何？是否解决了前人未解决的问题？
- 独特性体现在哪里？
- 与现有工作的区别？
- 评分理由是什么？

**维度4：发展潜力的评价 (权重20%)**
- 前期成果与国家需求的契合度如何？
- 研究连续性和成果集中度如何？
- 未来发展方向是否明确？
- 评分理由是什么？

**维度5：申请工作设想和国内依托单位支持情况 (权重15%)**
- 工作设想是否具体可行？
- 依托单位支持是否充分？
- 与前期工作的衔接如何？
- 评分理由是什么？

请用自然语言详细回答，就像在评审会议上发言一样。"""

            try:
                dimension_response = effective_client.chat.completions.create(
                    model=effective_model,
                    messages=[
                        {"role": "system", "content": "你是一位资深的各维度评估专家，正在评审会议上发言。"},
                        {"role": "user", "content": dimension_prompt}
                    ],
                    temperature=0.3,
                    max_tokens=2000,
                    stream=True
                )
                
                # 使用缓冲区流式处理
                dimension_result = ""
                for chunk_data in stream_response_with_buffer(dimension_response, 3, '各维度评估专家'):
                    yield chunk_data
                    # 提取内容用于后续处理
                    if isinstance(chunk_data, str) and 'content' in chunk_data:
                        try:
                            data = json.loads(chunk_data.replace('data: ', ''))
                            if 'content' in data:
                                dimension_result += data['content']
                        except:
                            pass
                
                yield f"data: {safe_json_dumps({'round': 3, 'reviewer': '各维度评估专家', 'status': 'complete', 'message': '各维度评估完成'})}\n\n"
                
            except Exception as e:
                yield f"data: {safe_json_dumps({'round': 3, 'reviewer': '各维度评估专家', 'status': 'error', 'message': f'各维度评估失败: {str(e)}'})}\n\n"
                return
            
            # 第四轮：综合评分和建议
            yield f"data: {safe_json_dumps({'round': 4, 'reviewer': '综合评审专家', 'status': 'start', 'message': '开始综合评估和建议...'})}\n\n"
            
            final_prompt = f"""作为综合评审专家，基于前面的分析，请进行最终的综合评估：

申请材料：{proposal_text}

前面的分析结果：
- 输入验证：{validation_result}
- 内容质量分析：{analysis_result}
- 各维度评估：{dimension_result}

请以对话形式进行最终的综合评估，包括：

1. **综合评分**：给出5个维度的具体分数（1-5分）和加权总分
2. **主要优势分析**：详细分析申请人的主要优势（至少5点）
3. **主要风险分析**：详细分析存在的主要风险（至少5点）
4. **具体改进建议**：提供针对国内青年人才申请的具体、可操作的改进建议（至少8条，按优先级排序），包括：
   - 申请材料的具体修改建议
   - 成果展示的优化方向
   - 申请策略的调整建议
   - 时间安排和准备计划
   - 与依托单位的沟通建议
5. **总体评价**：给出总体评价和最终建议

**极其严格的评分标准**：
- 只有世界顶级水平的研究才能获得4-5分
- 普通水平的研究只能获得2-3分
- 质量差的研究必须给予1-2分
- 如果材料不完整、缺乏具体数据、没有突出成果，总分必须在50分以下
- 如果只是泛泛而谈、没有实质性内容，总分必须在40分以下
- 如果内容空洞、缺乏学术价值，总分必须在30分以下

**评分参考标准**：
- 5分：世界级突破性成果，发表在Nature/Science级别期刊，有重大社会影响
- 4分：国际一流成果，发表在顶级期刊，有重要学术贡献
- 3分：国内先进水平，有一定学术价值，但缺乏突破性
- 2分：一般水平，成果有限，缺乏创新性
- 1分：质量很差，缺乏学术价值，不适合申请

请用自然语言详细回答，就像在评审会议上做最终总结发言一样。记住：宁可给低分也不要给同情分！"""

            try:
                final_response = effective_client.chat.completions.create(
                    model=effective_model,
                    messages=[
                        {"role": "system", "content": "你是一位资深的综合评审专家，负责最终的综合评估和建议。"},
                        {"role": "user", "content": final_prompt}
                    ],
                    temperature=0.2,
                    max_tokens=3000,
                    stream=True
                )
                
                # 使用缓冲区流式处理
                final_result = ""
                for chunk_data in stream_response_with_buffer(final_response, 4, '综合评审专家'):
                    yield chunk_data
                    # 提取内容用于后续处理
                    if isinstance(chunk_data, str) and 'content' in chunk_data:
                        try:
                            data = json.loads(chunk_data.replace('data: ', ''))
                            if 'content' in data:
                                final_result += data['content']
                        except:
                            pass

                # 若流式没有任何内容，回退一次非流式获取完整结果
                if not final_result.strip():
                    try:
                        final_response_simple = effective_client.chat.completions.create(
                            model=effective_model,
                            messages=[
                                {"role": "system", "content": "你是一位资深的综合评审专家，负责最终的综合评估和建议。"},
                                {"role": "user", "content": final_prompt}
                            ],
                            temperature=0.2,
                            max_tokens=3000,
                            stream=False
                        )
                        final_result = final_response_simple.choices[0].message.content or ""
                        if final_result:
                            yield f"data: {safe_json_dumps({'round': 4, 'reviewer': '综合评审专家', 'status': 'streaming', 'content': final_result})}\n\n"
                    except Exception as _fallback_err:
                        pass

                yield f"data: {safe_json_dumps({'round': 4, 'reviewer': '综合评审专家', 'status': 'complete', 'message': '综合评估完成'})}\n\n"
                
            except Exception as e:
                yield f"data: {safe_json_dumps({'round': 4, 'reviewer': '综合评审专家', 'status': 'error', 'message': f'综合评估失败: {str(e)}'})}\n\n"
                return
            
            # 第五轮：结构化评分（基于前面的分析生成JSON）
            yield f"data: {safe_json_dumps({'round': 5, 'reviewer': '结构化评估专家', 'status': 'start', 'message': '正在生成结构化评估结果...'})}\n\n"
            
            json_prompt = f"""基于前面的所有分析，请生成结构化的评估结果：

前面的分析：
- 输入验证：{validation_result}
- 内容质量分析：{analysis_result}
- 各维度评估：{dimension_result}
- 综合评估：{final_result}

**极其严格的评分标准**：
- 5分：世界级突破性成果，发表在Nature/Science级别期刊，有重大社会影响
- 4分：国际一流成果，发表在顶级期刊，有重要学术贡献  
- 3分：国内先进水平，有一定学术价值，但缺乏突破性
- 2分：一般水平，成果有限，缺乏创新性
- 1分：质量很差，缺乏学术价值，不适合申请

**评分原则**：
- 只有真正世界级的研究才能获得4-5分
- 普通水平的研究只能获得2-3分
- 质量差的研究必须给予1-2分
- 如果材料不完整、缺乏具体数据、没有突出成果，总分必须在50分以下
- 如果只是泛泛而谈、没有实质性内容，总分必须在40分以下
- 如果内容空洞、缺乏学术价值，总分必须在30分以下

**重要要求**：
1. **优先级改进建议**：必须是针对国内青年人才申请的具体、可操作的改进建议，包括：
   - 申请材料的具体修改建议
   - 成果展示的优化方向
   - 申请策略的调整建议
   - 时间安排和准备计划
   - 与依托单位的沟通建议

2. **详细评估信息**：重点关注申请相关的要素，避免技术细节：
   - 教育背景和海外经历的亮点与不足
   - 科研成果的学术影响力和创新性
   - 与国家重大需求的契合度
   - 工作计划的可行性
   - 依托单位支持的充分性

请严格按照以下JSON格式输出结构化结果：

{{
  "meta": {{
    "title": "国内青年人才申请评估结果",
    "version": "v1.0", 
    "review_time": "{datetime.now().isoformat()}"
  }},
  "scores": [
    {{
      "dimension": "教育、学术与科研工作经历",
      "weight": 15,
      "score_1_to_5": 分数,
      "evidence": ["教育背景亮点", "海外经历优势"],
      "issues": ["教育背景不足", "海外经历缺陷"],
      "suggestion": "针对申请的具体改进建议"
    }},
    {{
      "dimension": "已取得科学研究及技术创新的成果及贡献",
      "weight": 30,
      "score_1_to_5": 分数,
      "evidence": ["主要学术成果", "创新贡献"],
      "issues": ["成果展示不足", "创新性不够"],
      "suggestion": "针对申请的具体改进建议"
    }},
    {{
      "dimension": "学术见解及技术成果独特性和原始创新性评价",
      "weight": 20,
      "score_1_to_5": 分数,
      "evidence": ["原创性体现", "独特性优势"],
      "issues": ["原创性不足", "独特性不够"],
      "suggestion": "针对申请的具体改进建议"
    }},
    {{
      "dimension": "发展潜力的评价",
      "weight": 20,
      "score_1_to_5": 分数,
      "evidence": ["与国家需求契合度", "发展前景"],
      "issues": ["契合度不足", "发展前景不明"],
      "suggestion": "针对申请的具体改进建议"
    }},
    {{
      "dimension": "申请工作设想和国内依托单位支持情况",
      "weight": 15,
      "score_1_to_5": 分数,
      "evidence": ["工作设想可行性", "依托单位支持"],
      "issues": ["工作设想不足", "支持不够充分"],
      "suggestion": "针对申请的具体改进建议"
    }}
  ],
  "aggregate": {{
    "weighted_total_100": 加权总分,
    "strengths": ["申请优势1", "申请优势2", "申请优势3", "申请优势4", "申请优势5"],
    "risks": ["申请风险1", "申请风险2", "申请风险3", "申请风险4", "申请风险5"],
    "priority_fixes_top5": ["具体可操作的改进建议1", "具体可操作的改进建议2", "具体可操作的改进建议3", "具体可操作的改进建议4", "具体可操作的改进建议5"]
  }}
}}

请严格按照上述格式输出，不要添加任何其他内容。所有建议必须针对国内青年人才申请，避免技术细节。"""

            try:
                json_response = effective_client.chat.completions.create(
                    model=effective_model,
                    messages=[
                        {"role": "system", "content": "你是一位资深的结构化评估专家，专门负责生成标准化的评估结果。"},
                        {"role": "user", "content": json_prompt}
                    ],
                    temperature=0.1,
                    max_tokens=3000,
                    stream=True
                )
                
                # 使用缓冲区流式处理
                json_result = ""
                for chunk_data in stream_response_with_buffer(json_response, 5, '结构化评估专家'):
                    yield chunk_data
                    # 提取内容用于后续处理
                    if isinstance(chunk_data, str) and 'content' in chunk_data:
                        try:
                            data = json.loads(chunk_data.replace('data: ', ''))
                            if 'content' in data:
                                json_result += data['content']
                        except:
                            pass
                
                # 若某些模型（如部分 qwen*）不返回流式 content，则回退一次非流式以获取完整结果
                if not json_result.strip():
                    try:
                        json_response_simple = effective_client.chat.completions.create(
                            model=effective_model,
                            messages=[
                                {"role": "system", "content": "你是一位资深的结构化评估专家，专门负责生成标准化的评估结果。"},
                                {"role": "user", "content": json_prompt}
                            ],
                            temperature=0.1,
                            max_tokens=3000,
                            stream=False
                        )
                        json_result = json_response_simple.choices[0].message.content or ""
                        # 以单条流内容的形式输出，便于前端显示这一轮内容
                        if json_result:
                            yield f"data: {safe_json_dumps({'round': 5, 'reviewer': '结构化评估专家', 'status': 'streaming', 'content': json_result})}\n\n"
                    except Exception as _fallback_err:
                        # 忽略回退失败，继续后续解析与降级处理
                        pass

                yield f"data: {safe_json_dumps({'round': 5, 'reviewer': '结构化评估专家', 'status': 'complete', 'message': '结构化评估完成'})}\n\n"
                
                # 解析结构化结果
                try:
                    import re
                    cleaned_result = json_result.strip()
                    if cleaned_result.startswith('```json'):
                        cleaned_result = cleaned_result[7:]
                    if cleaned_result.endswith('```'):
                        cleaned_result = cleaned_result[:-3]
                    cleaned_result = cleaned_result.strip()
                    
                    try:
                        review_data = json.loads(cleaned_result)
                    except json.JSONDecodeError:
                        json_match = re.search(r'\{.*\}', cleaned_result, re.DOTALL)
                        if json_match:
                            review_data = json.loads(json_match.group())
                        else:
                            review_data = {
                                "meta": {
                                    "title": "综合评估结果",
                                    "version": "v1.0",
                                    "review_time": datetime.now().isoformat()
                                },
                                "scores": [],
                                "aggregate": {
                                    "weighted_total_100": 0,
                                    "strengths": ["评估过程中出现错误"],
                                    "risks": ["无法解析评估结果"],
                                    "priority_fixes_top5": ["重新提交评估", "检查输入内容", "联系技术支持"]
                                }
                            }
                    
                    # 确保必要字段存在
                    if 'meta' not in review_data:
                        review_data['meta'] = {
                            "title": "综合评估结果",
                            "version": "v1.0",
                            "review_time": datetime.now().isoformat()
                        }
                    
                    if 'scores' not in review_data:
                        review_data['scores'] = []
                        
                    if 'aggregate' not in review_data:
                        review_data['aggregate'] = {
                            "weighted_total_100": 0,
                            "strengths": ["评估结果不完整"],
                            "risks": ["缺少聚合信息"],
                            "priority_fixes_top5": ["重新提交评估"]
                        }
                    
                    # 第六轮：政策搜索和建议
                    print("开始第六轮：政策搜索和建议")
                    print(f"结构化评估结果: {review_data.get('aggregate', {}).get('weighted_total_100', 'N/A')}")
                    yield f"data: {safe_json_dumps({'round': 6, 'reviewer': '政策分析专家', 'status': 'start', 'message': '正在搜索最新相关政策...'})}\n\n"
                    
                    policy_prompt = f"""作为政策分析专家，请搜索并分析以下申请材料相关的国家最新政策：

申请材料：{proposal_text}

请搜索以下方面的最新政策：
1. 国内青年人才项目的最新政策变化
2. 相关学科领域的最新支持政策
3. 人才引进和科研资助的最新政策
4. 创新创业的支持政策
5. 相关产业发展的政策导向

请提供：
1. 最新政策要点（2024-2025年）
2. 政策对申请人的影响分析
3. 基于政策的项目建议
4. 申请策略优化建议

请用自然语言详细回答，就像在政策咨询会议上发言一样。"""

                    try:
                        # 政策搜索/分析模型：优先使用用户传入模型
                        policy_response = policy_client.chat.completions.create(
                            model=effective_policy_model,
                            messages=[
                                {"role": "system", "content": "你是一位资深的政策分析专家，专门负责搜索和分析国家最新政策。"},
                                {"role": "user", "content": policy_prompt}
                            ],
                            temperature=0.2,
                            max_tokens=2000,
                            stream=True
                        )
                        
                        # 使用缓冲区流式处理
                        policy_result = ""
                        try:
                            for chunk_data in stream_response_with_buffer(policy_response, 6, '政策分析专家'):
                                yield chunk_data
                                # 提取内容用于后续处理
                                if isinstance(chunk_data, str) and chunk_data.startswith('data: '):
                                    try:
                                        data = json.loads(chunk_data.replace('data: ', ''))
                                        if 'content' in data:
                                            policy_result += data['content']
                                    except:
                                        pass
                        except Exception as stream_error:
                            print(f"政策搜索流式处理错误: {stream_error}")
                            # 如果流式处理失败，尝试非流式处理
                            try:
                                policy_response_simple = policy_client.chat.completions.create(
                                    model=effective_policy_model,
                                    messages=[
                                        {"role": "system", "content": "你是一位资深的政策分析专家，专门负责搜索和分析国家最新政策。"},
                                        {"role": "user", "content": policy_prompt}
                                    ],
                                    temperature=0.2,
                                    max_tokens=2000,
                                    stream=False
                                )
                                policy_result = policy_response_simple.choices[0].message.content
                                yield f"data: {safe_json_dumps({'round': 6, 'reviewer': '政策分析专家', 'status': 'streaming', 'content': policy_result})}\n\n"
                            except Exception as fallback_error:
                                print(f"政策搜索备用方案也失败: {fallback_error}")
                                policy_result = "政策搜索暂时不可用，请稍后重试。"
                                yield f"data: {safe_json_dumps({'round': 6, 'reviewer': '政策分析专家', 'status': 'streaming', 'content': policy_result})}\n\n"
                        
                        print(f"政策分析完成，结果长度: {len(policy_result)}")
                        yield f"data: {safe_json_dumps({'round': 6, 'reviewer': '政策分析专家', 'status': 'complete', 'message': '政策分析完成'})}\n\n"
                        
                        # 将政策分析结果添加到最终输出
                        if 'meta' in review_data:
                            review_data['meta']['policy_analysis'] = policy_result
                        
                        # 发送包含政策分析的最终结果
                        print("发送包含政策分析的最终结果")
                        yield f"data: {safe_json_dumps({'status': 'complete', 'review': review_data, 'policy_analysis': policy_result, 'scoring_criteria': {}})}\n\n"
                        
                    except Exception as e:
                        yield f"data: {safe_json_dumps({'round': 6, 'reviewer': '政策分析专家', 'status': 'error', 'message': f'政策搜索失败: {str(e)}'})}\n\n"
                        # 即使政策搜索失败，也发送评估结果
                        yield f"data: {safe_json_dumps({'status': 'complete', 'review': review_data, 'scoring_criteria': {}})}\n\n"
                    
                except Exception as e:
                    yield f"data: {safe_json_dumps({'status': 'error', 'message': f'解析评估结果失败: {str(e)}'})}\n\n"
                
            except Exception as e:
                yield f"data: {safe_json_dumps({'round': 5, 'reviewer': '结构化评估专家', 'status': 'error', 'message': f'结构化评估失败: {str(e)}'})}\n\n"
                return
                
        except Exception as e:
            yield f"data: {safe_json_dumps({'status': 'error', 'message': f'评估过程中出现错误: {str(e)}'})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type'
    })

@app.route('/evaluate', methods=['POST'])
def evaluate():
    try:
        data = request.json
        proposal_text = data.get('proposal_text', '').strip()
        
        if not proposal_text:
            return jsonify({'success': False, 'error': '请提供研究计划文本'})
        
        # 这里可以添加非流式评估逻辑
        return jsonify({'success': True, 'message': '请使用流式评估接口'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/extract_pdf', methods=['POST'])
def extract_pdf():
    try:
        pdf_url = ""
        pdf_file = None
        
        # 检查是JSON请求（URL）还是表单数据（文件上传）
        if request.content_type and 'application/json' in request.content_type:
            data = request.json
            pdf_url = data.get('pdf_url', '')
        else:
            # 处理表单数据文件上传
            pdf_file = request.files.get('pdf_file')
            # 同时检查表单数据中的URL
            pdf_url = request.form.get('pdf_url', '')
        
        if not pdf_url and not pdf_file:
            return jsonify({'error': '请提供PDF URL或上传PDF文件'}), 400
        
        text = ""
        
        if pdf_file:
            # 处理上传的文件
            if pdf_file.filename == '':
                return jsonify({'error': '未选择文件'}), 400
            
            if not pdf_file.filename.lower().endswith('.pdf'):
                return jsonify({'error': '请上传PDF文件'}), 400
            
            try:
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_file.read()))
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
            except Exception as e:
                return jsonify({'error': f'读取PDF文件时出错: {str(e)}'}), 400
        
        elif pdf_url:
            # 处理URL
            try:
                response = requests.get(pdf_url, timeout=30)
                response.raise_for_status()
                
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(response.content))
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
            except Exception as e:
                return jsonify({'error': f'从URL下载或读取PDF时出错: {str(e)}'}), 400
        
        if not text.strip():
            return jsonify({'error': '无法从PDF中提取文本'}), 400
        
        return jsonify({
            'success': True,
            'text': text.strip()
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=4091)
