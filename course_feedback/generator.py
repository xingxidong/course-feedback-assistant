"""Deterministic Chinese course-feedback generator with an optional OpenAI-compatible LLM."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen

import yaml

SYSTEM_PROMPT = """你是一名严谨、真诚的高中物理教师。请根据课程知识点和学生表现，写一份发给家长的课程反馈。固定分为“课程内容”和“课堂表现”两段。表达客观、委婉、具体；不比较学生，不使用“笨、差、没救”等词；既指出问题，也给出可执行建议。课程内容逐项编号，保留物理术语。只输出正文。"""

def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _topic_sentence(index: int, topic: str, action: str = "学习") -> str:
    t = topic.strip().rstrip("。；;")
    maps = [
        ("动态平衡", "理解物体在缓慢变化过程中始终满足平衡条件的特点，掌握力的大小和方向变化的判断方法"),
        ("晾衣架", "分析绳子夹角变化与绳中张力变化之间的关系，强化几何关系与平衡条件的结合"),
        ("共点力", "规范确定研究对象、受力分析、建立坐标系、分解力和列平衡方程的求解步骤"),
        ("动量守恒", "理解系统动量守恒的条件，掌握根据初、末状态建立动量守恒方程的方法"),
        ("人船", "分析人与船运动过程中的动量关系和位移关系，掌握人船模型的基本处理方法"),
        ("流体", "理解连续流体在一段时间内的质量和动量变化，掌握运用动量定理分析流体冲击问题的方法"),
        ("回旋加速器", "理解磁场控制运动轨迹、电场提供加速作用以及交变电场周期与回旋周期的关系"),
        ("磁聚焦", "分析不同方向入射的带电粒子在特定边界条件下形成聚焦的轨迹规律"),
        ("磁发散", "分析带电粒子经过磁场后的轨迹分布，提升几何关系与圆周运动规律的综合运用能力"),
        ("带电粒子", "掌握洛伦兹力、轨道半径、运动周期以及圆心和运动轨迹的确定方法"),
        ("折射", "掌握折射率、入射角和折射角之间的关系，并能运用折射定律分析光路"),
        ("全反射", "理解全反射发生的条件，掌握临界角的计算和相关光路分析方法"),
        ("比结合能", "理解比结合能与原子核稳定性之间的关系，并结合核反应进行分析和计算"),
        ("电子跃迁", "掌握电子在不同能级间跃迁时吸收或释放光子的规律，以及光子能量的相关计算"),
        ("热学", "梳理分子动理论、气体实验定律和热力学定律，巩固典型问题的分析方法"),
        ("电场", "梳理电场强度、电势、电势差和电势能等概念，训练带电粒子在电场中的受力与运动分析"),
        ("闭合电路", "掌握电动势、内阻、路端电压和电流之间的关系，并分析电路动态变化与功率问题"),
        ("电流", "理解电流的形成条件、电流强度及其微观意义，巩固相关表达式的运用"),
    ]
    detail = next((v for k, v in maps if k in t), f"梳理{t}的基本概念、核心规律和典型题型，进一步规范分析与计算过程")
    return f"{index}.{action}{t}，{detail}。"

def _performance(notes: str, name: str) -> str:
    n = re.sub(r"\s+", "", notes)
    strengths, issues, advice = [], [], []
    if any(x in n for x in ["认真", "专注", "听课好"]): strengths.append("听课认真，能够跟随课堂思路进行分析")
    if any(x in n for x in ["思维好", "思维活跃", "聪明", "理解快"]): strengths.append("物理思维较好，对新模型和关键关系的理解较快")
    if any(x in n for x in ["活泼", "积极"]): strengths.append("课堂参与积极，愿意表达自己的思路")
    if any(x in n for x in ["追问", "打破砂锅", "问到底"]): strengths.append("对不理解的问题会主动追问，具有深入钻研的意识")
    if any(x in n for x in ["笔记", "记录"]): strengths.append("能够及时、细致地记录课堂笔记")
    if any(x in n for x in ["进步", "提升"]): strengths.append("近期学习已有一定进步")
    if not strengths: strengths.append("能够参与课堂学习并跟随主要教学进度")

    if any(x in n for x in ["不稳定", "稳定"]): issues.append("目前知识运用和考试发挥还不够稳定")
    if any(x in n for x in ["基础差", "基础薄弱", "不扎实", "基础不扎实"]): issues.append("前期部分基础知识和基本方法仍有缺口")
    if any(x in n for x in ["慢", "接受速度"]): issues.append("对新知识的理解和消化需要更充分的时间")
    if any(x in n for x in ["细节", "粗心"]): issues.append("做题时容易在条件分析、计算或规范表达等细节上失分")
    if any(x in n for x in ["不踏实", "浮躁", "坐不住", "分心"]): issues.append("学习过程中的专注度和落实程度还需要加强")
    if any(x in n for x in ["不思考", "不愿思考", "不看题", "不认真看"]): issues.append("面对题目时缺少耐心，审题和持续思考不够充分")
    if any(x in n for x in ["不背公式", "公式不熟"]): issues.append("基本公式和常用结论掌握得不够熟练")
    if any(x in n for x in ["作业不好", "作业完成不好", "作业不认真"]): issues.append("课后作业的完成质量不够理想，课堂内容没有得到及时巩固")
    if any(x in n for x in ["畏惧", "害怕", "畏难"]): issues.append("面对物理问题时存在一定畏难情绪，容易低估自己的理解能力")
    if any(x in n for x in ["提分一般", "提升不上", "不温不火"]): issues.append("目前知识积累向考试得分的转化还不够明显")

    if any(x in n for x in ["基础", "公式"]): advice.append("有计划地回补基础知识，整理并熟记常用公式")
    if any(x in n for x in ["细节", "粗心", "不看题", "审题"]): advice.append("做题时按照审题、建模、列式、计算和检查的步骤规范完成")
    if any(x in n for x in ["作业"]): advice.append("提高作业完成质量，独立完成并及时订正错误")
    if any(x in n for x in ["慢", "笔记"]): advice.append("在整理笔记后增加主动回忆和典型题的重复训练")
    if any(x in n for x in ["畏惧", "畏难"]): advice.append("从基础模型入手积累成功经验，增强独立尝试的信心")
    if any(x in n for x in ["不稳定", "不踏实", "坐不住", "分心"]): advice.append("把课堂理解落实到稳定、持续的课后训练中")
    if not advice: advice.append("课后及时整理课堂内容，并通过典型题巩固解题方法")

    first = f"{name}本节课" + "，".join(strengths[:2]) + "。"
    middle = ("当前" + "，".join(issues[:3]) + "。") if issues else "整体课堂表现较好。"
    end = "接下来应" + "，并".join(advice[:3]) + "，逐步提高解题的熟练度、准确性和稳定性。"
    return first + middle + end

def deterministic_generate(name: str, course_intro: str, topics: list[str], notes: str) -> str:
    action = "预习" if "预习" in course_intro and "复习" not in course_intro else "复习" if "复习" in course_intro else "学习"
    topic_text = "".join(_topic_sentence(i, t, action) for i, t in enumerate(topics, 1))
    intro = course_intro.strip().rstrip("。")
    return f"课程内容：{intro}。{topic_text}\n\n课堂表现：{_performance(notes, name)}"

def _keychain_secret(service: str, account: str) -> str:
    try:
        result = subprocess.run(["/usr/bin/security", "find-generic-password", "-w", "-s", service, "-a", account],
                                capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""

def _model_configs() -> list[dict]:
    if os.getenv("COURSE_FEEDBACK_DISABLE_LLM") == "1":
        return []
    configs: list[dict] = []
    env_base = os.getenv("COURSE_FEEDBACK_API_BASE", "").rstrip("/")
    env_key = os.getenv("COURSE_FEEDBACK_API_KEY", "")
    env_model = os.getenv("COURSE_FEEDBACK_MODEL", "")
    if env_base and env_key and env_model:
        configs.append({"base": env_base, "key": env_key, "model": env_model, "provider": "environment"})
    else:
        try:
            hermes = yaml.safe_load((Path.home() / ".hermes" / "config.yaml").read_text()) or {}
            model_spec = hermes.get("model", {})
            provider_name = model_spec.get("provider", "")
            model = model_spec.get("default", "")
            providers = hermes.get("providers", {})
            if provider_name == "openai":
                provider = providers.get("openai", {})
            elif provider_name.startswith("openai_compatible:"):
                wanted = provider_name.split(":", 1)[1]
                provider = next((p for p in providers.get("openai_compatible", []) if p.get("name") == wanted), {})
            else:
                provider = {}
            base, key = str(provider.get("base_url", "")).rstrip("/"), provider.get("api_key", "")
            if base and key and model:
                configs.append({"base": base, "key": key, "model": model, "provider": provider_name})
        except Exception:
            pass
    deepseek_key = _keychain_secret("课评助手.DeepSeek", "deepseek-api")
    if deepseek_key and not any(c["provider"] == "deepseek-backup" or "deepseek" in c["base"] for c in configs):
        configs.append({"base": "https://api.deepseek.com/v1", "key": deepseek_key,
                        "model": "deepseek-chat", "provider": "deepseek-backup"})
    return configs

def model_info() -> dict:
    configs = _model_configs()
    if not configs:
        return {"enabled": False, "model": "本地规则引擎", "provider": "local", "fallback": ""}
    return {"enabled": True, "model": configs[0]["model"], "provider": configs[0]["provider"],
            "fallback": configs[1]["model"] if len(configs) > 1 else "本地规则引擎"}

def _llm_generate(name: str, course_intro: str, topics: list[str], notes: str) -> str | None:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"学生：{name}\n课程概述：{course_intro}\n知识点：{json.dumps(topics, ensure_ascii=False)}\n课堂观察：{notes}"},
    ]
    for config in _model_configs():
        payload = {"model": config["model"], "messages": messages}
        req = Request(config["base"] + "/chat/completions", data=json.dumps(payload).encode(),
                      headers={"Authorization": "Bearer " + config["key"], "Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=90) as response:
                result = json.loads(response.read())
            text = result["choices"][0]["message"]["content"].strip()
            if "课程内容" in text and "课堂表现" in text:
                return text
        except Exception:
            continue
    return None

def generate(name: str, course_intro: str, topics: list[str], notes: str) -> str:
    return _llm_generate(name, course_intro, topics, notes) or deterministic_generate(name, course_intro, topics, notes)
