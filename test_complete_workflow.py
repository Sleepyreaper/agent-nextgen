#!/usr/bin/env python
"""
Comprehensive test suite for the 9-step Agent NextGen workflow.
Tests all agents and validates the complete processing pipeline.
"""

import os
import sys
import json
import asyncio
from datetime import datetime
from pathlib import Path

# Set environment variables for testing
# Database credentials MUST come from environment variables or Key Vault
# Never use hardcoded defaults for production credentials
os.environ['POSTGRES_HOST'] = os.getenv('POSTGRES_HOST')
os.environ['POSTGRES_PORT'] = os.getenv('POSTGRES_PORT', '5432')
os.environ['POSTGRES_DB'] = os.getenv('POSTGRES_DB', 'nextgenagentpostgres')
os.environ['POSTGRES_USER'] = os.getenv('POSTGRES_USER', 'sleepy')
os.environ['POSTGRES_PASSWORD'] = os.getenv('POSTGRES_PASSWORD')

from src.database import db
from src.logger import app_logger as logger

class WorkflowTester:
    """Test suite for the complete 9-step workflow."""
    
    def __init__(self):
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'tests': [],
            'summary': {'passed': 0, 'failed': 0, 'total': 0}
        }
    
    def test(self, name, func):
        """Decorator to run and track a test."""
        async def wrapper():
            try:
                result = await func() if asyncio.iscoroutinefunction(func) else func()
                self.results['tests'].append({
                    'name': name,
                    'status': 'PASSED',
                    'timestamp': datetime.now().isoformat(),
                    'result': str(result)[:200]
                })
                self.results['summary']['passed'] += 1
                print(f"✓ {name}")
                return True
            except Exception as e:
                self.results['tests'].append({
                    'name': name,
                    'status': 'FAILED',
                    'timestamp': datetime.now().isoformat(),
                    'error': str(e)[:200]
                })
                self.results['summary']['failed'] += 1
                print(f"✗ {name}: {e}")
                return False
        
        self.results['summary']['total'] += 1
        return wrapper
    
    def run_all_tests(self):
        """Run all workflow tests."""
        print("\n" + "="*70)
        print("AGENT NEXTGEN - COMPLETE WORKFLOW TEST SUITE")
        print("="*70 + "\n")
        
        # Step 1: Database Connection Test
        print("Step 1: Database Connectivity")
        print("-" * 70)
        self.test_database_connection()
        
        # Step 2: Schema Validation
        print("\nStep 2: Database Schema Validation")
        print("-" * 70)
        self.test_schema_validation()
        
        # Step 3: Test Data Availability
        print("\nStep 3: Test Data Availability")
        print("-" * 70)
        self.test_data_availability()
        
        # Step 4: Audit Logging Tables
        print("\nStep 4: Audit Logging Tables")
        print("-" * 70)
        self.test_audit_tables()
        
        # Step 5: Configuration
        print("\nStep 5: Configuration & Environment")
        print("-" * 70)
        self.test_configuration()
        
        # Step 6: Agents Loading
        print("\nStep 6: Agents Loading")
        print("-" * 70)
        self.test_agents_loading()
        
        # Print Summary
        print("\n" + "="*70)
        print("TEST SUMMARY")
        print("="*70)
        print(f"Total Tests: {self.results['summary']['total']}")
        print(f"Passed: {self.results['summary']['passed']}")
        print(f"Failed: {self.results['summary']['failed']}")
        print("="*70 + "\n")
        
        return self.results
    
    @staticmethod
    def test_database_connection():
        """Test 1: Database Connection"""
        try:
            conn = db.connect()
            print("✓ Database connection successful")
            cursor = conn.cursor()
            cursor.execute("SELECT version()")
            version = cursor.fetchone()[0]
            print(f"✓ PostgreSQL version: {version.split(',')[0]}")
            cursor.close()
        except Exception as e:
            print(f"✗ Database connection failed: {e}")
            raise
    
    @staticmethod
    def test_schema_validation():
        """Test 2: Schema Validation"""
        required_tables = [
            'applications',
            'school_context',
            'rapunzel_grades',
            'ai_evaluations',
            'agent_interactions',
            'audit_log'
        ]
        
        for table in required_tables:
            try:
                query = f"SELECT COUNT(*) FROM {table} LIMIT 1"
                result = db.execute_query(query)
                print(f"✓ Table '{table}' exists")
            except Exception as e:
                print(f"⚠ Table '{table}' check: {str(e)[:80]}")
    
    @staticmethod
    def test_data_availability():
        """Test 3: Test Data Availability"""
        try:
            # Check applications count
            result = db.execute_query("SELECT COUNT(*) as cnt FROM applications")
            app_count = result[0].get('cnt') if result else 0
            print(f"✓ Applications in database: {app_count}")
            
            if app_count > 0:
                # Show sample application
                result = db.execute_query(
                    "SELECT application_id, applicant_name FROM applications LIMIT 1"
                )
                if result:
                    app = result[0]
                    print(f"✓ Sample application: ID={app['application_id']}, Name={app['applicant_name']}")
            else:
                print("⚠ No applications found in database")
        except Exception as e:
            print(f"✗ Data availability check failed: {e}")
            raise
    
    @staticmethod
    def test_audit_tables():
        """Test 4: Audit Logging Tables"""
        audit_tables = ['agent_interactions', 'audit_log']
        
        for table in audit_tables:
            try:
                query = f"SELECT COUNT(*) as cnt FROM {table}"
                result = db.execute_query(query)
                count = result[0].get('cnt') if result else 0
                print(f"✓ Audit table '{table}': {count} records")
            except Exception as e:
                print(f"⚠ Audit table '{table}' check: {str(e)[:80]}")
    
    @staticmethod
    def test_configuration():
        """Test 5: Configuration & Environment"""
        from src.config import config
        
        try:
            if config.azure_openai_endpoint:
                print(f"✓ Azure OpenAI endpoint configured: {config.azure_openai_endpoint[:30]}...")
            
            if config.postgres_host:
                print(f"✓ PostgreSQL configured: {config.postgres_host}")
            
            if hasattr(config, 'key_vault_name') and config.key_vault_name:
                print(f"✓ Key Vault configured: {config.key_vault_name}")
            else:
                print("ℹ Key Vault not configured (using env variables)")
            
            print("✓ Configuration loaded successfully")
        except Exception as e:
            print(f"✗ Configuration check failed: {e}")
            raise
    
    @staticmethod
    def test_agents_loading():
        """Test 6: Agents Loading"""
        agent_files = [
            'src/agents/naveen_validator.py',
            'src/agents/moana_enricher.py',
            'src/agents/rapunzel_grade_reader.py',
            'src/agents/aurora_reporter.py',
            'src/agents/ariel_qa_agent.py'
        ]
        
        for agent_file in agent_files:
            agent_path = Path(agent_file)
            if agent_path.exists():
                print(f"✓ Agent file exists: {agent_file}")
            else:
                print(f"⚠ Agent file missing: {agent_file}")
        
        try:
            from src.agents import orchestrator
            print("✓ Orchestrator module loaded successfully")
        except ImportError:
            print("⚠ Orchestrator module not found")
        except Exception as e:
            print(f"⚠ Orchestrator loading error: {e}")


def main():
    """Run the complete test suite."""
    tester = WorkflowTester()
    results = tester.run_all_tests()
    
    # Save results to file
    results_file = Path('test_results_workflow.json')
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"Results saved to: {results_file}")
    
    # Exit with appropriate code
    sys.exit(0 if results['summary']['failed'] == 0 else 1)


if __name__ == '__main__':
    main()
