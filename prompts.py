def get_extraction_prompt(current_date: str, chunk: str) -> str:
    return f"""
    Extract SHORT, ATOMIC facts from the text.
    
    RULES:
    1. If it is a personal event, log, or action, determine the 'date' using {current_date} as today. Use YYYY-MM-DD.
    2. If it is static knowledge, specification, or general fact, set 'date' to null.
    3. Assign a simple 1-word 'category'.
    4. The 'fact' string should be a clean sentence.
    
    Text to process:
    {chunk}
    """

def get_analysis_prompt(current_date: str, raw_question: str) -> str:
    return f"""
    Analyze the user question.
    Current date: {current_date}
    1. 'is_analytical': true if the user asks for stats, chart, average, sum, count, or uses 'analyze:' prefix.
    2. 'category': guess the category from the question. Return null if general.
    3. 'standalone_question': rephrase the question to be standalone.
    
    Question: {raw_question}
    """

def get_system_instructions(current_date: str) -> str:
    return f"""
    Current Date: {current_date}
    You are a highly intelligent, conversational AI assistant.
    
    CORE RULES:
    1. Talk naturally. Use your vast general knowledge to answer the user's questions thoroughly.
    2. The provided Context is your "memory" of the user. Use it to personalize the interaction ONLY when it makes sense. 
    3. DO NOT force connections.
    4. ONLY act as a strict data analyst and generate charts ([CHART]JSON[/CHART]) if the user explicitly asked to calculate/chart their personal data or trends.
    5. If exact numerical values are missing, use general knowledge to provide reasonable average estimates. DO NOT refuse to calculate. State clearly that you are using estimated averages.
    6. Exclude missing days from calculations. Calculate averages ONLY based on present context.
    7. Resolve relative dates using {current_date}.
    """

def get_contextualize_prompt(history_str: str, question: str) -> str:
    return f"History:\n{history_str}\n\nFollow-up: {question}\n\nRephrase to standalone question:"