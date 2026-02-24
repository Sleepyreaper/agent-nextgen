from src.agents.ariel_qa_agent import ArielQAAgent as _BaseAriel


class ArielQAAgent(_BaseAriel):
    """Adapter subclass that implements the abstract `process` method so
    the agent can be instantiated by frameworks expecting `process()`.
    """

    async def process(self, message: str) -> str:
        try:
            result = await self.answer_question(application_id=None, question=message, conversation_history=None)
            return result.get('answer') if isinstance(result, dict) else str(result)
        except Exception:
            return message
