def get_extraction_prompt(current_date: str, chunk: str) -> str:
    return f"""
    Extract SHORT, ATOMIC facts from the text.
    
    RULES:
    1. If it is a personal event, log, or action, determine the 'date' using {current_date} as today. Use YYYY-MM-DD.
    2. If it is static knowledge, specification, or general fact, set 'date' to null.
    3. Assign a simple 1-word 'category'.
    4. The 'fact' string should be a clean sentence.
    5. EXPLICIT TIMEFRAME: ONLY prepend the current date if the user explicitly specifies a timeframe (e.g., "today", "tomorrow", "this month", "next week"). Example User input: "I want to eat pizza today." -> Extracted fact: "[{current_date}] The user wants to eat pizza."
    6. NO TIME WORD = NULL DATE: If the input lacks an explicit temporal trigger (like 'today', 'now', 'this week', 'yesterday'), you MUST set 'date' to null, even for personal statements. General states or skills (e.g., "I write in Go") are NOT logs and MUST have a null date unless a timeframe is mentioned.
    7. GENERAL GOALS: DO NOT add any dates to general goals, skills they want to learn, or long-term desires that lack a specific timeframe. Example User input: "I want to learn how to fly a drone." -> Extracted fact: "The user wants to learn how to fly a drone."
    
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
    3. ANALYTICAL MODE: Triggered ONLY if the current query requires data analysis. In this mode, generate [CHART]JSON[/CHART] and a summary.
    4. If the current question is just a regular chat message (even if previous ones were analytical), DO NOT generate charts. Talk like a human.
    5. Resolve relative dates using {current_date}.
    """