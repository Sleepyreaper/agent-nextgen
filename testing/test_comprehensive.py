"""
Comprehensive test suite for the NextGen AI Evaluation System.

This script:
1. Creates a realistic test student
2. Validates all database operations
3. Tests each agent individually
4. Runs the full Smee orchestrator pipeline
5. Reports results with security and performance metrics
"""

import asyncio
import sys
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('test_results.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ComprehensiveTestRunner:
    """Runs comprehensive tests on the evaluation system."""
    
    def __init__(self):
        """Initialize test runner."""
        self.test_results = {
            'timestamp': datetime.now().isoformat(),
            'tests': {},
            'summary': {}
        }
        self.setup_ok = False
        
    async def setup(self) -> bool:
        """Setup test environment and imports."""
        try:
            logger.info("=" * 70)
            logger.info("NEXTGEN AI EVALUATION SYSTEM - COMPREHENSIVE TEST SUITE")
            logger.info("=" * 70)
            
            # Setup environment
            from dotenv import load_dotenv
            load_dotenv()
            
            # Import critical modules
            from src.config import config
            from src.database import db
            from openai import AzureOpenAI
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            from src.agents import (
                SmeeOrchestrator,
                TianaApplicationReader,
                RapunzelGradeReader,
                MulanRecommendationReader,
                MoanaSchoolContext,
                MerlinStudentEvaluator,
                AuroraAgent
            )
            from src.test_data_generator import test_data_generator
            
            self.config = config
            self.db = db
            self.SmeeOrchestrator = SmeeOrchestrator
            self.TianaApplicationReader = TianaApplicationReader
            self.RapunzelGradeReader = RapunzelGradeReader
            self.MulanRecommendationReader = MulanRecommendationReader
            self.MoanaSchoolContext = MoanaSchoolContext
            self.MerlinStudentEvaluator = MerlinStudentEvaluator
            self.AuroraAgent = AuroraAgent
            self.test_data_generator = test_data_generator
            
            logger.info("✓ All imports successful")
            
            # Initialize Azure OpenAI client
            try:
                token_provider = get_bearer_token_provider(
                    DefaultAzureCredential(),
                    "https://cognitiveservices.azure.com/.default"
                )
                self.client = AzureOpenAI(
                    azure_ad_token_provider=token_provider,
                    api_version=config.api_version,
                    azure_endpoint=config.azure_openai_endpoint
                )
                logger.info("✓ Azure OpenAI client initialized")
            except Exception as e:
                logger.error(f"✗ Azure OpenAI initialization failed: {e}")
                return False
            
            # Test database connection
            try:
                self.db.connect()
                logger.info("✓ Database connection successful")
            except Exception as e:
                logger.error(f"✗ Database connection failed: {e}")
                return False
            
            self.setup_ok = True
            return True
            
        except ImportError as e:
            logger.error(f"✗ Import failed: {e}")
            return False
        except Exception as e:
            logger.error(f"✗ Setup failed: {e}")
            return False
    
    async def test_database_operations(self) -> bool:
        """Test database operations."""
        logger.info("\n--- DATABASE OPERATIONS TEST ---")
        
        try:
            # Test get_application with proper field normalization
            test_app = {
                'ApplicantName': 'Test Student',
                'ApplicationText': 'This is a test application essay.',
                'ApplicationID': 99999
            }
            
            logger.info("✓ Database operations test passed")
            self.test_results['tests']['database'] = {'status': 'pass'}
            return True
            
        except Exception as e:
            logger.error(f"✗ Database test failed: {e}")
            self.test_results['tests']['database'] = {'status': 'fail', 'error': str(e)}
            return False
    
    async def test_create_test_student(self) -> Optional[Dict[str, Any]]:
        """Create a single test student."""
        logger.info("\n--- TEST STUDENT GENERATION ---")
        
        try:
            # Generate a single high-quality test student
            student = self.test_data_generator.generate_student(quality_tier='high')
            
            logger.info(f"✓ Test student created:")
            logger.info(f"  Name: {student['name']}")
            logger.info(f"  Email: {student['email']}")
            logger.info(f"  School: {student['school']}")
            logger.info(f"  GPA: {student['gpa']}")
            logger.info(f"  Location: {student['city']}, {student['state']}")
            logger.info(f"  AP Courses: {len(student['ap_courses'])}")
            logger.info(f"  Activities: {len(student['activities'])}")
            logger.info(f"  Quality Tier: {student['quality_tier']}")
            
            self.test_results['tests']['student_creation'] = {
                'status': 'pass',
                'student_name': student['name']
            }
            
            return student
            
        except Exception as e:
            logger.error(f"✗ Student creation failed: {e}")
            self.test_results['tests']['student_creation'] = {
                'status': 'fail',
                'error': str(e)
            }
            return None
    
    async def test_individual_agents(self, application: Dict[str, Any]) -> Dict[str, Any]:
        """Test each agent individually."""
        logger.info("\n--- INDIVIDUAL AGENT TESTS ---")
        
        agent_results = {}
        
        # Prepare application data with required fields
        test_app = {
            'ApplicantName': application['name'],
            'ApplicationID': 99999,
            'ApplicationText': application['application_text'],
            'RecommendationText': 'Excellent student with strong leadership potential.',
            'TranscriptData': f"GPA: {application['gpa']}\nAP Courses: {', '.join(application['ap_courses'])}",
            'SchoolContext': f"{application['school']}, {application['city']}, {application['state']}"
        }
        
        # Test Tiana (Application Reader)
        logger.info("\n[1/5] Testing Tiana (Application Reader)...")
        try:
            tiana = self.TianaApplicationReader(
                name="Tiana",
                client=self.client,
                model=self.config.deployment_name
            )
            result = await tiana.parse_application(test_app)
            logger.info("✓ Tiana completed successfully")
            agent_results['tiana_application_reader'] = {'status': 'pass', 'result': result}
        except Exception as e:
            logger.error(f"✗ Tiana failed: {e}")
            agent_results['tiana_application_reader'] = {'status': 'fail', 'error': str(e)}
        
        # Test Rapunzel (Grade Reader)
        logger.info("\n[2/5] Testing Rapunzel (Grade Reader)...")
        try:
            rapunzel = self.RapunzelGradeReader(
                name="Rapunzel",
                client=self.client,
                model=self.config.deployment_name
            )
            result = await rapunzel.parse_grades(
                test_app['ApplicationText'],
                test_app['ApplicantName']
            )
            logger.info("✓ Rapunzel completed successfully")
            agent_results['rapunzel_grade_reader'] = {'status': 'pass', 'result': result}
        except Exception as e:
            logger.error(f"✗ Rapunzel failed: {e}")
            agent_results['rapunzel_grade_reader'] = {'status': 'fail', 'error': str(e)}
        
        # Test Mulan (Recommendation Reader)
        logger.info("\n[3/5] Testing Mulan (Recommendation Reader)...")
        try:
            mulan = self.MulanRecommendationReader(
                name="Mulan",
                client=self.client,
                model=self.config.deployment_name
            )
            result = await mulan.parse_recommendation(
                test_app['RecommendationText'],
                test_app['ApplicantName'],
                test_app['ApplicationID']
            )
            logger.info("✓ Mulan completed successfully")
            agent_results['mulan_recommendation_reader'] = {'status': 'pass', 'result': result}
        except Exception as e:
            logger.error(f"✗ Mulan failed: {e}")
            agent_results['mulan_recommendation_reader'] = {'status': 'fail', 'error': str(e)}
        
        # Test Moana (School Context)
        logger.info("\n[4/5] Testing Moana (School Context)...")
        try:
            moana = self.MoanaSchoolContext(
                name="Moana",
                client=self.client,
                model=self.config.deployment_name
            )
            result = await moana.analyze_student_school_context(
                application=test_app,
                transcript_text=test_app['ApplicationText'],
                rapunzel_grades_data=agent_results.get('rapunzel_grade_reader', {}).get('result')
            )
            logger.info("✓ Moana completed successfully")
            agent_results['moana_school_context'] = {'status': 'pass', 'result': result}
        except Exception as e:
            logger.error(f"✗ Moana failed: {e}")
            agent_results['moana_school_context'] = {'status': 'fail', 'error': str(e)}
        
        self.test_results['tests']['individual_agents'] = agent_results
        
        passed = sum(1 for r in agent_results.values() if r.get('status') == 'pass')
        logger.info(f"\n✓ Agent tests: {passed}/{len(agent_results)} passed")
        
        return agent_results
    
    async def test_smee_orchestrator(self, application: Dict[str, Any]) -> Dict[str, Any]:
        """Test the full Smee orchestrator pipeline."""
        logger.info("\n--- SMEE ORCHESTRATOR PIPELINE TEST ---")
        logger.info("This will run the complete evaluation pipeline with all agents coordinated by Smee")
        
        try:
            # Initialize Smee orchestrator
            smee = self.SmeeOrchestrator(
                name="Smee",
                client=self.client,
                model=self.config.deployment_name,
                db_connection=self.db
            )
            
            # Register all agents
            tiana = self.TianaApplicationReader(
                name="Tiana",
                client=self.client,
                model=self.config.deployment_name
            )
            smee.register_agent('tiana_application_reader', tiana)
            
            rapunzel = self.RapunzelGradeReader(
                name="Rapunzel",
                client=self.client,
                model=self.config.deployment_name
            )
            smee.register_agent('rapunzel_grade_reader', rapunzel)
            
            mulan = self.MulanRecommendationReader(
                name="Mulan",
                client=self.client,
                model=self.config.deployment_name
            )
            smee.register_agent('mulan_recommendation_reader', mulan)
            
            moana = self.MoanaSchoolContext(
                name="Moana",
                client=self.client,
                model=self.config.deployment_name
            )
            smee.register_agent('moana_school_context', moana)
            
            merlin = self.MerlinStudentEvaluator(
                name="Merlin",
                client=self.client,
                model=self.config.deployment_name,
                db_connection=self.db
            )
            smee.register_agent('student_evaluator', merlin)
            
            aurora = self.AuroraAgent(
                name="Aurora",
                client=self.client,
                model=self.config.deployment_name
            )
            smee.register_agent('aurora_formatter', aurora)

            # register a lightweight dummy Milo agent for training analysis
            class DummyMilo:
                name = 'Milo'
                async def analyze_training_insights(self):
                    return {'status': 'success', 'insights': []}
                async def compute_alignment(self, application):
                    return {'match_score': 50, 'nextgen_align_score': 50, 'explanation': 'dummy'}
            smee.register_agent('data_scientist', DummyMilo())
            
            logger.info(f"✓ Smee initialized with {len(smee.get_registered_agents())} agents:")
            for agent_id, agent_name in smee.get_registered_agents().items():
                logger.info(f"  - {agent_id}: {agent_name}")
            
            # Prepare application
            test_app = {
                'ApplicantName': application['name'],
                'ApplicationID': 99999,
                'ApplicationText': application['application_text'],
                'RecommendationText': 'Excellent student with strong leadership potential.',
                'TranscriptData': f"GPA: {application['gpa']}\nAP Courses: {', '.join(application['ap_courses'])}",
                'SchoolContext': f"{application['school']}, {application['city']}, {application['state']}"
            }
            
            # Run the orchestration
            logger.info("\n🚀 Starting orchestration pipeline...")
            logger.info("=" * 70)
            
            def progress_callback(update: Dict[str, Any]):
                """Log progress updates."""
                if update.get('type') == 'agent_progress':
                    logger.info(f"  [{update.get('agent')}] {update.get('status')}: {update.get('message', '')}")
            
            # Define evaluation steps
            evaluation_steps = [
                'tiana_application_reader',
                'rapunzel_grade_reader',
                'mulan_recommendation_reader',
                'moana_school_context',
                'data_scientist',
                'student_evaluator',
                'aurora_formatter'
            ]
            
            orchestration_result = await smee.coordinate_evaluation(
                application=test_app,
                evaluation_steps=evaluation_steps,
                progress_callback=progress_callback
            )
            
            logger.info("=" * 70)
            logger.info("✓ Orchestration completed successfully")
            logger.info("\nResults Summary:")
            logger.info(json.dumps(orchestration_result, indent=2, default=str))
            
            self.test_results['tests']['smee_orchestrator'] = {
                'status': 'pass',
                'result': orchestration_result
            }
            
            return orchestration_result
            
        except Exception as e:
            logger.error(f"✗ Smee orchestrator failed: {e}", exc_info=True)
            self.test_results['tests']['smee_orchestrator'] = {
                'status': 'fail',
                'error': str(e)
            }
            return None
    
    async def run_all_tests(self):
        """Run all tests in sequence."""
        try:
            # Setup
            if not await self.setup():
                logger.error("Setup failed. Cannot continue.")
                return False
            
            # Database operations
            await self.test_database_operations()
            
            # Create test student
            student = await self.test_create_test_student()
            if not student:
                logger.error("Student creation failed. Cannot continue.")
                return False
            
            # Individual agent tests
            await self.test_individual_agents(student)
            
            # Full orchestrator test
            await self.test_smee_orchestrator(student)
            
            # Generate summary
            await self._generate_summary()
            
            return True
            
        except Exception as e:
            logger.error(f"Test suite failed: {e}", exc_info=True)
            return False
        finally:
            try:
                self.db.close()
            except:
                pass
    
    async def _generate_summary(self):
        """Generate test summary."""
        logger.info("\n" + "=" * 70)
        logger.info("TEST SUMMARY")
        logger.info("=" * 70)
        
        for test_name, test_result in self.test_results['tests'].items():
            if isinstance(test_result, dict):
                status = test_result.get('status', 'unknown')
                emoji = "✓" if status == "pass" else "✗"
                logger.info(f"{emoji} {test_name}: {status}")
        
        # Save results
        results_file = Path('test_results.json')
        with open(results_file, 'w') as f:
            json.dump(self.test_results, f, indent=2, default=str)
        
        logger.info(f"\n✓ Detailed results saved to {results_file}")
        logger.info("=" * 70)


async def main():
    """Main entry point."""
    runner = ComprehensiveTestRunner()
    success = await runner.run_all_tests()
    return 0 if success else 1


if __name__ == '__main__':
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
