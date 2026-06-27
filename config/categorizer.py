"""文档方向检测 — 基于关键词密度自动分类文档所属领域

类别:
  - construction_machinery: 挖掘机/装载机/推土机 等工程机械
  - optical_network: 光纤/ONU/OLT/GPON 等光通信
  - industrial_equipment: 通用工业设备
  - automotive: 汽车维修
  - unknown: 无法分类
"""
import re
from dataclasses import dataclass


CATEGORY_KEYWORDS = {
    "construction_machinery": {
        "keywords": [
            r'\b(?:挖掘机|excavator)\b',
            r'\b(?:装载机|loader)\b',
            r'\b(?:推土机|bulldozer)\b',
            r'\b(?:履带|crawler|track\s+shoe)\b',
            r'\b(?:动臂|boom)\b',
            r'\b(?:斗杆|arm|stick)\b',
            r'\b(?:铲斗|bucket)\b',
            r'\b(?:回转|swing)\b',
            r'\b(?:液压泵|hydraulic\s+pump)\b',
            r'\b(?:控制阀|control\s+valve)\b',
            r'\b(?:行走马达|travel\s+motor)\b',
            r'\b(?:回转马达|swing\s+motor)\b',
            r'\b(?:先导|pilot)\b',
            r'\b(?:减速器|reducer)\b',
            r'\bPC\d+[- ]?\d*\b',           # PC200-6 类机型
            r'\bDH\d+[- ]?\d*\b',           # DH220-5
            r'\bZX\d+[- ]?\d*\b',           # ZX200
            r'\bSK\d+[- ]?\d*\b',           # SK200
            r'\bCAT\d+\b',                  # CAT320
        ],
        "weight": 3.0,
    },
    "optical_network": {
        "keywords": [
            r'\bONU\b', r'\bOLT\b', r'\bONT\b',
            r'\bGPON\b', r'\bEPON\b', r'\bXG-PON\b',
            r'\b(?:光网络|optical\s+network)\b',
            r'\b(?:光纤|optical\s+fiber)\b',
            r'\b(?:分光器|splitter)\b',
            r'\b(?:光模块|SFP|XFP|QSFP)\b',
            r'\b(?:波长|wavelength)\b',
            r'\b(?:灵敏度|sensitivity)\b',
            r'\b(?:光功率|optical\s+power)\b',
            r'\b(?:接收|receiver)\b',
            r'\b(?:发射|transmitter)\b',
            r'\bITU-T\s+G\.\d+\b',
        ],
        "weight": 2.5,
    },
    "automotive": {
        "keywords": [
            r'\b(?:发动机|engine)\b',
            r'\b(?:变速箱|transmission)\b',
            r'\b(?:制动|brake)\b',
            r'\b(?:离合器|clutch)\b',
            r'\b(?:底盘|chassis)\b',
            r'\b(?:悬架|suspension)\b',
        ],
        "weight": 1.0,
        "exclude_if": "construction_machinery",  # 工程机械也有发动机，优先归工程机械
    },
    "industrial_equipment": {
        "keywords": [
            r'\b(?:电机|motor)\b',
            r'\b(?:变频器|inverter)\b',
            r'\b(?:PLC|可编程)\b',
            r'\b(?:传感器|sensor)\b',
            r'\b(?:执行器|actuator)\b',
        ],
        "weight": 1.5,
    },
}


@dataclass
class DocCategory:
    category: str
    confidence: float
    matched_keywords: list[str]


def detect_category(text: str, sample_size: int = 5000) -> DocCategory:
    """基于关键词匹配密度检测文档类别
    
    sample_size: 采样字符数（取文档前 N 字符+随机段落）
    """
    if len(text) > sample_size:
        # 取头 2/3 + 尾 1/3
        head = text[:int(sample_size * 0.7)]
        tail = text[-int(sample_size * 0.3):]
        sample = head + tail
    else:
        sample = text

    scores = {}
    matched_all = {}

    for cat, config in CATEGORY_KEYWORDS.items():
        score = 0.0
        matched = []
        for pattern in config["keywords"]:
            matches = re.findall(pattern, sample, re.IGNORECASE)
            if matches:
                # 去重计数
                unique_matches = set(m.lower() for m in matches)
                score += len(unique_matches) * config.get("weight", 1.0)
                matched.extend(unique_matches)
        if score > 0:
            scores[cat] = score
            matched_all[cat] = matched

    if not scores:
        return DocCategory("unknown", 0.0, [])

    # 找出最高分类别
    best_cat = max(scores, key=scores.get)

    # 排除规则
    config = CATEGORY_KEYWORDS.get(best_cat, {})
    if "exclude_if" in config:
        exclude_cat = config["exclude_if"]
        if exclude_cat in scores and scores[exclude_cat] > scores[best_cat] * 0.5:
            best_cat = exclude_cat

    # 归一化置信度
    total = sum(scores.values())
    confidence = min(scores[best_cat] / max(total, 1), 1.0)

    return DocCategory(best_cat, round(confidence, 2), matched_all.get(best_cat, [])[:10])


def categorize_document(text: str) -> str:
    """快捷函数：返回 category 字符串"""
    return detect_category(text).category
