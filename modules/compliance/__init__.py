# modules/compliance/__init__.py
# Dominio: Gestión documental y normativa (ISO, SASISOPA, SGM, CAPA, Auditorías).
# Incluye: documentos generales, compliance, SASISOPA, SGM,
#          trámites/normativas, CAPA (no conformidades) y auditorías.
# Nota: documental_docs.py es una fábrica interna usada por sasisopa y sgm.

from modules.compliance.docs import register as register_docs
from modules.compliance.compliance import register as register_compliance
from modules.compliance.sasisopa_docs import register as register_sasisopa  # usa documental_docs internamente
from modules.compliance.sgm_docs import register as register_sgm            # usa documental_docs internamente
from modules.compliance.tramites_normativas import register as register_tramites
from modules.compliance.capa import register as register_capa
from modules.compliance.audit import register as register_audit
from modules.compliance.docx_templates import register as register_docx_templates  # nuevo motor DOCX <<VAR>>


def register(app):
    register_docs(app)
    register_compliance(app)
    register_sasisopa(app)
    register_sgm(app)
    register_tramites(app)
    register_capa(app)
    register_audit(app)
    register_docx_templates(app)
