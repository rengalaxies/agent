"""Select persistence explicitly; never fall back to local temporary storage."""
import os
from services.audit_pg import AuditUnavailable
BACKEND = os.environ.get("DMRP_AUDIT_BACKEND", "postgres")
if BACKEND == "object_storage_volume":
    from services.audit_volume import audit_record, audit_ready
elif BACKEND == "postgres":
    from services.audit_pg import audit_record, audit_ready
else:
    raise RuntimeError("Unsupported audit backend")
