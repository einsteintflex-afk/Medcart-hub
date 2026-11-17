from sqlalchemy.orm import Session

from ..models import AuditLog


def audit(db: Session, actor_id: int | None, action: str, entity: str, entity_id=None,
          patient_id: int | None = None, ip: str | None = None, **detail) -> None:
    db.add(AuditLog(actor_id=actor_id, action=action, entity=entity,
                    entity_id=str(entity_id) if entity_id is not None else None,
                    patient_id=patient_id, ip=ip, detail=detail))
