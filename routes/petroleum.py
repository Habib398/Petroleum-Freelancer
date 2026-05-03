from flask import redirect, session

from routes.auth import login_required, role_required


def register(app):
    """Petroleum module.

    Separate UI + routes from Consulting/HME.
    Uses the same users/auth, but different features/menus.
    """

    @app.get('/petroleum')
    def petroleum_entry():
        """Entry point that activates the Petroleum brand.

        UI is shared with Consulting (same sidebar/layout), but data are isolated by `brand`.
        """
        session['brand'] = 'petroleum'
        if not session.get('user_id'):
            return redirect('/login')
        return redirect('/mod/dashboard')

    @app.get('/petroleum/menu')
    @login_required
    @role_required('admin', 'jefe_estacion', 'operador')
    def petroleum_menu():
        # Backwards compatibility route. Admin sees the dedicated Petroleum hub; staff keeps the shared dashboard/menu.
        role = (session.get('role') or '').strip().lower()
        if role == 'admin':
            return redirect('/admin/menu')
        return redirect('/staff/menu')

    @app.get('/petroleum/inspecciones')
    @login_required
    @role_required('admin', 'jefe_estacion', 'operador')
    def petroleum_inspecciones():
        return redirect('/mod/activities')

    @app.get('/petroleum/alertas')
    @login_required
    @role_required('admin', 'jefe_estacion', 'operador')
    def petroleum_alertas():
        return redirect('/mod/alerts')

    @app.get('/petroleum/reportes')
    @login_required
    @role_required('admin', 'jefe_estacion')
    def petroleum_reportes():
        return redirect('/mod/reports')

    @app.get('/petroleum/catalogos')
    @login_required
    @role_required('admin')
    def petroleum_catalogos():
        return redirect('/admin/users')
