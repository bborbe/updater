---
status: created
---

<summary>
- A bug in JSON response parsing only needs to be fixed in one place instead of three
- All Claude-powered analysis features share the same response extraction logic
- No change to user-visible behavior — same analysis results, same error messages
- Reduces maintenance risk from copy-pasted code that can drift out of sync
- Test coverage for JSON extraction is direct and explicit
</summary>

<objective>
Claude response parsing logic exists in three identical copies. A fix to one copy must be manually applied to the other two, creating maintenance risk. Consolidate into a single shared helper so parsing bugs are fixed once.
</objective>

<context>
Read CLAUDE.md for project conventions.
Read `src/updater/claude_analyzer.py`.

The identical block appears at three locations (lines ~283-296, ~430-442, ~564-576):
```python
if "```json" in response_text:
    start = response_text.find("```json") + 7
    end = response_text.find("```", start)
    response_text = response_text[start:end].strip()
elif "```" in response_text:
    start = response_text.find("```") + 3
    end = response_text.find("```", start)
    response_text = response_text[start:end].strip()
else:
    start = response_text.find("{")
    end = response_text.rfind("}") + 1
    if start != -1 and end > start:
        response_text = response_text[start:end].strip()

try:
    analysis = json.loads(response_text)
except json.JSONDecodeError as e:
    raise ClaudeError(...)
```
</context>

<requirements>
1. Create `_extract_json_from_response(response_text: str) -> dict[str, Any]` in `claude_analyzer.py` (use existing `Any` import from `typing`):
   - Performs the markdown code block stripping (```json, ```, plain brace matching)
   - Calls `json.loads()` on the result
   - Raises `ClaudeError` on `json.JSONDecodeError` with format: `f"Failed to parse Claude response as JSON: {e}\nResponse: {response_text}"`
   - Returns the parsed dict

2. Replace all three duplicated blocks with a call to `_extract_json_from_response(response_text)`

3. Update `tests/test_claude_analyzer.py`:
   - Add direct tests for `_extract_json_from_response()` covering: json code block, plain code block, no code block with braces, no JSON at all (error case)
   - Existing tests that test JSON parsing indirectly should still pass
</requirements>

<constraints>
- Do NOT change any prompt text or retry logic
- Do NOT change the return types of the three public functions
- Do NOT change metrics recording
- Do NOT commit — dark-factory handles git
</constraints>

<verification>
Run `make precommit` — must pass with exit code 0.
Run `uv run pytest tests/test_claude_analyzer.py -v` — all tests must pass.
</verification>
