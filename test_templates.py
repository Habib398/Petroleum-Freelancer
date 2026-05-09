import os
from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader('templates'))
errors = []
for root, dirs, files in os.walk('templates'):
    for file in files:
        if file.endswith('.html'):
            path = os.path.join(root, file)
            rel_path = os.path.relpath(path, 'templates').replace(os.sep, '/')
            try:
                env.get_template(rel_path)
            except Exception as e:
                errors.append(f"{rel_path}: {e}")

if errors:
    for e in errors:
        print(e)
else:
    print('No errors found.')
