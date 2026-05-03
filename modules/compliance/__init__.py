# modules/compliance/__init__.py
# Dominio: Gestión documental y normativa (ISO, SASISOPA, SGM, CAPA, Auditorías).
# Incluye: documentos generales, documental avanzado, compliance, SASISOPA,
#          SGM, trámites/normativas y CAPA (no conformidades).

from routes.docs import register as register_docs
from routes.compliance import register as register_compliance
from routes.sasisopa_docs import register as register_sasisopa  # usa documental_docs internamente
from routes.sgm_docs import register as register_sgm            # usa documental_docs internamente
from routes.tramites_normativas import register as register_tramites
from routes.capa import register as register_capa
from routes.audit import register as register_audit


def register(app):
    register_docs(app)
    register_compliance(app)
    register_sasisopa(app)
    register_sgm(app)
    register_tramites(app)
    register_capa(app)
    register_audit(app)
