"""
Core fact-checking pipeline for Verum.

This is a refactor of the original notebook prototype:
- API keys are now read from environment variables (never hardcoded / never
  shipped to the browser extension).
- Whisper and the fact/opinion classifier are loaded once, at import time,
  and reused across requests (loading them per-request would be extremely slow).
"""

import os
import json
import logging

import pandas as pd
from tavily import TavilyClient
from huggingface_hub import InferenceClient
from transformers import pipeline
import whisper

logger = logging.getLogger("verum")

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
HF_API_KEY = os.environ.get("HF_API_KEY")

if not TAVILY_API_KEY or not HF_API_KEY:
    logger.warning(
        "TAVILY_API_KEY and/or HF_API_KEY are not set. Set them as environment "
        "variables / Space secrets before deploying."
    )

# ---------------------------------------------------------------------------
# Heavy models: load once at module import time, not per-request.
# ---------------------------------------------------------------------------
logger.info("Loading Whisper model (base)...")
_transcriber = whisper.load_model("base")

logger.info("Loading fact/opinion classifier...")
_classifier = pipeline("text-classification", model="lighteternal/fact-or-opinion-xlmr-el")


class FactChecker:

    SYSTEM_PROMPT = """
    You are a fact checker. Given a statement and relevant context, determine:

    - verdict: is the statement factually accurate? one of [true, false, cannot be sure]
    - reasoning: a concise explanation justifying the verdict, citing evidence from the context (max 50 words)

    responses should be in JSON format only
    """

    def __init__(self):
        self.tavily = TavilyClient(api_key=TAVILY_API_KEY)
        self.llm = InferenceClient(provider="auto", api_key=HF_API_KEY)
        self.current_sources = {}

    def search_web(self, statement):
        response = self.tavily.search(query=statement, max_results=3)
        return list(response["results"])

    def get_llm_response(self, context, statement):
        full_input = f"Statement: {statement}, Context: {context}"
        response = self.llm.chat_completion(
            model="Qwen/Qwen2.5-7B-Instruct",
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": full_input},
            ],
            max_tokens=125,
        )
        return response.choices[0].message.content

    def evaluate_statement(self, statement):
        self.current_sources.clear()
        search_context = self.search_web(statement)

        context = ""
        for result in search_context:
            website = result["title"]
            url = result["url"]
            content = result["content"]

            self.current_sources[website] = url
            context += content

        llm_response = self.get_llm_response(context, statement)

        cleaned = llm_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.replace("json\n", "", 1) if cleaned.startswith("json\n") else cleaned

        try:
            result_json = json.loads(cleaned)
        except json.JSONDecodeError:
            result_json = {
                "verdict": "cannot be sure",
                "reasoning": "Failed to parse LLM response as JSON.",
                "raw_response": llm_response,
            }

        return result_json

    def get_sources(self):
        if len(self.current_sources) > 0:
            return json.dumps(self.current_sources)
        return json.dumps({})


class AudioFactChecker:

    CONFIDENCE_THRESHOLD = 0.85
    STATEMENT_THRESHOLD = 6

    def __init__(self, audio_file):
        self.audio_file = audio_file
        self.fact_checker = FactChecker()
        self.audio_segments = []
        self.evaluation_results = {}

    def get_audio_segments(self):
        self.audio_segments = _transcriber.transcribe(self.audio_file)["segments"]

    def is_fact(self, statement):
        res = _classifier([statement])
        verdict = res[0]["label"]
        confidence = res[0]["score"]
        return (verdict == "LABEL_1") and (confidence > self.CONFIDENCE_THRESHOLD)

    def evaluate_statements(self):
        if not self.audio_segments:
            return {
                "statement": [], "start_time": [], "end_time": [],
                "verdict": [], "reasoning": [], "sources": [], "claim_weight": [],
            }

        evaluation_data = {
            "statement": [], "start_time": [], "end_time": [],
            "verdict": [], "reasoning": [], "sources": [], "claim_weight": [],
        }

        for seg in self.audio_segments:
            statement = seg["text"]
            start_time = seg["start"]
            end_time = seg["end"]

            for sub_statement in statement.split("."):
                if len(sub_statement) > self.STATEMENT_THRESHOLD and self.is_fact(sub_statement):
                    raw_evaluation = self.fact_checker.evaluate_statement(sub_statement)
                    final_verdict = raw_evaluation.get("verdict", "cannot be sure")
                    final_reasoning = raw_evaluation.get("reasoning", "")
                    final_sources = self.fact_checker.get_sources()

                    evaluation_data["statement"].append(sub_statement.strip())
                    evaluation_data["start_time"].append(start_time)
                    evaluation_data["end_time"].append(end_time)
                    evaluation_data["verdict"].append(final_verdict)
                    evaluation_data["reasoning"].append(final_reasoning)
                    evaluation_data["sources"].append(final_sources)
                    evaluation_data["claim_weight"].append(len(sub_statement.replace(" ", "")))

        return evaluation_data

    def fact_check_audio(self):
        self.get_audio_segments()
        evaluation_results = pd.DataFrame(self.evaluate_statements())
        reliability_score = self.get_reliability_score(evaluation_results)
        return evaluation_results, reliability_score

    @staticmethod
    def get_reliability_score(eval_results_df):
        if eval_results_df.empty:
            return None  # no checkable factual claims found

        total_claim_weight = eval_results_df["claim_weight"].sum()
        if total_claim_weight == 0:
            return None

        not_true_weight = eval_results_df.loc[
            eval_results_df["verdict"] != "true", "claim_weight"
        ].sum()
        true_weight = total_claim_weight - not_true_weight

        return round(true_weight / total_claim_weight, 2)
