# FrontDesk tool schemas (fd-tools/1)

Given to Gemini as schema-only `FunctionDeclaration`s with automatic function calling disabled. The model may not enforce every keyword, so the server-side Pydantic models in `contracts/models/policy.py` (`extra="forbid"`) are the authoritative check; a failure is DENY `INVALID_ARGUMENTS`, never an exception. `tool_result.schema.json` is the minimal result the model sees.
