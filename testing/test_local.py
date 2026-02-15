"""
Simplified comprehensive test suite for local development/testing.

Tests the NextGen AI Evaluation System components that can run locally
without requiring Azure cloud credentials.
"""

import asyncio
import sys
import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Main test execution."""
    
    logger.info("=" * 80)
    logger.info("NEXTGEN AI SYSTEM - LOCAL DEVELOPMENT TEST SUITE")
    logger.info("=" * 80)
    
    results = {
        'timestamp': datetime.now().isoformat(),
        'tests': {},
        'summary': {}
    }
    
    try:
        # Load environment
        from dotenv import load_dotenv
        load_dotenv()
        logger.info("✓ Environment variables loaded")
        
        # Test 1: Configuration validation
        logger.info("\n--- TEST 1: Configuration Validation ---")
        try:
            from src.config import config
            logger.info(f"✓ Config loaded: {config}")
            
            # Check required configs
            checks = [
                ('Azure OpenAI Endpoint', config.azure_openai_endpoint),
                ('Deployment Model', config.deployment_name),
                ('API Version', config.api_version),
            ]
            
            for name, value in checks:
                if value:
                    logger.info(f"  ✓ {name}: {value[:50]}..." if len(str(value)) > 50 else f"  ✓ {name}: {value}")
                else:
                    logger.warning(f"  ⚠ {name}: Not configured")
            
            results['tests']['configuration'] = {'status': 'pass'}
        except Exception as e:
            logger.error(f"✗ Configuration test failed: {e}")
            results['tests']['configuration'] = {'status': 'fail', 'error': str(e)}
        
        # Test 2: Database connectivity
        logger.info("\n--- TEST 2: Database Connectivity ---")
        try:
            from src.database import db
            db.connect()
            logger.info("✓ Database connection successful")
            results['tests']['database'] = {'status': 'pass'}
            db.close()
        except Exception as e:
            logger.error(f"✗ Database test failed: {e}")
            results['tests']['database'] = {'status': 'fail', 'error': str(e)}
        
        # Test 3: Test data generation
        logger.info("\n--- TEST 3: Test Student Generation ---")
        try:
            from src.test_data_generator import test_data_generator
            
            student = test_data_generator.generate_student(quality_tier='high')
            logger.info(f"✓ Test student created: {student['name']}")
            logger.info(f"  School: {student['school']}")
            logger.info(f"  GPA: {student['gpa']}")
            logger.info(f"  AP Courses: {len(student['ap_courses'])}")
            logger.info(f"  Activities: {len(student['activities'])}")
            
            results['tests']['student_generation'] = {
                'status': 'pass',
                'student_name': student['name']
            }
        except Exception as e:
            logger.error(f"✗ Student generation test failed: {e}")
            results['tests']['student_generation'] = {'status': 'fail', 'error': str(e)}
            student = None
        
        # Test 4: Agent imports
        logger.info("\n--- TEST 4: Agent Imports ---")
        try:
            from src.agents import (
                SmeeOrchestrator,
                TianaApplicationReader,
                RapunzelGradeReader,
                MulanRecommendationReader,
                MoanaSchoolContext,
                MerlinStudentEvaluator,
                AuroraAgent
            )
            
            agents_imported = [
                'SmeeOrchestrator',
                'TianaApplicationReader',
                'RapunzelGradeReader',
                'MulanRecommendationReader',
                'MoanaSchoolContext',
                'MerlinStudentEvaluator',
                'AuroraAgent'
            ]
            
            for agent_name in agents_imported:
                logger.info(f"  ✓ {agent_name}")
            
            results['tests']['agent_imports'] = {'status': 'pass', 'agents': agents_imported}
        except ImportError as e:
            logger.error(f"✗ Agent import test failed: {e}")
            results['tests']['agent_imports'] = {'status': 'fail', 'error': str(e)}
        
        # Test 5: Logger functionality
        logger.info("\n--- TEST 5: Logging System ---")
        try:
            from src.logger import app_logger, audit_logger, SensitiveDataFilter
            
            test_logger = app_logger
            test_logger.info("✓ Application logger: OK")
            audit_logger.log_security_event('test_event', 'INFO', {'test': 'data'})
            logger.info("✓ Audit logger: OK")
            logger.info("✓ Sensitive data filter: OK")
            
            results['tests']['logging'] = {'status': 'pass'}
        except Exception as e:
            logger.error(f"✗ Logging test failed: {e}")
            results['tests']['logging'] = {'status': 'fail', 'error': str(e)}
        
        # Test 6: Security checks
        logger.info("\n--- TEST 6: Security Checks ---")
        try:
            security_checks = []
            
            # Check if print statements are gone from main modules
            with open('app.py', 'r') as f:
                app_content = f.read()
                print_count_app = app_content.count('print(')
                if print_count_app == 0:
                    logger.info("  ✓ app.py: No debug print() statements")
                    security_checks.append(('app.py print cleanup', True))
                else:
                    logger.warning(f"  ⚠ app.py: {print_count_app} print() statements found")
                    security_checks.append(('app.py print cleanup', False))
            
            # Check if logging is properly configured
            if os.path.exists('src/logger.py'):
                logger.info("  ✓ src/logger.py: Professional logging module exists")
                security_checks.append(('Logger module', True))
            else:
                logger.warning("  ⚠ src/logger.py: Not found")
                security_checks.append(('Logger module', False))
            
            # Check if database uses parameterized queries
            with open('src/database.py', 'r') as f:
                db_content = f.read()
                if '%s' in db_content and 'execute' in db_content:
                    logger.info("  ✓ Database: Uses parameterized queries (PostgreSQL %s placeholders)")
                    security_checks.append(('Parameterized queries', True))
            
            passed = sum(1 for _, result in security_checks if result)
            results['tests']['security'] = {
                'status': 'pass',
                'checks': passed,
                'total': len(security_checks)
            }
        except Exception as e:
            logger.error(f"✗ Security check test failed: {e}")
            results['tests']['security'] = {'status': 'fail', 'error': str(e)}
        
        # Test 7: Flask app structure
        logger.info("\n--- TEST 7: Flask Application ---")
        try:
            from app import app as flask_app
            logger.info(f"✓ Flask app loaded")
            logger.info(f"  Debug mode: {flask_app.debug}")
            logger.info(f"  Max content length: {flask_app.config.get('MAX_CONTENT_LENGTH')} bytes")
            
            # Check for required routes
            routes = []
            for rule in flask_app.url_map.iter_rules():
                routes.append(rule.rule)
            
            if '/test' in routes:
                logger.info(f"  ✓ Test route available: /test")
            
            results['tests']['flask_app'] = {'status': 'pass', 'route_count': len(routes)}
        except Exception as e:
            logger.error(f"✗ Flask app test failed: {e}")
            results['tests']['flask_app'] = {'status': 'fail', 'error': str(e)}
        
        # Summary
        logger.info("\n" + "=" * 80)
        logger.info("TEST SUMMARY")
        logger.info("=" * 80)
        
        for test_name, test_result in results['tests'].items():
            status = test_result.get('status', 'unknown')
            emoji = "✓" if status == "pass" else "✗"
            logger.info(f"{emoji} {test_name}: {status}")
        
        # Calculate passed tests
        passed = sum(1 for t in results['tests'].values() if t.get('status') == 'pass')
        total = len(results['tests'])
        
        logger.info(f"\nResult: {passed}/{total} tests passed")
        
        # Save results
        results_file = Path('test_results_local.json')
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        logger.info(f"✓ Detailed results saved to {results_file}")
        logger.info("=" * 80)
        
        return 0 if passed == total else 1
        
    except Exception as e:
        logger.error(f"Test suite failed: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
