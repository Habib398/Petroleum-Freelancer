from modules.compliance.documental_docs import register_module


def register(app):
    register_module(app, module_key='sasisopa', module_label='SASISOPA', template_folder='documental_docs', route_segment='sasisopa')
