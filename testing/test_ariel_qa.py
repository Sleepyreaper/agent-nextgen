"""
Test ARIEL Q&A Agent
Tests the Q&A functionality for asking questions about students.
"""

import asyncio
import json
from src.agents.ariel_qa_agent import ArielQAAgent


async def test_ariel_qa():
    """Test ARIEL Q&A agent with a sample student."""
    print("=" * 60)
    print("ARIEL Q&A Agent Test")
    print("=" * 60)
    
    ariel = ArielQAAgent()
    
    # Test with a sample application ID
    # In real usage, this would be an actual student ID from the database
    test_application_id = 1
    
    test_questions = [
        "What is this student's GPA and how strong is it academically?",
        "What AP courses are available at this student's school?",
        "How does this student's academic rigor score compare to their school context?",
        "What were the key findings from the evaluation agents?"
    ]
    
    print(f"\n📚 Testing Q&A for Application ID: {test_application_id}")
    print("-" * 60)
    
    conversation_history = []
    
    for i, question in enumerate(test_questions, 1):
        print(f"\n🔸 Question {i}: {question}")
        print("-" * 60)
        
        result = await ariel.answer_question(
            application_id=test_application_id,
            question=question,
            conversation_history=conversation_history
        )
        
        if result['success']:
            print(f"✅ Success!")
            print(f"\n📖 Answer:\n{result['answer']}\n")
            
            print(f"📊 Reference Data:")
            print(f"  - Student: {result['reference_data'].get('name', 'N/A')}")
            print(f"  - School: {result['reference_data'].get('school', 'N/A')}")
            print(f"  - GPA: {result['reference_data'].get('gpa', 'N/A')}")
            print(f"  - Sources: {', '.join(result['reference_data'].get('data_sources', []))}")
            
            # Add to conversation history for context
            conversation_history.append({
                "question": question,
                "answer": result['answer']
            })
        else:
            print(f"❌ Error: {result.get('error', 'Unknown error')}")
    
    print("\n" + "=" * 60)
    print("🎉 ARIEL Q&A Test Complete!")
    print("=" * 60)


async def test_ariel_single_question():
    """Test a single Q&A interaction."""
    print("\n" + "=" * 60)
    print("ARIEL Single Question Test")
    print("=" * 60)
    
    ariel = ArielQAAgent()
    application_id = 1
    question = "Tell me about this student's academic performance."
    
    print(f"\nApplication ID: {application_id}")
    print(f"Question: {question}\n")
    print("-" * 60)
    
    result = await ariel.answer_question(
        application_id=application_id,
        question=question,
        conversation_history=[]
    )
    
    if result['success']:
        print("✅ Answer received!\n")
        print(result['answer'])
        print("\n" + "-" * 60)
        print(f"Reference Data: {json.dumps(result['reference_data'], indent=2)}")
    else:
        print(f"❌ Error: {result['error']}")
    
    print("\n" + "=" * 60)


async def main():
    """Run all tests."""
    try:
        # Run comprehensive test
        await test_ariel_qa()
        
        # Run single question test
        await test_ariel_single_question()
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
