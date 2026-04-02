import sys
import os
import datetime

# Add the root project directory to the path so we can import src modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.db.session import SessionLocal
from src.db.models import IncidentReport, Company, Equipment

def seed_reports():
    with SessionLocal() as db:
        company = db.query(Company).first()
        if not company:
            company = Company(name="Demo Manufacturing Inc", )
            db.add(company)
            db.flush()
            print("Created default company: Demo Manufacturing Inc")

        equipments = [
            {"id": "CMP-01 (Air Compressor)", "name": "CMP-01 Air Compressor", "equipment_type": "compressor"},
            {"id": "CHL-04 (Water Chiller)", "name": "CHL-04 Water Chiller", "equipment_type": "chiller"},
            {"id": "CVY-12 (Main Transfer Belt)", "name": "CVY-12 Main Transfer Belt", "equipment_type": "conveyor"}
        ]
        for eq in equipments:
            if not db.query(Equipment).filter(Equipment.id == eq["id"]).first():
                db.add(Equipment(company_id=company.id, **eq))
        db.flush()

        reports = [
            {
                "id": "IR-2024-017",
                "title": "Machine stopped due to High Pressure Trip",
                "process_line": "Line A",
                "asset_id": "CMP-01 (Air Compressor)",
                "symptoms": ["Machine stopped due to High Pressure Trip."],
                "trigger_condition": "Discharge pressure exceeded threshold (12.8 bar).",
                "initial_assumption": "Internal compressor mechanical failure.",
                "root_cause": "Downstream valve (V-204) partially closed, causing backpressure.",
                "resolution": "Valve reopened and discharge pressure normalized.",
                "diagnosis_time_traditional": 45,
                "diagnosis_time_structured": 18,
                "escalation_required": False,
                "created_at": datetime.datetime(2024, 2, 12, 14, 35)
            },
            {
                "id": "IR-2024-022",
                "title": "Temperature Spikes on Chiller Unit",
                "process_line": "Line B",
                "asset_id": "CHL-04 (Water Chiller)",
                "symptoms": ["Intermittent high-temperature alarms.", "Cooling capacity dropping."],
                "trigger_condition": "Outgoing water temp hit 12°C (Set point 7°C).",
                "initial_assumption": "Refrigerant leak or compressor failure.",
                "root_cause": "Cooling tower fan VFD failure reducing heat rejection.",
                "resolution": "VFD drive replaced, and fan speed restored.",
                "diagnosis_time_traditional": 120,
                "diagnosis_time_structured": 35,
                "escalation_required": True,
                "escalation_level": 2,
                "created_at": datetime.datetime(2024, 2, 28, 9, 15)
            },
            {
                "id": "IR-2024-031",
                "title": "Conveyor Belt Motor Tripping",
                "process_line": "Packaging",
                "asset_id": "CVY-12 (Main Transfer Belt)",
                "symptoms": ["Motor overload trips after 10 mins of operation."],
                "trigger_condition": "Motor breaker tripped twice in one shift.",
                "initial_assumption": "Motor winding degradation or bearing failure.",
                "root_cause": "Upstream feeder dropping excessive material, overloading the belt.",
                "resolution": "Feeder speed calibrated to match conveyor capacity.",
                "diagnosis_time_traditional": 60,
                "diagnosis_time_structured": 12,
                "escalation_required": False,
                "created_at": datetime.datetime(2024, 3, 5, 22, 40)
            }
        ]

        for r_data in reports:
            existing = db.query(IncidentReport).filter(IncidentReport.id == r_data["id"]).first()
            if not existing:
                report = IncidentReport(
                    company_id=company.id,
                    **r_data
                )
                db.add(report)
        
        db.commit()
        print("Successfully seeded sample reports.")

if __name__ == "__main__":
    seed_reports()
