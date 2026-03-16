from src.graph import diagnosis_router

state1 = {"problem_description": "New incident (no problem described yet).", "incident_card": {"normalized_summary": "New Incident"}, "confidence": 0.99}
print(diagnosis_router(state1)) # should be question_generation

state2 = {"problem_description": "hello", "confidence": 0.9}
print(diagnosis_router(state2)) # should be question_generation

state3 = {"problem_description": "Pump is broken", "confidence": 0.9}
print(diagnosis_router(state3)) # should be decision_brief
