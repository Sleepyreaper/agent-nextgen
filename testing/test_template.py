#!/usr/bin/env python
"""Debug template parsing error."""

from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError

try:
    env = Environment(loader=FileSystemLoader('web/templates'))
    template = env.get_template('application.html')
    print("✅ Template loaded successfully!")
except TemplateSyntaxError as e:
    print(f"❌ Template Syntax Error:")
    print(f"   File: {e.filename}")
    print(f"   Line: {e.lineno}")
    print(f"   Message: {e.message}")
    print(f"   Full: {e}")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
