# -*- coding: utf-8 -*-
"""收款结算单：确定性核算 + 渲染引擎（自 settlement-statement skill 包移植）。

分层约束：LLM 只做自由文本→结构化 JSON 的格式整理（见 llm/prompts.py），
金额计算与版式渲染全部在本包内确定性完成——同样输入永远同样输出，
LLM 与引擎的边界是「只搬运数字，不做任何算术」。
"""
