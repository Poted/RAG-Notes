def get_extraction_prompt(current_date: str, chunk: str) -> str:
    return f"""
    Extract SHORT, ATOMIC facts from the text. 
    Current reference date is: {current_date}

    CATEGORIZATION RULES:
    1. Assign exactly ONE lowercase word as 'category'.
    2. BE BROAD AND CONSISTENT: Group similar topics under broad nouns. 
       (Examples of good categories: 'fitness', 'diet', 'finance', 'work', 'health', 'hobby', 'car', 'home').
    3. AVOID hyper-specific words. (e.g., use 'diet' instead of 'apple', use 'finance' instead of 'invoice').

    DATE & LOGGING RULES (STRICT):
    1. RELATIVE DATES: If the text mentions "today", "yesterday", "now", "tomorrow", "two days ago", etc.:
       - CALCULATE the exact date based on {current_date}.
       - PREPEND to 'fact' in brackets: [YYYY-MM-DD].
       - REMOVE the relative time word from the final 'fact' text.

    2. IMPLICIT LOGS: If the text describes a specific action or event (e.g., "I ate a steak", "I paid taxes") but NO time is mentioned:
       - ASSUME it happened today. 
       - PREPEND [{current_date}] to the 'fact'.

    3. STATIC KNOWLEDGE: If the fact is a general truth, skill, or trait (e.g., "I like Python"):
       - SET 'date' to null.
       - DO NOT prepend any date to the 'fact'.

    Text to process:
    {chunk}
    """

def get_analysis_prompt(current_date: str, history_str: str, raw_question: str) -> str:
    return f"""
    Analyze the user question.
    Current date: {current_date}
    
    Conversation history (last 4 messages):
    {history_str}
    
    CRITICAL RULE: Evaluate 'is_analytical' based ONLY on the CURRENT question below. 
    Ignore analysis triggers from the conversation history.

    1. 'is_analytical': true ONLY if the current question starts with 'analyze:', contains 'analyze:', or explicitly asks for stats/charts.
    2. 'category': guess the category from the question. Return null if general.
    3. 'standalone_question': rephrase the question to be standalone. Resolve pronouns using history.
    
    Current Question: {raw_question}
    """

def get_system_instructions(current_date: str, history_str: str) -> str:
    return f"""
    Current Date: {current_date}
    You are a highly intelligent, conversational AI assistant.
    
    Conversation history (last 4 messages):
    {history_str}
    
    CORE RULES:
    1. Talk naturally.
    2. Use the provided Context only when relevant.
    3. ANALYTICAL MODE: Triggered ONLY if the current query requires data analysis. In this mode, generate a chart and a summary.
    4. If the current question is just a regular chat message (even if previous ones were analytical), DO NOT generate charts. Talk like a human.
    5. Resolve relative dates using {current_date}.

    If the user asks for a chart or graph, you MUST use Chart.js format.
    Return the chart configuration in the exact format below (and nothing else):

    [CHART]
    ```json
    {{
      "type": "pie", 
      "data": {{
        "labels": ["Carbs", "Fats", "Protein"],
        "datasets": [{{
          "data": [45, 35, 20]
        }}]
      }}
    }}
    ```
    [/CHART]
    Ensure the JSON structure strictly contains 'type', 'data', 'labels', and 'datasets' keys.
    """