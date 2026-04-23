import os
import genai

def ask_llm(prompt, llm_origin="Gemini", llm_model="gemini-2.5-flash"):

    if llm_origin == "Gemini":
        # Configure Google GenAI client
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Gemini API key must be provided")
        
        client = genai.Client(api_key=api_key)
        print(f"Initialized Google GenAI model: {llm_model}")
        
        # Generate and return answer based on optimized prompt
        try:
            response = client.models.generate_content(model=llm_model, contents=prompt)
            return response.text.strip()
        
        except Exception as e:
            return f"Error calling Google GenAI API: {str(e)}"
    
    elif llm_origin == "Qwen":
        if vllm compatible:
            vllm
        else:
            load from hugging face


    elif llm_origin == "OpenAI":
        