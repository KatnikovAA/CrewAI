"""Strict local export: invalid answers are handled by Task guardrails, not converter retries.

Pinned to CrewAI 1.15.28 Task's export hook. No SDK patching or extra LLM calls.
"""
from pydantic import BaseModel, ValidationError
from travel_planner.runtime import configure_runtime
configure_runtime()
from crewai import Task


class StructuredTask(Task):
    def _export_output(self, result):
        schema = self.output_pydantic or self.output_json
        if schema is None:
            return None, None
        try:
            model = (schema.model_validate(result.model_dump()) if isinstance(result, BaseModel)
                     else schema.model_validate_json(result))
        except (ValidationError, ValueError, TypeError):
            # Keep raw unchanged. Our guardrail reports precise errors and owns the retry budget.
            return None, None
        return (model, None) if self.output_pydantic else (None, model.model_dump())

    async def _aexport_output(self, result):
        return self._export_output(result)
