from enum import StrEnum


class QuestionIntent(StrEnum):
    CONCEPTUAL = "conceptual"
    DEVICE_INCIDENT = "device_incident"


INCIDENT_MARKERS = (
    "我的", "我们的", "生产", "线上", "实例", "设备", "服务器", "宕机", "告警",
    "报错", "连接不上", "无法连接", "突然", "延迟飙升", "内存爆了", "无法启动",
)


def classify_question(question: str) -> QuestionIntent:
    normalized = question.lower()
    if any(marker in normalized for marker in INCIDENT_MARKERS):
        return QuestionIntent.DEVICE_INCIDENT
    return QuestionIntent.CONCEPTUAL

