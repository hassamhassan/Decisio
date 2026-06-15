import asyncio
from src.graph import build_graph
intake_graph = build_graph()
state = intake_graph.invoke({
    "report": "The pump PMP-01 is leaking fluid rapidly.",
    "confidence": 0.0,
    "company_id": 4,
    "questions_asked_count": 0,
    "current_diagnostic_step": 1,
})
print("Confidence:", state.get("confidence"))
print("Hypotheses confidence:", state.get("hypotheses", [{}])[0].get("probability") if state.get("hypotheses") else None)
