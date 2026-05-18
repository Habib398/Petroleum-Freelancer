from __future__ import annotations

from flask import abort, render_template

from services.brand import get_brand


_MODULES = {
    "sasisopa": "SASISOPA",
    "sgm":      "SGM",
}

def register(app):
    ctx = app.extensions["ctx"]
    login_required = ctx.login_required

    def _admin_or_403() -> dict:
        me = ctx.get_me()
        if not me:
            abort(401)
        if (me.get("role") or "").lower() != "admin":
            abort(403)
        return me

    def _render_page(module_key: str):
        if module_key not in _MODULES:
            abort(404)
        _admin_or_403()
        brand = (get_brand() or "consulting").lower()
        return render_template(
            "docx_templates/admin_upload.html",
            module_key=module_key,
            module_label=_MODULES[module_key],
            admin_base=f"/admin/{module_key}/docs",
            back_url=f"/admin/{module_key}/docs",
            back_label=f"Volver a {_MODULES[module_key]}",
            brand=brand,
            brand_label="Petroleum" if brand == "petroleum" else "Consulting",
        )

    @app.get("/admin/sasisopa/docx-templates")
    @login_required
    def admin_sasisopa_docx_templates_ui():
        return _render_page("sasisopa")

    @app.get("/admin/sgm/docx-templates")
    @login_required
    def admin_sgm_docx_templates_ui():
        return _render_page("sgm")
