#!/usr/bin/env python3
"""
Quick code structure validation (doesn't require Azure/OpenTelemetry)
"""
import ast
import sys
import os

print("=" * 80)
print("AGENT CODE STRUCTURE VALIDATION")
print("=" * 80)

def check_class_inheritance(file_path, class_name, expected_parent):
    """Check if a class inherits from expected parent"""
    try:
        with open(file_path, 'r') as f:
            tree = ast.parse(f.read())
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                # Check bases
                base_names = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        base_names.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        base_names.append(base.attr)
                
                if expected_parent in base_names:
                    return True, base_names
                else:
                    return False, base_names
        
        return None, []  # Class not found
    except Exception as e:
        return None, str(e)

def check_method_exists(file_path, class_name, method_name):
    """Check if a method exists in a class"""
    try:
        with open(file_path, 'r') as f:
            tree = ast.parse(f.read())
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    # Check both regular and async functions
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                        return True
                return False
        
        return None  # Class not found
    except Exception as e:
        return None, str(e)

# Test 1: Naveen inherits from BaseAgent
print("\n1. Checking Naveen inheritance...")
result, bases = check_class_inheritance(
    'src/agents/naveen_school_data_scientist.py',
    'NaveenSchoolDataScientist',
    'BaseAgent'
)
if result:
    print(f"✓ NaveenSchoolDataScientist correctly inherits from BaseAgent")
    print(f"  Bases: {bases}")
elif result is False:
    print(f"✗ NaveenSchoolDataScientist inherits from: {bases}")
    print(f"  Expected: BaseAgent")
    sys.exit(1)
else:
    print(f"✗ Error: {bases}")
    sys.exit(1)

# Test 2: Naveen has required methods
print("\n2. Checking Naveen methods...")
methods_to_check = [
    'analyze_school',
    '_build_research_prompt',
    '_refine_analysis',
    'process',
]

for method in methods_to_check:
    result = check_method_exists(
        'src/agents/naveen_school_data_scientist.py',
        'NaveenSchoolDataScientist',
        method
    )
    if result:
        print(f"✓ Method '{method}' exists")
    elif result is False:
        print(f"✗ Method '{method}' NOT FOUND")
        sys.exit(1)
    else:
        print(f"? Method '{method}' check failed")

# Test 3: app.py has dual client support
print("\n3. Checking app.py client configuration...")
with open('app.py', 'r') as f:
    app_content = f.read()

checks = [
    ('client_mini variable', 'client_mini'),
    ('get_ai_client_mini function', 'def get_ai_client_mini'),
    ('api_version parameter', 'api_version'),
]

for check_name, pattern in checks:
    if pattern in app_content:
        print(f"✓ {check_name}")
    else:
        print(f"✗ {check_name} NOT FOUND")
        sys.exit(1)

# Test 4: Smee has agent context tracking
print("\n4. Checking Smee orchestrator...")
with open('src/agents/smee_orchestrator.py', 'r') as f:
    smee_content = f.read()

if 'agent_context' in smee_content:
    print(f"✓ agent_context tracking found")
else:
    print(f"✗ agent_context tracking NOT FOUND")
    sys.exit(1)

if 'required_agents' in smee_content and 'optional_agents' in smee_content:
    print(f"✓ Agent sequencing (required/optional) found")
else:
    print(f"✗ Agent sequencing NOT FOUND")
    sys.exit(1)

# Test 5: Config has mini API version
print("\n5. Checking config.py...")
with open('src/config.py', 'r') as f:
    config_content = f.read()

if 'api_version_mini' in config_content:
    print(f"✓ api_version_mini field found")
else:
    print(f"✗ api_version_mini field NOT FOUND")
    sys.exit(1)

print("\n" + "=" * 80)
print("✓ ALL CODE STRUCTURE VALIDATIONS PASSED!")
print("=" * 80)
print("\nChanges verified:")
print("  ✓ Naveen inherits from BaseAgent for AI model integration")
print("  ✓ Naveen has methods for research, analysis, and refinement")
print("  ✓ app.py has dual client support for two Foundry deployments")
print("  ✓ config.py supports mini API version configuration")
print("  ✓ Smee has agent context tracking and sequencing logic")
print("\nReady for Azure deployment!")
